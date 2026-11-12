# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render diagnostics core: failure events, GPU and host memory, background tasks.

A renderer can show a fallback material without any error when a material,
texture or MDL module fails to compile, load or become resident, for example
on a small MIG partition. The modules of this feature make those cases visible:

* this module keeps failure events (:class:`RenderDiagnostics`), reads GPU and
  host memory, checks them against the documented minimum for the scene size,
  and owns the background tasks of the feature with their shutdown;
* ``render_native_log`` reads the native renderer log, where the failures are;
* ``render_material_report`` reports each material with its renderer state;
* ``render_probe`` renders each material in an isolated studio and compares it
  with a reference, to find a material that the renderer shows wrong.

The module has no import of ``omni.ui`` and no import of ``pxr`` at module
level, so it is safe to import before any renderer exists.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import weakref
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("ovui.render_diagnostics")

GIB = 1024**3
MIB = 1024**2

#: Environment variable that replaces the minimum GPU memory (GiB) from the table.
MIN_GPU_MEMORY_ENV = "OVUI_MIN_GPU_MEMORY_GIB"
#: Set to 1 to refuse a scene when GPU or host memory is below the minimum
#: (the default is to warn and continue).
STRICT_ENV = "OVUI_STRICT_RESOURCE_CHECK"
#: Seconds to wait for one background task to stop at shutdown.
STOP_TIMEOUT = 2.0

#: Scene-wide events name no material: the failure cannot be tied to one.
SCENE = "(scene)"


class InsufficientResourcesError(RuntimeError):
    """GPU or host memory is below the minimum, and ``OVUI_STRICT_RESOURCE_CHECK=1``."""


class BackgroundTaskStuckError(RuntimeError):
    """A background task did not stop in its time limit at shutdown."""


# --------------------------------------------------------------------------
# Minimum resources by scene size
# --------------------------------------------------------------------------

#: (largest composed layer bytes for the tier, minimum GPU GiB, minimum host GiB,
#: partition advice). GPU values are the memory that the process can see; a
#: nominal "24 GB" MIG partition shows about 23 GiB and "48 GB" about 47 GiB, so
#: each value is below its nominal size. The 24 GiB and 48 GiB limits come from
#: one field report (an 800 MB scene failed on 1g.24gb with a 64 GiB pod and was
#: correct on 2g.48gb with a 128 GiB pod and on L40); the smaller tiers are
#: conservative estimates, not measurements.
_TIERS: tuple[tuple[Optional[int], float, float, str], ...] = (
    (100 * MIB, 14.0, 16.0, "16 GB class GPU or larger"),
    (500 * MIB, 20.0, 48.0, "24 GB class GPU or larger (for MIG: 1g.24gb is the smallest)"),
    (None, 44.0, 96.0, "48 GB class GPU or larger (for MIG: 2g.48gb or larger, not 1g.24gb)"),
)


@dataclass(frozen=True)
class ResourceMinimum:
    scene_bytes: int
    min_gpu_gib: float
    min_host_gib: float
    advice: str


def minimum_for_scene(scene_bytes: int) -> ResourceMinimum:
    """Return the documented minimum resources for a composed scene size."""

    scene_bytes = max(0, int(scene_bytes))
    for limit, gpu, host, advice in _TIERS:
        if limit is None or scene_bytes < limit:
            minimum = ResourceMinimum(scene_bytes, gpu, host, advice)
            break
    override = os.environ.get(MIN_GPU_MEMORY_ENV, "").strip()
    if override:
        try:
            minimum = ResourceMinimum(
                scene_bytes, float(override), minimum.min_host_gib,
                f"GPU with at least {float(override):g} GiB ({MIN_GPU_MEMORY_ENV})",
            )
        except ValueError:
            LOGGER.warning("%s=%r is not a number; the table value is used", MIN_GPU_MEMORY_ENV, override)
    return minimum


# --------------------------------------------------------------------------
# GPU memory (NVML) and host memory (cgroup, /proc, Windows API)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GpuMemory:
    """GPU memory that is visible to this process. ``error`` is set when unknown.

    ``unified`` is True for an integrated GPU that has no memory of its own (GB10 of DGX Spark): then the
    values are the memory that it shares with the host, and ``note`` says how they were found and their limits.
    """

    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    device: str = ""
    mig: bool = False
    source: str = ""
    error: str = ""
    unified: bool = False
    note: str = ""

    @property
    def available(self) -> bool:
        return self.total_bytes is not None


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


def _load_nvml() -> Any:
    if sys.platform == "win32":
        candidates = [
            "nvml.dll",
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvml.dll"),
        ]
    else:
        candidates = ["libnvidia-ml.so.1"]
    errors = []
    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError as exc:
            errors.append(str(exc))
    raise OSError("NVML library not found: " + "; ".join(errors))


def _read_gpu_memory_nvml(index: int) -> GpuMemory:
    """Read memory through NVML. On MIG, read the MIG device handle.

    ``nvmlDeviceGetMemoryInfo`` on the parent device of a MIG partition returns
    NOT_SUPPORTED. The same call on the MIG device handle returns the memory of
    the partition, and needs no extra permission in a container.
    """

    lib = _load_nvml()
    if lib.nvmlInit_v2() != 0:
        raise RuntimeError("nvmlInit failed")
    try:
        handle = ctypes.c_void_p()
        rc = lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle))
        if rc != 0:
            raise RuntimeError(f"nvmlDeviceGetHandleByIndex failed ({rc})")
        name = ctypes.create_string_buffer(96)
        lib.nvmlDeviceGetName(handle, name, 96)
        device = name.value.decode("utf-8", "replace")
        current, pending = ctypes.c_uint(), ctypes.c_uint()
        mig = (
            lib.nvmlDeviceGetMigMode(handle, ctypes.byref(current), ctypes.byref(pending)) == 0
            and current.value == 1
        )
        info = _NvmlMemory()
        if mig:
            count = ctypes.c_uint()
            if lib.nvmlDeviceGetMaxMigDeviceCount(handle, ctypes.byref(count)) != 0:
                raise RuntimeError("nvmlDeviceGetMaxMigDeviceCount failed")
            for slot in range(count.value):
                mig_handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetMigDeviceHandleByIndex(handle, slot, ctypes.byref(mig_handle)) != 0:
                    continue  # this slot is not visible in this container
                if lib.nvmlDeviceGetMemoryInfo(mig_handle, ctypes.byref(info)) == 0:
                    return GpuMemory(
                        info.total, info.used, info.free, device, True, f"nvml:mig_slot_{slot}"
                    )
            raise RuntimeError("no visible MIG device returned memory information")
        if lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(info)) != 0:
            raise RuntimeError("nvmlDeviceGetMemoryInfo failed")
        return GpuMemory(info.total, info.used, info.free, device, False, "nvml")
    finally:
        lib.nvmlShutdown()


def _read_gpu_memory_smi() -> GpuMemory:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
        check=False, capture_output=True, text=True, timeout=5.0,
    )
    line = (result.stdout or "").splitlines()[0] if result.stdout else ""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != 3 or not (parts[1].isdigit() and parts[2].isdigit()):
        raise RuntimeError(f"nvidia-smi gave no memory values: {line or result.stderr.strip()!r}")
    total, used = int(parts[1]) * MIB, int(parts[2]) * MIB
    return GpuMemory(total, used, total - used, parts[0], False, "nvidia-smi")


#: ``CU_DEVICE_ATTRIBUTE_INTEGRATED`` of the CUDA driver API: 1 for a GPU that is integrated with the host memory.
_CU_DEVICE_ATTRIBUTE_INTEGRATED = 18
#: (index, NVML UUID) -> (integrated, CUDA device name). The kind of a device does not change in a process.
_CUDA_DEVICES: dict[tuple[int, str], tuple[bool, str]] = {}


def _load_cuda() -> Any:
    candidates = ["nvcuda.dll"] if sys.platform == "win32" else ["libcuda.so.1"]
    errors = []
    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError as exc:
            errors.append(str(exc))
    raise OSError("CUDA driver library not found: " + "; ".join(errors))


def _nvml_uuid(index: int) -> tuple[str, Optional[int]]:
    """The UUID of the NVML device ``index`` ("" when NVML cannot give it) and the number of NVML devices (None when
    NVML cannot be asked)."""

    try:
        lib = _load_nvml()
    except OSError:
        return "", None
    if lib.nvmlInit_v2() != 0:
        return "", None
    try:
        count = ctypes.c_uint()
        devices = count.value if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) == 0 else None
        handle, uuid = ctypes.c_void_p(), ctypes.create_string_buffer(96)
        if lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) != 0:
            return "", devices
        text = uuid.value.decode("ascii", "replace") if lib.nvmlDeviceGetUUID(handle, uuid, 96) == 0 else ""
        return text, devices
    finally:
        lib.nvmlShutdown()


def _cuda_device(index: int, uuid: str, nvml_devices: Optional[int] = None) -> tuple[bool, str]:
    """Ask the CUDA driver whether the device is integrated with the host memory, and its name.

    The device is the CUDA device with the NVML ``uuid``. Without a UUID, the CUDA order can differ from the NVML
    order (``CUDA_DEVICE_ORDER``, ``CUDA_VISIBLE_DEVICES``), so a device is used only when there is no other one:
    ``index`` 0, one CUDA device, and one NVML device or no answer from NVML (``nvml_devices`` None). Only device
    queries are used: no CUDA context is made.
    """

    key = (index, uuid)
    if key in _CUDA_DEVICES:
        return _CUDA_DEVICES[key]
    lib = _load_cuda()
    rc = lib.cuInit(0)
    if rc != 0:
        raise RuntimeError(f"cuInit failed ({rc})")
    count = ctypes.c_int()
    rc = lib.cuDeviceGetCount(ctypes.byref(count))
    if rc != 0:
        raise RuntimeError(f"cuDeviceGetCount failed ({rc})")
    if not uuid and (index != 0 or count.value != 1 or nvml_devices not in (None, 1)):
        nvml = "no answer" if nvml_devices is None else nvml_devices
        raise RuntimeError(
            f"NVML gives no UUID for GPU {index}, and there is more than one device (CUDA: {count.value}, NVML: "
            f"{nvml}), so the CUDA device of that GPU is not known"
        )
    for ordinal in range(count.value):
        device = ctypes.c_int()
        if lib.cuDeviceGet(ctypes.byref(device), ordinal) != 0:
            continue
        if uuid:
            raw = (ctypes.c_ubyte * 16)()
            if lib.cuDeviceGetUuid(raw, device) != 0:
                continue
            text = bytes(raw).hex()
            if f"gpu-{text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:]}" != uuid.lower():
                continue
        integrated = ctypes.c_int()
        rc = lib.cuDeviceGetAttribute(ctypes.byref(integrated), _CU_DEVICE_ATTRIBUTE_INTEGRATED, device)
        if rc != 0:
            raise RuntimeError(f"cuDeviceGetAttribute(INTEGRATED) failed ({rc})")
        name = ctypes.create_string_buffer(256)
        rc = lib.cuDeviceGetName(name, 256, device)
        # The name is only shown: its failure is reported in its place, and the answer about the device stays.
        label = name.value.decode("utf-8", "replace")
        if rc != 0:
            label = f"CUDA device {ordinal} (cuDeviceGetName failed ({rc}))"
        _CUDA_DEVICES[key] = (integrated.value == 1, label)
        return _CUDA_DEVICES[key]
    raise RuntimeError(f"no CUDA device {uuid or index} among {count.value}")


def _allocatable_host_memory(host: "HostMemory", meminfo: str = "/proc/meminfo") -> tuple[Optional[int], str]:
    """The memory that a GPU that uses the host memory can allocate now, and how it was found.

    NVIDIA's advice for DGX Spark: ``MemAvailable`` plus ``SwapFree`` of ``/proc/meminfo``, because the system can
    move pages to swap; when the system has huge pages, the free huge pages (they are not swapped). A container
    limit also caps it: the limit minus the memory that the container uses. ``/proc/meminfo`` is read only for a
    ``host`` that :func:`read_linux_memory` gave; for the Windows reading, the free memory is its limit minus the
    memory in use. The way follows ``host``, not the system that runs this code.
    """

    free: Optional[int] = None
    basis = ""
    if host.source in _LINUX_HOST_SOURCES:
        try:
            values = _read_meminfo(meminfo)
            if values.get("HugePages_Total"):
                free = values["HugePages_Free"] * values["Hugepagesize"]
                basis = "HugePages_Free x Hugepagesize of /proc/meminfo"
            else:
                free = values["MemAvailable"] + values.get("SwapFree", 0)
                basis = "MemAvailable + SwapFree of /proc/meminfo, as NVIDIA advises for DGX Spark"
        except (OSError, KeyError, ValueError, IndexError) as exc:
            basis = f"/proc/meminfo cannot be read ({type(exc).__name__}: {exc})"
    if host.source != "meminfo" and host.limit_bytes is not None and host.used_bytes is not None:
        room = max(0, host.limit_bytes - host.used_bytes)
        if free is None or room < free:
            limited = f"the {host.source} limit minus the memory in use"
            free, basis = room, f"{limited} (less than {basis})" if basis else limited
    return free, basis


def _read_unified_memory(device: str, missing: str, matched: str) -> GpuMemory:
    """The memory of an integrated GPU: the memory that it shares with the host, with a note on its limits.

    ``missing`` gives why NVML and ``nvidia-smi`` gave no memory, ``matched`` how the CUDA device was found.
    """

    host = read_host_memory()
    if host.limit_bytes is None:
        raise RuntimeError("the host memory is unknown")
    total, total_basis = _shared_memory_total(host)
    free, basis = _allocatable_host_memory(host)
    note = (
        f"'{device}' is an integrated GPU: it has no memory of its own and uses the memory of the host (unified "
        f"memory). NVML and nvidia-smi give no memory for it ({missing}). The CUDA driver says that {matched} is "
        f"integrated. total_bytes is the memory that the GPU shares with the CPU and with all processes "
        f"({total_basis}). free_bytes is the memory that can be allocated now: {basis}. cudaMemGetInfo can "
        "show less. The scene check compares total_bytes with the GPU minimum plus the host minimum, because the GPU "
        "and the host use the same memory. Limits: free_bytes changes at any time with other processes and the file "
        "cache, and no value gives the part of this memory that the renderer uses."
    )
    return GpuMemory(total, host.used_bytes, free, device, False, f"unified:{host.source}", "", True, note)


def _shared_memory_total(host: "HostMemory", meminfo: str = "/proc/meminfo") -> tuple[int, str]:
    """The memory that an integrated GPU shares with the host, and how it was found.

    It is the host limit. A container limit (cgroup) can be set above the memory that the system has, and the GPU
    cannot use more than that, so ``MemTotal`` of ``/proc/meminfo`` caps a cgroup limit. The other readings give the
    memory of the system itself (``MemTotal``, or the physical memory of the Windows reading).
    """

    limit = f"the host limit, {host.source}"
    if host.source not in ("cgroup2", "cgroup1"):
        return host.limit_bytes, limit
    try:
        physical = _read_meminfo(meminfo)["MemTotal"]
    except (OSError, KeyError, ValueError, IndexError) as exc:
        return host.limit_bytes, f"{limit}; MemTotal of /proc/meminfo cannot be read ({type(exc).__name__}: {exc})"
    if physical < host.limit_bytes:
        return physical, (
            f"MemTotal of /proc/meminfo: the {host.source} limit, {host.limit_bytes / GIB:.1f} GiB, is above the "
            "memory of the system"
        )
    return host.limit_bytes, limit


_FALLBACK_REPORTED: set[str] = set()


def read_gpu_memory(index: int = 0) -> GpuMemory:
    """Read GPU memory with NVML, then with ``nvidia-smi``, then as unified memory. Never raise.

    An integrated GPU (GB10 of DGX Spark) has no memory of its own, so NVML and ``nvidia-smi`` give none. When
    both fail and the CUDA driver says that the device is integrated, the memory is the memory that the device
    shares with the host (``unified``). The use of a second way is reported once, with the cause. When every way
    fails, the failures are in ``error``.
    """

    errors: list[str] = []
    for name, reader in (("NVML", lambda: _read_gpu_memory_nvml(index)), ("nvidia-smi", _read_gpu_memory_smi)):
        try:
            memory = reader()
        except Exception as exc:  # noqa: BLE001 - the cause is kept and reported below
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if errors and errors[0] not in _FALLBACK_REPORTED:
            _FALLBACK_REPORTED.add(errors[0])
            LOGGER.warning("GPU memory is read with %s because %s", name, errors[0])
        return memory
    missing = "; ".join(errors)
    try:
        uuid, nvml_devices = _nvml_uuid(index)
        integrated, device = _cuda_device(index, uuid, nvml_devices)
        if integrated:
            matched = f"the device with the NVML UUID {uuid}" if uuid else "the only CUDA device (NVML gives no UUID)"
            memory = _read_unified_memory(device, missing, matched)
            if f"unified:{device}" not in _FALLBACK_REPORTED:
                _FALLBACK_REPORTED.add(f"unified:{device}")
                LOGGER.info("GPU memory: %s", memory.note)
            return memory
        errors.append(f"CUDA: '{device}' is not an integrated GPU")
    except Exception as exc:  # noqa: BLE001 - the cause is kept and reported below
        errors.append(f"unified memory: {type(exc).__name__}: {exc}")
    return GpuMemory(error="; ".join(errors))


@dataclass(frozen=True)
class HostMemory:
    """The memory limit of this container and the memory that it uses and cannot give back.

    ``used_bytes`` leaves out the file cache and the other caches that the kernel reclaims when memory is
    short (``reclaimable_bytes``): a container that read many files holds them in its cache, and that cache
    is not a risk of running out of memory.
    """

    limit_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    source: str = ""
    reclaimable_bytes: Optional[int] = None


def _read_number(path: str) -> Optional[int]:
    try:
        with open(path, encoding="ascii") as handle:
            text = handle.read().strip()
    except OSError:
        return None  # the file is not there on this system: the next source is tried
    return int(text) if text.isdigit() else None


def _read_stat(path: str) -> dict[str, int]:
    """The ``name value`` lines of a cgroup ``memory.stat`` file (empty when it cannot be read)."""

    values: dict[str, int] = {}
    try:
        with open(path, encoding="ascii") as handle:
            for line in handle:
                name, _, value = line.strip().partition(" ")
                if value.isdigit():
                    values[name] = int(value)
    except OSError:
        pass
    return values


def _read_meminfo(path: str) -> dict[str, int]:
    """The values of ``/proc/meminfo``: bytes for the ``kB`` lines, counts for the others (``HugePages_Total``)."""

    values: dict[str, int] = {}
    with open(path, encoding="ascii") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            words = rest.split()
            values[key] = int(words[0]) * (1024 if words[1:] == ["kB"] else 1)
    return values


def _read_host_memory_windows() -> HostMemory:
    class Status(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
            ("avail_ext", ctypes.c_ulonglong),
        ]

    status = Status()
    status.length = ctypes.sizeof(Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        return HostMemory()
    # The available memory counts the standby (file) cache as free.
    return HostMemory(status.total_phys, status.total_phys - status.avail_phys, "GlobalMemoryStatusEx")


#: (limit file, use file, stat file, source, names in the stat file of the memory that the kernel can reclaim).
#: cgroup v2 ``file`` also counts shared memory (tmpfs), which cannot be reclaimed without swap, so the file
#: lists ``active_file`` and ``inactive_file`` are used, not ``file``.
_CGROUPS = (
    ("memory.max", "memory.current", "memory.stat", "cgroup2", ("active_file", "inactive_file", "slab_reclaimable")),
    ("memory/memory.limit_in_bytes", "memory/memory.usage_in_bytes", "memory/memory.stat", "cgroup1",
     ("total_active_file", "total_inactive_file")),
)
#: The sources of a reading of :func:`read_linux_memory`.
_LINUX_HOST_SOURCES = tuple(entry[3] for entry in _CGROUPS) + ("meminfo",)


def read_host_memory() -> HostMemory:
    """Read the memory limit of this host or container and the memory that it cannot give back.

    The Windows API on Windows, else :func:`read_linux_memory`.
    """

    if sys.platform == "win32":
        return _read_host_memory_windows()
    return read_linux_memory()


def read_linux_memory(cgroup_root: str = "/sys/fs/cgroup", meminfo: str = "/proc/meminfo") -> HostMemory:
    """cgroup v2 or v1 first, then ``/proc/meminfo``. The use is the cgroup's use minus its reclaimable caches (file
    cache, reclaimable kernel caches), as ``MemAvailable`` does for ``/proc/meminfo``.
    """

    for limit_name, used_name, stat_name, source, reclaimable_names in _CGROUPS:
        limit = _read_number(os.path.join(cgroup_root, limit_name))
        # A value above 2**60 means "no limit" in cgroup v1.
        if limit is None or limit >= 2**60:
            continue
        current = _read_number(os.path.join(cgroup_root, used_name))
        if current is None:
            return HostMemory(limit, None, source)
        stat = _read_stat(os.path.join(cgroup_root, stat_name))
        reclaimable = sum(stat.get(name, 0) for name in reclaimable_names)
        return HostMemory(limit, max(0, current - reclaimable), source, reclaimable)
    try:
        values = _read_meminfo(meminfo)
        total, available = values["MemTotal"], values["MemAvailable"]
        return HostMemory(total, total - available, "meminfo", available - values.get("MemFree", available))
    except (OSError, KeyError, ValueError, IndexError) as exc:
        LOGGER.warning("host memory is unknown: %s: %s", type(exc).__name__, exc)
        return HostMemory()


_GPU_BEFORE_RENDERER: Optional[GpuMemory] = None
#: The warnings of the newest :func:`check_resources` that say a resource is below the minimum.
_LAST_BLOCKING: list[str] = []


def note_gpu_memory_before_renderer() -> GpuMemory:
    """Read GPU memory just before a renderer is created, and keep it.

    The free memory at that moment is what the renderer can use: other processes (or another
    renderer) hold the rest. :func:`check_resources` compares it with the minimum of the scene.
    """

    global _GPU_BEFORE_RENDERER
    _GPU_BEFORE_RENDERER = read_gpu_memory()
    return _GPU_BEFORE_RENDERER


def gpu_memory_before_renderer() -> Optional[GpuMemory]:
    return _GPU_BEFORE_RENDERER


def _size_text(size: int) -> str:
    if size >= MIB:
        return f"{size / MIB:.0f} MiB"
    return f"{size / 1024:.0f} KiB" if size >= 1024 else f"{size} bytes"


def check_resources(
    scene_bytes: int,
    gpu: Optional[GpuMemory] = None,
    host: Optional[HostMemory] = None,
    gpu_at_start: Optional[GpuMemory] = None,
    empty: bool = False,
) -> list[str]:
    """Return one warning for each resource below the minimum for this scene size.

    When GPU memory cannot be read, a warning says so: the check is not silent.
    ``gpu_at_start`` (default: the reading of :func:`note_gpu_memory_before_renderer`) is the
    memory that was free when the renderer started; it is checked too, because a GPU of the right
    size whose memory other processes use is as small for the scene as a small partition.
    On an integrated GPU (``gpu.unified``) the GPU and the host use the same memory, so that memory is
    compared with the sum of the GPU and host minimums. An ``empty`` scene (no prims) has no materials or
    textures that can render wrong: no minimum of the table applies to it, and nothing is checked.
    With ``OVUI_STRICT_RESOURCE_CHECK=1`` a resource below the minimum raises
    :class:`InsufficientResourcesError`.
    """

    _LAST_BLOCKING.clear()
    if empty:
        return []
    gpu = gpu if gpu is not None else read_gpu_memory()
    host = host if host is not None else read_host_memory()
    gpu_at_start = gpu_at_start if gpu_at_start is not None else _GPU_BEFORE_RENDERER
    minimum = minimum_for_scene(scene_bytes)
    warnings: list[str] = []
    blocking: list[str] = []
    scene_text = f"scene size {_size_text(scene_bytes)}"
    if not gpu.available:
        warnings.append(
            f"GPU memory is unknown ({gpu.error or 'no reader'}); cannot check the minimum of "
            f"{minimum.min_gpu_gib:g} GiB for {scene_text}. Materials can render wrong without an error "
            "when the GPU is too small."
        )
    elif gpu.unified:
        shared = minimum.min_gpu_gib + minimum.min_host_gib
        if gpu.total_bytes < shared * GIB:
            warnings.append(
                f"The integrated GPU '{gpu.device}' shares {gpu.total_bytes / GIB:.1f} GiB of memory with the host, "
                f"below the minimum of {shared:g} GiB for {scene_text}: {minimum.min_gpu_gib:g} GiB for the GPU and "
                f"{minimum.min_host_gib:g} GiB for the host, from the same memory. Use a system with more memory. "
                "Materials and textures can render wrong (fallback material) without an error on this device."
            )
            blocking.append(warnings[-1])
        elif (gpu_at_start is not None and gpu_at_start.free_bytes is not None
              and gpu_at_start.free_bytes < minimum.min_gpu_gib * GIB):
            warnings.append(
                f"When the renderer started, {gpu_at_start.free_bytes / GIB:.1f} GiB of the "
                f"{(gpu_at_start.total_bytes or 0) / GIB:.1f} GiB that the integrated GPU '{gpu_at_start.device}' "
                f"shares with the host could be allocated (other processes used the rest), below the minimum of "
                f"{minimum.min_gpu_gib:g} GiB for {scene_text}. Materials and textures can render wrong (fallback "
                "material) without an error. Stop other processes to free memory."
            )
            blocking.append(warnings[-1])
    elif gpu.total_bytes < minimum.min_gpu_gib * GIB:
        kind = "MIG partition" if gpu.mig else "GPU"
        warnings.append(
            f"The {kind} '{gpu.device}' has {gpu.total_bytes / GIB:.1f} GiB, below the minimum of "
            f"{minimum.min_gpu_gib:g} GiB for {scene_text}. Use a {minimum.advice}. "
            "Materials and textures can render wrong (fallback material) without an error on this device."
        )
        blocking.append(warnings[-1])
    elif (gpu_at_start is not None and gpu_at_start.free_bytes is not None
          and gpu_at_start.free_bytes < minimum.min_gpu_gib * GIB):
        warnings.append(
            f"When the renderer started, {gpu_at_start.free_bytes / GIB:.1f} GiB of the "
            f"{(gpu_at_start.total_bytes or 0) / GIB:.1f} GiB of '{gpu_at_start.device}' were free (other processes "
            f"used the rest), below the minimum of {minimum.min_gpu_gib:g} GiB for {scene_text}. "
            "Materials and textures can render wrong (fallback material) without an error. Free GPU memory or "
            f"use a {minimum.advice}."
        )
        blocking.append(warnings[-1])
    # On an integrated GPU the host minimum is part of the shared check above.
    if not gpu.unified and host.limit_bytes is None:
        warnings.append(f"The host memory limit is unknown; cannot check the minimum of {minimum.min_host_gib:g} GiB for {scene_text}.")
    elif not gpu.unified and host.limit_bytes < minimum.min_host_gib * GIB:
        warnings.append(
            f"The host memory limit is {host.limit_bytes / GIB:.1f} GiB, below the minimum of "
            f"{minimum.min_host_gib:g} GiB for {scene_text}. The first native step can use more "
            "host memory than the limit."
        )
        blocking.append(warnings[-1])
    for text in warnings:
        LOGGER.warning(text)
    _LAST_BLOCKING.extend(blocking)
    if blocking and os.environ.get(STRICT_ENV, "").strip() not in ("", "0"):
        raise InsufficientResourcesError(" ".join(blocking) + f" ({STRICT_ENV}=1 refuses this scene.)")
    return warnings


# --------------------------------------------------------------------------
# Background tasks: each stops at shutdown within a time limit; a task that does not stop is named
# --------------------------------------------------------------------------


class BackgroundTask:
    """A thread that ovui starts for the render diagnostics, with a bounded stop.

    ``step()`` runs every ``interval`` seconds until :meth:`stop`, or once when
    ``interval`` is None. ``final()`` runs once in the thread that calls
    :meth:`stop`, after the task thread has ended, so that the last data is read.
    """

    _registry: "OrderedDict[int, BackgroundTask]" = OrderedDict()
    _registry_lock = threading.Lock()

    def __init__(self, name: str, step: Callable[[], None], interval: Optional[float] = None,
                 final: Optional[Callable[[], None]] = None) -> None:
        self.name = name
        self._step = step
        self._final = final
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> "BackgroundTask":
        with self._registry_lock:
            self._registry[id(self)] = self
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            if self._interval is None:
                self._step()
                self._forget()  # a one-shot task that has ended has nothing left to stop
                return
            while not self._stop.wait(self._interval):
                self._step()
        except Exception:  # noqa: BLE001 - reported, then the task ends
            LOGGER.exception("background task %s failed", self.name)
            self._forget()

    def _forget(self) -> None:
        with self._registry_lock:
            self._registry.pop(id(self), None)

    def finish(self) -> None:
        """End the task from its own thread: the current step is its last one, and it is no longer listed."""

        self._stop.set()
        self._forget()

    def stop(self, timeout: float = STOP_TIMEOUT) -> bool:
        """Stop the task and wait at most ``timeout`` seconds. Returns True when it stopped."""

        self._stop.set()
        self._thread.join(timeout=timeout)
        stopped = not self._thread.is_alive()
        if stopped:
            with self._registry_lock:
                self._registry.pop(id(self), None)
            if self._final is not None:
                self._final()
        else:
            LOGGER.error("background task %s did not stop in %.1f s", self.name, timeout)
        return stopped

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    @classmethod
    def running(cls) -> list["BackgroundTask"]:
        with cls._registry_lock:
            return list(cls._registry.values())


class WeakOwners:
    """The owners of a process-wide resource, held by weak reference.

    An owner that is freed without giving its share back (an adapter that its caller dropped without shutting it
    down, or whose construction failed) does not keep the resource: only owners that are still alive count. The
    caller holds its own lock around each call.
    """

    def __init__(self) -> None:
        self._refs: dict[int, Callable[[], Any]] = {}

    def add(self, owner: Any) -> None:
        try:
            ref: Callable[[], Any] = weakref.ref(owner)
        except TypeError:  # an object without weak references is held until it gives its share back
            ref = lambda kept=owner: kept  # noqa: E731
        self._refs[id(owner)] = ref

    def discard(self, owner: Any) -> None:
        ref = self._refs.get(id(owner))
        if ref is not None and ref() is owner:
            del self._refs[id(owner)]

    def __len__(self) -> int:
        self._refs = {key: ref for key, ref in self._refs.items() if ref() is not None}
        return len(self._refs)


def shutdown_background_tasks(timeout: float = STOP_TIMEOUT) -> list[str]:
    """Stop every background task of the render diagnostics. Returns the names of tasks that did not stop."""

    stuck = []
    for task in BackgroundTask.running():
        if not task.stop(timeout):
            stuck.append(task.name)
    return stuck


def raise_if_stuck(names: list[str]) -> None:
    """Raise :class:`BackgroundTaskStuckError` for the tasks that did not stop, so that the application exit fails."""

    if names:
        raise BackgroundTaskStuckError(
            "background tasks did not stop in their time limit: " + ", ".join(names)
        )


class HostMemoryWatch:
    """Warn once when host memory use crosses a fraction of the limit.

    Use it around a step that can grow without bound, such as the first native
    step of a large scene. The watch only reads memory; it never stops the work.
    """

    def __init__(self, label: str, fraction: float = 0.8, interval: float = 1.0,
                 diagnostics: Optional["RenderDiagnostics"] = None) -> None:
        self._label, self._fraction = label, fraction
        self._diagnostics = diagnostics
        self._fired = False
        self._task = BackgroundTask("ovui-host-memory-watch", self._check, interval)

    def __enter__(self) -> "HostMemoryWatch":
        self._task.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._task.stop()

    def _check(self) -> None:
        if self._fired:
            return
        host = read_host_memory()
        if host.limit_bytes and host.used_bytes and host.used_bytes >= self._fraction * host.limit_bytes:
            self._fired = True
            cache = f" (not counting {host.reclaimable_bytes / GIB:.1f} GiB of reclaimable cache)" if host.reclaimable_bytes else ""
            message = (
                f"Host memory in use is {host.used_bytes / GIB:.1f} of {host.limit_bytes / GIB:.1f} GiB{cache} "
                f"during {self._label}. Lower the texture streaming budget or use a larger host limit."
            )
            (self._diagnostics or get_render_diagnostics()).record(SCENE, "", "memory", message)


# --------------------------------------------------------------------------
# Failure events
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderEvent:
    """One failure that the renderer showed. ``scope`` says how well it is tied to the scene.

    * ``material``: a material or shader prim path is named.
    * ``resource``: a file (texture, MDL module) is named but no prim. The material
      report links such an event to each material that uses the file.
    * ``scene``: nothing is named (for example an out-of-memory error). The event is
      not tied to a material, and ``context`` may hold the last material path that the
      renderer log named before it. ``context`` is a hint, not an attribution.
    """

    material: str
    resource: str
    kind: str  # compile | select | texture | mdl | memory | step | mismatch
    message: str
    scope: str = "scene"
    context: str = ""
    time: float = field(default_factory=time.time)


class RenderDiagnostics:
    """Thread-safe, bounded list of the render failure events of the open scene."""

    def __init__(self, limit: int = 1000) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        #: Each event with its number; the numbers grow in the order of recording.
        self._events: "OrderedDict[tuple[str, str, str], tuple[int, RenderEvent]]" = OrderedDict()
        self._count = 0
        #: Events with a lower number belong to a scene that another scene replaces (see :meth:`begin_scene`).
        self._scene_start = 0
        #: Renderer lines that are a failure only when the files of the scene do not explain them
        #: (``render_native_log.note_body_resource``): (resource, message), held until the files are known.
        self._held: list[tuple[str, str]] = []
        #: The texture and MDL files of the scene (``render_material_report.shader_files``), once they are known.
        self._scene_files: Optional[list[dict[str, Any]]] = None

    def record(self, material: str, resource: str, kind: str, message: str,
               context: str = "") -> Optional[RenderEvent]:
        """Store one event and log a warning that names the material and resource.

        The same (material, resource, kind) is stored once for a scene. When the list is full the
        oldest ``unverified`` event is dropped (a material that could not be checked), and only when
        there is none the oldest event, so that a failure is not pushed out by unchecked materials;
        memory use does not grow.
        """

        key = (material, resource, kind)
        scope = "material" if material != SCENE else ("resource" if resource else "scene")
        with self._lock:
            held = self._events.get(key)
            if held is not None:
                if held[0] >= self._scene_start:
                    return None
                del self._events[key]  # the same failure in the scene that replaces the old one
            event = RenderEvent(material, resource, kind, message, scope, context)
            self._count += 1
            self._events[key] = (self._count, event)
            while len(self._events) > self._limit:
                drop = next((k for k, (_n, e) in self._events.items() if e.kind == "unverified"), None)
                if drop is None:
                    self._events.popitem(last=False)
                else:
                    del self._events[drop]
        LOGGER.warning(
            "material %s resource %s (%s): %s%s", material, resource or "-", kind, message,
            f" [last material in the renderer log: {context}]" if context else "",
        )
        return event

    def begin_scene(self) -> int:
        """Another scene is being loaded: the events recorded from now on belong to it.

        Returns the mark to give to :meth:`retire_before` when the new scene is loaded. The events of the
        old scene are kept until then, so that a load that fails does not lose them.
        """

        with self._lock:
            self._scene_start = self._count + 1
            self._scene_files = None
            return self._scene_start

    def hold_until_files(self, resource: str, message: str) -> Optional[list[dict[str, Any]]]:
        """Return the files of the scene when they are known; else hold ``(resource, message)`` and return None."""

        with self._lock:
            if self._scene_files is None:
                self._held.append((resource, message))
                return None
            return self._scene_files

    def set_scene_files(self, files: Optional[list[dict[str, Any]]]) -> list[tuple[str, str]]:
        """Store the files of the scene; None when they cannot be read (then no line is explained by them).

        Returns the held lines, for the caller to decide with the files.
        """

        with self._lock:
            self._scene_files = list(files) if files is not None else []
            held, self._held = self._held, []
            return held

    def retire_before(self, mark: int) -> int:
        """The new scene is loaded: drop the events of the scenes before ``mark``. Returns how many were dropped."""

        with self._lock:
            old = [key for key, (number, _event) in self._events.items() if number < mark]
            for key in old:
                del self._events[key]
            return len(old)

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(event) for _number, event in self._events.values()]

    def version(self) -> int:
        """A number that grows with each new event (cheap to read at every frame)."""

        with self._lock:
            return self._count

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_DIAGNOSTICS = RenderDiagnostics()


def get_render_diagnostics() -> RenderDiagnostics:
    return _DIAGNOSTICS


# --------------------------------------------------------------------------
# Scene size and the open-time resource report
# --------------------------------------------------------------------------


def scene_layer_bytes(stage: Any) -> int:
    """Return the summed file size of every layer file the stage composes."""

    total = 0
    for layer in stage.GetUsedLayers():
        real_path = getattr(layer, "realPath", "") or ""
        if real_path and os.path.isfile(real_path):
            total += os.path.getsize(real_path)
    return total


_RESOURCE_REPORT: dict[str, Any] = {"checked": False, "warnings": []}


def last_resource_report() -> dict[str, Any]:
    """Return the newest scene resource check (see :func:`check_scene_resources`)."""

    return dict(_RESOURCE_REPORT)


def check_scene_resources(scene_bytes: int, basis: str, empty: bool = False) -> list[str]:
    """Check GPU and host memory for a scene of ``scene_bytes``, keep and return the warnings.

    An ``empty`` scene (no prims) gets no minimum and no warning (see :func:`check_resources`); the report says
    so. A failure of the check itself is logged and kept in the report. Only
    :class:`InsufficientResourcesError` (strict mode) is raised.
    """

    global _RESOURCE_REPORT
    try:
        gpu, host, at_start = read_gpu_memory(), read_host_memory(), _GPU_BEFORE_RENDERER
        _RESOURCE_REPORT = {
            "checked": True, "scene_bytes": scene_bytes, "scene_size_basis": basis, "scene_empty": empty,
            "gpu": {**vars(gpu), "available": gpu.available}, "host": vars(host),
            "gpu_free_when_renderer_started": vars(at_start) if at_start is not None else None,
            "minimum": None if empty else vars(minimum_for_scene(scene_bytes)), "warnings": [], "below_minimum": [],
        }
        if empty:
            _RESOURCE_REPORT["note"] = (
                "The scene has no prims, so no minimum of the scene-size table applies. The check runs again when "
                "a scene with prims is loaded."
            )
        try:
            warnings = check_resources(scene_bytes, gpu, host, at_start, empty)
        except InsufficientResourcesError as exc:
            below = list(_LAST_BLOCKING)
            _RESOURCE_REPORT.update(warnings=below, below_minimum=below, refused=str(exc))
            raise
        _RESOURCE_REPORT.update(warnings=warnings, below_minimum=list(_LAST_BLOCKING))
        return warnings
    except InsufficientResourcesError:
        raise
    except Exception as exc:  # noqa: BLE001 - kept in the report and logged
        LOGGER.error("resource check failed: %s: %s", type(exc).__name__, exc)
        _RESOURCE_REPORT = {"checked": False, "warnings": [], "error": f"{type(exc).__name__}: {exc}"}
        return []


def scene_has_prims(stage: Any, own_roots: tuple[str, ...] = ()) -> bool:
    """Return whether a layer that a pxr stage composes has a prim, other than the application's own prims.

    ``own_roots`` are the paths of the root prims that the application authors itself (the viewport camera,
    render product and fallback light under ``/OvGearSession``). Every other prim counts, also a prim in a session
    layer or its sublayers: live scene content can be there.
    """

    return any(
        str(spec.path) not in own_roots for layer in stage.GetUsedLayers() for spec in layer.rootPrims
    )


def check_stage_resources(stage: Any, own_roots: tuple[str, ...] = ()) -> list[str]:
    """Run :func:`check_scene_resources` with the composed layer size of a pxr stage.

    The scene is empty when :func:`scene_has_prims` finds no prim outside ``own_roots``.
    """

    try:
        scene_bytes, basis = scene_layer_bytes(stage), "composed layers"
        empty = not scene_has_prims(stage, own_roots)
    except Exception as exc:  # noqa: BLE001 - the size is then unknown; reported
        LOGGER.error("scene size is unknown (%s: %s)", type(exc).__name__, exc)
        scene_bytes, basis, empty = 0, f"unknown ({type(exc).__name__})", False
    return check_scene_resources(scene_bytes, basis, empty)


# --------------------------------------------------------------------------
# Result of the last render check (see render_probe)
# --------------------------------------------------------------------------

_VERIFICATION: dict[str, dict[str, Any]] = {}
_VERIFICATION_LOCK = threading.Lock()


def set_verification(results: dict[str, dict[str, Any]]) -> None:
    """Keep the per-material result of the newest render check."""

    with _VERIFICATION_LOCK:
        _VERIFICATION.clear()
        _VERIFICATION.update(results)


def get_verification() -> dict[str, dict[str, Any]]:
    with _VERIFICATION_LOCK:
        return dict(_VERIFICATION)
