# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render diagnostics: events, memory checks, background tasks and shutdown."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import pytest

from ovui_data_adapters.common import render_diagnostics as rd
from ovui_data_adapters.common import render_native_log as nl


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    monkeypatch.setattr(rd, "_VERIFICATION", {})
    monkeypatch.setattr(rd, "_RESOURCE_REPORT", {"checked": False, "warnings": []})
    monkeypatch.setattr(rd, "_GPU_BEFORE_RENDERER", None)
    monkeypatch.setattr(nl, "_GENERATED_DIRS", [])
    yield
    assert rd.shutdown_background_tasks(5.0) == []


def _wait(condition, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_a_full_event_list_drops_unchecked_materials_before_failures():
    diagnostics = rd.RenderDiagnostics(limit=3)
    diagnostics.record("/W/A", "", "unverified", "not checked: no albedo input")
    diagnostics.record("/W/Floor", "./floor.png", "texture", "Couldn't process file")
    diagnostics.record("/W/B", "", "unverified", "not checked: no geometry")
    diagnostics.record("/W/Grid", "./grid.mdl", "mdl", "C100")
    diagnostics.record("/W/Fence", "./fence.png", "texture", "texture unresolved")
    kept = [(e["material"], e["kind"]) for e in diagnostics.events()]
    assert kept == [("/W/Floor", "texture"), ("/W/Grid", "mdl"), ("/W/Fence", "texture")]
    diagnostics.record("/W/Other", "./o.png", "texture", "failed")  # no unchecked one left: the oldest goes
    assert [e["material"] for e in diagnostics.events()] == ["/W/Grid", "/W/Fence", "/W/Other"]


# -- minimum memory --------------------------------------------------------------------


def test_minimum_by_scene_size_and_startup_warning(monkeypatch, caplog):
    monkeypatch.delenv(rd.MIN_GPU_MEMORY_ENV, raising=False)
    assert rd.minimum_for_scene(800 * rd.MIB).min_gpu_gib == 44.0
    assert rd.minimum_for_scene(50 * rd.MIB).min_gpu_gib == 14.0
    small = rd.GpuMemory(int(23.0 * rd.GIB), 0, int(23.0 * rd.GIB), "RTX PRO 6000", True, "nvml")
    big = rd.GpuMemory(int(47.4 * rd.GIB), 0, int(47.4 * rd.GIB), "RTX PRO 6000", True, "nvml")
    host64 = rd.HostMemory(64 * rd.GIB, 0, "cgroup2")
    host128 = rd.HostMemory(128 * rd.GIB, 0, "cgroup2")
    kitchen = 800 * rd.MIB
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        warnings_1g = rd.check_resources(kitchen, small, host64)
    assert len(warnings_1g) == 2 and "MIG partition" in warnings_1g[0] and "2g.48gb" in warnings_1g[0]
    assert "host memory limit" in warnings_1g[1]
    assert "MIG partition" in caplog.text
    assert rd.check_resources(kitchen, big, host128) == []


def test_unknown_memory_is_not_silent():
    warnings = rd.check_resources(800 * rd.MIB, rd.GpuMemory(error="no reader"), rd.HostMemory())
    assert "GPU memory is unknown (no reader)" in warnings[0]
    assert "host memory limit is unknown" in warnings[1]


def test_minimum_override(monkeypatch):
    monkeypatch.setenv(rd.MIN_GPU_MEMORY_ENV, "10")
    minimum = rd.minimum_for_scene(800 * rd.MIB)
    assert minimum.min_gpu_gib == 10.0 and "at least 10 GiB" in minimum.advice


def test_strict_mode_refuses_a_device_below_the_minimum(monkeypatch):
    small = rd.GpuMemory(int(23.0 * rd.GIB), 0, int(23.0 * rd.GIB), "RTX PRO 6000", True, "nvml")
    host = rd.HostMemory(128 * rd.GIB, 0, "cgroup2")
    monkeypatch.delenv(rd.STRICT_ENV, raising=False)
    assert rd.check_resources(800 * rd.MIB, small, host)  # default: warns, does not raise
    monkeypatch.setenv(rd.STRICT_ENV, "1")
    with pytest.raises(rd.InsufficientResourcesError, match="2g.48gb"):
        rd.check_resources(800 * rd.MIB, small, host)
    assert rd.check_resources(800 * rd.MIB, rd.GpuMemory(error="no reader"), host)  # unknown: warning only


def test_free_gpu_memory_when_the_renderer_started_is_checked(monkeypatch):
    """A GPU of the right size whose memory other processes use is too small for the scene: warn (strict: refuse)."""

    monkeypatch.delenv(rd.STRICT_ENV, raising=False)
    monkeypatch.delenv(rd.MIN_GPU_MEMORY_ENV, raising=False)
    device = rd.GpuMemory(int(47.4 * rd.GIB), int(44.0 * rd.GIB), int(3.4 * rd.GIB), "RTX PRO 6000", True, "nvml")
    roomy = rd.GpuMemory(int(47.4 * rd.GIB), int(2.0 * rd.GIB), int(45.4 * rd.GIB), "RTX PRO 6000", True, "nvml")
    host = rd.HostMemory(128 * rd.GIB, 0, "cgroup2")
    factory = 404 * rd.MIB  # minimum 20 GiB
    (warning,) = rd.check_resources(factory, device, host, device)
    assert "When the renderer started, 3.4 GiB of the 47.4 GiB" in warning and "minimum of 20 GiB" in warning
    assert rd.check_resources(factory, device, host, roomy) == []
    assert rd.check_resources(factory, device, host, rd.GpuMemory(error="no reader")) == []  # not known: no claim
    monkeypatch.setenv(rd.STRICT_ENV, "1")
    with pytest.raises(rd.InsufficientResourcesError, match="other processes"):
        rd.check_resources(factory, device, host, device)


def test_the_reading_before_the_renderer_is_kept_for_the_scene_check(monkeypatch):
    """The adapters read GPU memory just before they create the renderer; the scene check uses that reading."""

    monkeypatch.delenv(rd.STRICT_ENV, raising=False)
    monkeypatch.delenv(rd.MIN_GPU_MEMORY_ENV, raising=False)
    before = rd.GpuMemory(int(47.4 * rd.GIB), int(44.0 * rd.GIB), int(3.4 * rd.GIB), "RTX PRO 6000", True, "nvml")
    monkeypatch.setattr(rd, "read_gpu_memory", lambda index=0: before)
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.HostMemory(128 * rd.GIB, 0, "cgroup2"))
    assert rd.note_gpu_memory_before_renderer() is before and rd.gpu_memory_before_renderer() is before
    warnings = rd.check_scene_resources(404 * rd.MIB, "composed layers")
    report = rd.last_resource_report()
    assert report["below_minimum"] == warnings and len(warnings) == 1
    assert report["gpu_free_when_renderer_started"]["free_bytes"] == before.free_bytes
    monkeypatch.setenv(rd.STRICT_ENV, "1")
    with pytest.raises(rd.InsufficientResourcesError):
        rd.check_scene_resources(404 * rd.MIB, "composed layers")
    report = rd.last_resource_report()
    assert report["below_minimum"] == report["warnings"] and "refuses this scene" in report["refused"]


def test_gpu_memory_fallback_is_reported_once(monkeypatch, caplog):
    def broken(index):
        raise OSError("no NVML here")

    smi = rd.GpuMemory(10 * rd.GIB, 0, 10 * rd.GIB, "GPU", False, "nvidia-smi")
    monkeypatch.setattr(rd, "_read_gpu_memory_nvml", broken)
    monkeypatch.setattr(rd, "_read_gpu_memory_smi", lambda: smi)
    monkeypatch.setattr(rd, "_FALLBACK_REPORTED", set())
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        assert rd.read_gpu_memory() == smi
        assert rd.read_gpu_memory() == smi
    assert caplog.text.count("GPU memory is read with nvidia-smi") == 1 and "no NVML here" in caplog.text


def test_read_gpu_memory_never_raises():
    memory = rd.read_gpu_memory(index=99)
    assert memory.available or memory.error


def _no_dedicated_memory(monkeypatch, integrated: bool):
    """NVML and nvidia-smi give no memory, as on GB10 (DGX Spark); CUDA says whether the device is integrated."""

    def nvml(index):
        raise RuntimeError("nvmlDeviceGetMemoryInfo failed")

    def smi():
        raise RuntimeError("nvidia-smi gave no memory values: 'NVIDIA GB10, [N/A], [N/A]'")

    monkeypatch.setattr(rd, "_read_gpu_memory_nvml", nvml)
    monkeypatch.setattr(rd, "_read_gpu_memory_smi", smi)
    monkeypatch.setattr(rd, "_nvml_uuid", lambda index: ("GPU-1", 1))
    monkeypatch.setattr(
        rd, "_cuda_device", lambda index, uuid, nvml_devices=None: (integrated, "NVIDIA GB10" if integrated else "RTX")
    )
    monkeypatch.setattr(rd, "_FALLBACK_REPORTED", set())


def test_an_integrated_gpu_uses_the_memory_that_it_shares_with_the_host(monkeypatch, tmp_path, caplog):
    """GB10: no dedicated memory; the shared memory and NVIDIA's allocatable estimate are used, and explained."""

    _no_dedicated_memory(monkeypatch, integrated=True)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 127597588 kB\nMemAvailable: 104857600 kB\nSwapFree: 16777216 kB\n"
                       "HugePages_Total: 0\nHugepagesize: 2048 kB\n")
    # A Linux reading on purpose: the way follows the reading, not the system that runs the test (also Windows).
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.read_linux_memory(str(tmp_path / "no-cgroup"), str(meminfo)))
    monkeypatch.setattr(rd, "_read_meminfo", lambda path, real=rd._read_meminfo: real(str(meminfo)))
    with caplog.at_level(logging.INFO, logger="ovui.render_diagnostics"):
        memory = rd.read_gpu_memory()
        assert rd.read_gpu_memory() == memory
    assert memory.available and memory.unified and not memory.error and memory.device == "NVIDIA GB10"
    assert memory.total_bytes == 127597588 * 1024 and memory.free_bytes == (104857600 + 16777216) * 1024
    assert memory.source == "unified:meminfo" and "MemAvailable + SwapFree" in memory.note
    assert "nvmlDeviceGetMemoryInfo failed" in memory.note and "the device with the NVML UUID GPU-1" in memory.note
    assert caplog.text.count("is an integrated GPU") == 1  # reported once, as information


def test_huge_pages_and_a_container_limit_cap_the_shared_memory_that_can_be_allocated(tmp_path):
    # Linux readings ("meminfo", "cgroup2") on purpose: /proc/meminfo is read for them on every system.
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 104857600 kB\nSwapFree: 0 kB\nHugePages_Total: 1024\nHugePages_Free: 512\n"
                       "Hugepagesize: 2048 kB\n")
    free, basis = rd._allocatable_host_memory(rd.HostMemory(128 * rd.GIB, 8 * rd.GIB, "meminfo"), str(meminfo))
    assert free == 512 * 2048 * 1024 and "HugePages_Free" in basis
    meminfo.write_text("MemAvailable: 104857600 kB\nSwapFree: 0 kB\nHugePages_Total: 0\n")
    free, basis = rd._allocatable_host_memory(rd.HostMemory(64 * rd.GIB, 60 * rd.GIB, "cgroup2"), str(meminfo))
    assert free == 4 * rd.GIB and "cgroup2 limit" in basis


def test_an_integrated_gpu_on_windows_shares_the_memory_of_the_windows_reading(monkeypatch, tmp_path):
    """The Windows reading (GlobalMemoryStatusEx) gives the shared memory and the free memory; /proc/meminfo is
    not used for it, on any system, and the scene check uses that budget."""

    monkeypatch.delenv(rd.STRICT_ENV, raising=False)
    monkeypatch.delenv(rd.MIN_GPU_MEMORY_ENV, raising=False)
    _no_dedicated_memory(monkeypatch, integrated=True)
    meminfo = tmp_path / "meminfo"  # Linux values that must not count for the Windows reading
    meminfo.write_text("MemTotal: 33554432 kB\nMemAvailable: 8388608 kB\nSwapFree: 0 kB\nHugePages_Total: 0\n")
    monkeypatch.setattr(rd, "_read_meminfo", lambda path, real=rd._read_meminfo: real(str(meminfo)))
    windows = rd.HostMemory(64 * rd.GIB, 40 * rd.GIB, "GlobalMemoryStatusEx")
    monkeypatch.setattr(rd, "read_host_memory", lambda: windows)
    memory = rd.read_gpu_memory()
    assert memory.unified and not memory.error and memory.source == "unified:GlobalMemoryStatusEx"
    assert memory.total_bytes == 64 * rd.GIB and memory.free_bytes == 24 * rd.GIB
    assert "(the host limit, GlobalMemoryStatusEx)" in memory.note and "meminfo" not in memory.note
    assert rd.check_resources(10 * 1024, memory, windows, memory) == []  # 14 + 16 GiB; 24 GiB free
    (warning,) = rd.check_resources(800 * rd.MIB, memory, windows, memory)  # 44 + 96 GiB
    assert "shares 64.0 GiB of memory with the host, below the minimum of 140 GiB" in warning


def test_a_container_limit_above_the_memory_of_the_system_is_capped_by_memtotal(monkeypatch, tmp_path):
    """The GPU cannot use more memory than the system has, also when a cgroup limit allows more."""

    _no_dedicated_memory(monkeypatch, integrated=True)
    cgroup, meminfo = tmp_path / "cgroup", tmp_path / "meminfo"
    cgroup.mkdir()
    (cgroup / "memory.current").write_text(f"{8 * rd.GIB}\n")
    (cgroup / "memory.stat").write_text("active_file 0\ninactive_file 0\nslab_reclaimable 0\n")
    meminfo.write_text("MemTotal: 134217728 kB\nMemAvailable: 125829120 kB\nSwapFree: 0 kB\nHugePages_Total: 0\n")
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.read_linux_memory(str(cgroup), str(meminfo)))
    monkeypatch.setattr(rd, "_read_meminfo", lambda path, real=rd._read_meminfo: real(str(meminfo)))
    (cgroup / "memory.max").write_text(f"{256 * rd.GIB}\n")
    memory = rd.read_gpu_memory()
    assert memory.source == "unified:cgroup2" and memory.total_bytes == 128 * rd.GIB
    assert "MemTotal of /proc/meminfo: the cgroup2 limit, 256.0 GiB, is above the memory of the system" in memory.note
    assert memory.free_bytes == 120 * rd.GIB  # MemAvailable + SwapFree, below the limit minus the use
    (cgroup / "memory.max").write_text(f"{64 * rd.GIB}\n")
    memory = rd.read_gpu_memory()
    assert memory.total_bytes == 64 * rd.GIB and "(the host limit, cgroup2)" in memory.note
    assert memory.free_bytes == 56 * rd.GIB


GB10_UUID, RTX_UUID = "a1b2c3d4e5f60718293a4b5c6d7e8f90", "0123456789abcdef0123456789abcdef"


def _nvml_uuid_text(raw: str) -> str:
    return f"GPU-{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


class _FakeCudaDriver:
    """The CUDA driver calls of the GPU memory reading, answered for a list of (UUID, integrated, name) devices."""

    def __init__(self, devices, name_rc=0):
        self.devices, self.name_rc = devices, name_rc

    def cuInit(self, flags):
        return 0

    def cuDeviceGetCount(self, count):
        count._obj.value = len(self.devices)
        return 0

    def cuDeviceGet(self, device, ordinal):
        device._obj.value = ordinal
        return 0

    def cuDeviceGetUuid(self, raw, device):
        raw[:] = list(bytes.fromhex(self.devices[device.value][0]))
        return 0

    def cuDeviceGetAttribute(self, value, attribute, device):
        value._obj.value = int(self.devices[device.value][1]) if attribute == rd._CU_DEVICE_ATTRIBUTE_INTEGRATED else -1
        return 0

    def cuDeviceGetName(self, name, size, device):
        name.value = self.devices[device.value][2].encode()
        return self.name_rc


def test_the_cuda_device_is_found_by_the_nvml_uuid_when_the_cuda_order_differs(monkeypatch):
    monkeypatch.setattr(rd, "_CUDA_DEVICES", {})
    driver = _FakeCudaDriver([(RTX_UUID, False, "NVIDIA RTX"), (GB10_UUID, True, "NVIDIA GB10")])
    monkeypatch.setattr(rd, "_load_cuda", lambda: driver)
    assert rd._cuda_device(0, _nvml_uuid_text(GB10_UUID), 2) == (True, "NVIDIA GB10")
    assert rd._cuda_device(1, _nvml_uuid_text(RTX_UUID), 2) == (False, "NVIDIA RTX")
    with pytest.raises(RuntimeError, match="no CUDA device GPU-ffffffff"):
        rd._cuda_device(0, _nvml_uuid_text("f" * 32), 2)


def test_without_an_nvml_uuid_a_cuda_device_is_used_only_when_there_is_no_other(monkeypatch):
    real_cuda_device = rd._cuda_device
    _no_dedicated_memory(monkeypatch, integrated=True)
    monkeypatch.setattr(rd, "_cuda_device", real_cuda_device)
    monkeypatch.setattr(rd, "_CUDA_DEVICES", {})
    monkeypatch.setattr(rd, "_nvml_uuid", lambda index: ("", None))
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.HostMemory(64 * rd.GIB, 40 * rd.GIB, "GlobalMemoryStatusEx"))
    two = _FakeCudaDriver([(RTX_UUID, False, "NVIDIA RTX"), (GB10_UUID, True, "NVIDIA GB10")])
    monkeypatch.setattr(rd, "_load_cuda", lambda: two)
    memory = rd.read_gpu_memory()  # the CUDA order need not be the NVML order: no guess
    assert not memory.available and "the CUDA device of that GPU is not known" in memory.error
    assert "CUDA: 2, NVML: no answer" in memory.error
    one = _FakeCudaDriver([(GB10_UUID, True, "NVIDIA GB10")])
    monkeypatch.setattr(rd, "_load_cuda", lambda: one)
    with pytest.raises(RuntimeError, match="CUDA: 1, NVML: 2"):
        rd._cuda_device(0, "", 2)  # NVML has a second GPU that CUDA_VISIBLE_DEVICES can hide
    memory = rd.read_gpu_memory()
    assert memory.unified and "the only CUDA device (NVML gives no UUID)" in memory.note


def test_a_failed_device_name_query_is_reported_and_keeps_the_answer_about_the_device(monkeypatch):
    monkeypatch.setattr(rd, "_CUDA_DEVICES", {})
    monkeypatch.setattr(rd, "_load_cuda", lambda: _FakeCudaDriver([(GB10_UUID, True, "NVIDIA GB10")], name_rc=999))
    assert rd._cuda_device(0, _nvml_uuid_text(GB10_UUID), 1) == (True, "CUDA device 0 (cuDeviceGetName failed (999))")


def test_the_real_driver_finds_the_cuda_device_of_the_nvml_gpu(monkeypatch):
    """No fake: the NVIDIA driver of this computer. The CUDA device with the NVML UUID is found, and CUDA calls it
    integrated exactly when NVML gives it no memory of its own. Skips only without an NVIDIA driver or GPU."""

    try:
        rd._load_nvml()
        rd._load_cuda()
    except OSError as exc:
        pytest.skip(f"no NVIDIA driver on this computer: {exc}")
    uuid, devices = rd._nvml_uuid(0)
    if not devices:
        pytest.skip("the NVIDIA driver lists no GPU")
    monkeypatch.setattr(rd, "_CUDA_DEVICES", {})
    assert uuid.startswith("GPU-"), uuid
    integrated, name = rd._cuda_device(0, uuid, devices)
    try:
        rd._read_gpu_memory_nvml(0)
        own_memory = True
    except RuntimeError:
        own_memory = False
    assert name and "cuDeviceGetName failed" not in name
    assert integrated is not own_memory, (name, integrated, own_memory)


def test_a_discrete_gpu_without_memory_telemetry_stays_unknown_and_says_why(monkeypatch):
    _no_dedicated_memory(monkeypatch, integrated=False)
    memory = rd.read_gpu_memory()
    assert not memory.available and not memory.unified
    assert "nvmlDeviceGetMemoryInfo failed" in memory.error and "'RTX' is not an integrated GPU" in memory.error
    (warning, _host) = rd.check_resources(50 * rd.MIB, memory, rd.HostMemory())
    assert warning.startswith("GPU memory is unknown") and "minimum of 14 GiB for scene size 50 MiB" in warning


def test_shared_memory_is_checked_against_the_gpu_and_the_host_minimum_together(monkeypatch):
    monkeypatch.delenv(rd.STRICT_ENV, raising=False)
    monkeypatch.delenv(rd.MIN_GPU_MEMORY_ENV, raising=False)
    spark = rd.GpuMemory(int(121.7 * rd.GIB), int(9 * rd.GIB), int(112 * rd.GIB), "NVIDIA GB10", unified=True)
    host = rd.HostMemory(int(121.7 * rd.GIB), int(9 * rd.GIB), "meminfo")
    assert rd.check_resources(10 * 1024, spark, host, spark) == []
    assert rd.check_resources(404 * rd.MIB, spark, host, spark) == []  # 20 + 48 GiB
    (warning,) = rd.check_resources(800 * rd.MIB, spark, host, spark)  # 44 + 96 GiB from one memory
    assert "shares 121.7 GiB of memory with the host, below the minimum of 140 GiB" in warning
    busy = rd.GpuMemory(int(121.7 * rd.GIB), int(110 * rd.GIB), int(11 * rd.GIB), "NVIDIA GB10", unified=True)
    (warning,) = rd.check_resources(404 * rd.MIB, spark, host, busy)
    assert "11.0 GiB of the 121.7 GiB that the integrated GPU 'NVIDIA GB10' shares with the host" in warning
    monkeypatch.setenv(rd.STRICT_ENV, "1")
    with pytest.raises(rd.InsufficientResourcesError, match="140 GiB"):
        rd.check_resources(800 * rd.MIB, spark, host, spark)


def test_an_empty_scene_gets_no_minimum_and_a_scene_with_prims_does(monkeypatch):
    unknown = rd.GpuMemory(error="NVML: no reader")
    monkeypatch.setattr(rd, "read_gpu_memory", lambda index=0: unknown)
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.HostMemory(128 * rd.GIB, 0, "cgroup2"))
    assert rd.check_scene_resources(10, "composed layers", empty=True) == []
    report = rd.last_resource_report()
    assert report["scene_empty"] is True and report["minimum"] is None and "no prims" in report["note"]
    (warning,) = rd.check_scene_resources(10 * 1024, "composed layers")
    assert "minimum of 14 GiB for scene size 10 KiB" in warning
    assert rd.last_resource_report()["minimum"]["min_gpu_gib"] == 14.0


# -- events ----------------------------------------------------------------------------


def test_events_are_bounded_and_have_a_scope():
    diagnostics = rd.RenderDiagnostics(limit=5)
    for index in range(12):
        diagnostics.record(f"/M{index}", "", "texture", "x")
    events = diagnostics.events()
    assert [e["material"] for e in events] == [f"/M{i}" for i in range(7, 12)]  # the list does not grow
    assert diagnostics.record("/M11", "", "texture", "again") is None  # same key is stored once
    assert diagnostics.record(rd.SCENE, "/a/b.png", "texture", "x").scope == "resource"
    assert diagnostics.record(rd.SCENE, "", "memory", "x").scope == "scene"
    assert diagnostics.record("/M99", "/a/b.png", "texture", "x").scope == "material"


def test_event_warning_names_material_resource_and_context(caplog):
    diagnostics = rd.RenderDiagnostics()
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        diagnostics.record("/World/Looks/red", "./red.png", "texture", "not found")
        diagnostics.record(rd.SCENE, "", "memory", "out of memory", context="/World/Looks/blue")
    assert "material /World/Looks/red resource ./red.png (texture)" in caplog.text
    assert "last material in the renderer log: /World/Looks/blue" in caplog.text


# -- the native log --------------------------------------------------------------------

MISSING = (
    "2026-10-24T16:13:40Z [77,482ms] [Error] [omni.rtx.materials] [UsdToMdl] Prim "
    "'/World/Looks/red/OpenPBR' parameter 'ND_image_color3__1_file': References an asset "
    "that can not be found: './red.png'"
)
CORRUPT = (
    "2026-10-24T16:38:30Z [3,796ms] [Error] [omni.rtx] Couldn't process "
    "file:/data/kitchen/PotatoRed.png, it might not have written completely. Reason: STB Failed to load image info"
)
MDL_ERROR = (
    "2026-10-24T16:38:46Z [2,417ms] [Error] [omni.rtx.materials] [MDLC:COMPILER] error: "
    "file:/data/kitchen/peru_runner_diamond_v1.mdl(7,21): C109 'df::no_such_bsdf' has not been declared"
)
OOM = "2026-10-24T16:40:00Z [9,000ms] [Error] [omni.rtx] Failed to allocate 4096 MB: out of memory"
# The lines that the renderer writes when a device runs out of memory (seen with 1 GiB of free device memory).
DEVICE_OOM = [
    "2026-10-24T17:11:31Z [9,986ms] [Error] [omni.rtx] vkAllocateMemory failed for flags: 0.",
    "2026-10-24T17:11:31Z [9,986ms] [Error] [omni.rtx] VkResult: ERROR_OUT_OF_DEVICE_MEMORY",
    "2026-10-24T17:11:31Z [9,986ms] [Error] [omni.rtx] Failed to allocate memory for resource allocator Foundation Resource Allocator",
]


def test_native_log_missing_asset_names_material_and_resource(caplog):
    """The line has the form of the renderer's own log line for an asset that is not found."""

    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        event = nl.parse_native_log_line(MISSING)
    assert (event.material, event.resource, event.kind, event.scope) == (
        "/World/Looks/red/OpenPBR", "./red.png", "texture", "material")
    assert "/World/Looks/red/OpenPBR" in caplog.text and "./red.png" in caplog.text


def test_native_log_file_failures_name_the_resource_not_a_made_up_material():
    texture = nl.parse_native_log_line(CORRUPT)
    assert (texture.material, texture.resource, texture.kind, texture.scope) == (
        rd.SCENE, "file:/data/kitchen/PotatoRed.png", "texture", "resource")
    module = nl.parse_native_log_line(MDL_ERROR)
    assert (module.resource, module.kind, module.scope) == ("file:/data/kitchen/peru_runner_diamond_v1.mdl", "mdl", "resource")


def test_native_log_memory_failure_is_scene_wide_with_a_context_hint_only():
    event = nl.parse_native_log_line(OOM, context="/World/Looks/blue/OpenPBR")
    assert (event.material, event.resource, event.kind, event.scope) == (rd.SCENE, "", "memory", "scene")
    assert event.context == "/World/Looks/blue/OpenPBR"  # a hint; the material is not set


@pytest.mark.parametrize("line", DEVICE_OOM)
def test_native_log_device_memory_exhaustion_is_a_scene_wide_memory_event(line):
    event = nl.parse_native_log_line(line, context="/World/Looks/m3/OpenPBR")
    assert (event.kind, event.scope, event.material, event.resource) == ("memory", "scene", rd.SCENE, "")


@pytest.mark.parametrize("line", [
    "2026-10-24T16:09:00Z [3,000ms] [Error] [omni.rtx] FindAppliedAPIPrimDefinition('OmniRtxSettingsGlobalRtAdvancedAPI_1') returned nothing",
    "2026-10-24T16:09:00Z [3,000ms] [Error] [omni.rtx] Could not find UsdPrimDefinition for 'OmniRtxSettingsGlobalRtAdvancedAPI_1'",
    "2026-10-24T16:08:24Z [1,090ms] [Warning] [omni.rtx] ECC is enabled on physical device 0",
    "2026-10-24T16:08:26Z [2,607ms] [Warning] [omni.rtx] invalid semantic 1578 in material omniMaterial",
    "2026-10-24T16:08:26Z [2,653ms] [Warning] [omni.rtx.materials] [MDLC:COMPILER] warn : file:/x/materialx.mdl(99,11): C183 unused parameter 'a'",
    "2026-10-24T16:08:25Z [2,357ms] [Warning] [omni.rtx] ovrtx_open_usd_from_file is deprecated; use x",
    "2026-10-24T16:08:24Z [1,341ms] [Info] [omni.rtx] Max allowing 15 shader compiler sessions based on 128.1 GB of free system memory.",
])
def test_native_log_healthy_lines_are_not_events(line):
    assert nl.parse_native_log_line(line) is None
    assert rd.get_render_diagnostics().events() == []


def test_native_log_registers_the_generated_module_directory():
    line = ("2026-10-24T16:23:05Z [2,418ms] [Info] [omni.rtx.materials] Registered MDL search path "
            "for MaterialX generated modules: file:/run/x/carb.abc")
    assert nl.parse_native_log_line(line) is None
    assert nl.generated_modules_dirs() == ["/run/x/carb.abc"]


#: The cache-key line of ovrtx (rtx.mdltranslator) for a texture of a generated MaterialX module, in the form of the
#: renderer log: one for each texture of each module when MaterialX deduplication is off.
def _body_resource(uri: str, state: str = "resolved") -> str:
    return ("2026-10-27T14:43:48Z [4,284ms] [Warning] [omni.rtx.materials] MDL material "
            "(file:/run/x/carb.abc/omni_mtlx_v2_example/materialx.mdl) "
            f"bodyResource ({uri}) could not be {state}; hashing its authored path")


def _texture(material: str, uri: str, resolved: str, missing=None) -> dict:
    """One item of render_material_report.shader_files."""

    return {"material": material, "uri": uri, "resolved": resolved, "kind": "texture", "missing": missing}


def test_body_resource_line_of_a_texture_that_the_scene_has_on_disk_is_not_a_failure(tmp_path):
    from ovui_data_adapters.common.render_material_report import record_file_events

    red = tmp_path / "textures" / "red.png"
    red.parent.mkdir()
    red.write_bytes(b"png")
    # The renderer writes the line while it compiles, before the file check of the first frame.
    assert nl.parse_native_log_line(_body_resource("./textures/red.png")) is None
    record_file_events([_texture("/World/Looks/Red", "./textures/red.png", str(red))])
    assert rd.get_render_diagnostics().events() == []
    # A line that comes after the file check is decided at once.
    assert nl.parse_native_log_line(_body_resource("./textures/red.png")) is None
    assert rd.get_render_diagnostics().events() == []


def test_body_resource_line_of_a_missing_texture_stays_a_failure(tmp_path):
    from ovui_data_adapters.common.render_material_report import record_file_events

    nl.parse_native_log_line(_body_resource("./textures/blue.png"))
    record_file_events([_texture("/World/Looks/Blue", "./textures/blue.png", "", missing="unresolved")])
    events = {(e["material"], e["resource"], e["kind"]) for e in rd.get_render_diagnostics().events()}
    assert (rd.SCENE, "./textures/blue.png", "texture") in events  # the renderer's line
    assert ("/World/Looks/Blue", "./textures/blue.png", "texture") in events  # the file check


def test_body_resource_line_is_a_failure_when_one_material_with_that_path_has_no_file(tmp_path):
    from ovui_data_adapters.common.render_material_report import record_file_events

    found = tmp_path / "a" / "albedo.png"
    found.parent.mkdir()
    found.write_bytes(b"png")
    nl.parse_native_log_line(_body_resource("./albedo.png"))
    record_file_events([
        _texture("/World/Looks/A", "./albedo.png", str(found)),
        _texture("/World/Looks/B", "./albedo.png", str(tmp_path / "b" / "albedo.png")),
    ])
    assert (rd.SCENE, "./albedo.png", "texture") in {
        (e["material"], e["resource"], e["kind"]) for e in rd.get_render_diagnostics().events()}


def test_body_resource_line_that_no_shader_of_the_scene_names_stays_a_failure(tmp_path):
    other = tmp_path / "other.png"
    other.write_bytes(b"png")
    nl.parse_native_log_line(_body_resource("./textures/body_only.png"))
    assert nl.settle_body_resources([_texture("/World/Looks/Red", "./other.png", str(other))]) == 1
    assert [e["resource"] for e in rd.get_render_diagnostics().events()] == ["./textures/body_only.png"]


def test_body_resource_lines_are_failures_when_the_files_of_the_scene_cannot_be_read():
    nl.parse_native_log_line(_body_resource("./textures/red.png"))
    assert rd.get_render_diagnostics().events() == []  # held, not dropped
    assert nl.settle_body_resources(None) == 1
    assert [e["resource"] for e in rd.get_render_diagnostics().events()] == ["./textures/red.png"]
    # Later lines of the same scene have no files to explain them either.
    nl.parse_native_log_line(_body_resource("./textures/green.png"))
    assert len(rd.get_render_diagnostics().events()) == 2


_RED_FAILED = "2026-11-06T21:18:59Z [422ms] [Error] [omni.rtx] Failed load texture file:/scene/red.png"


@pytest.mark.parametrize(
    ("case", "kept"),
    [
        ("held-then-failure", True),  # decided by the files of the scene after the reader read it
        ("already-recorded", True),  # the renderer's Python log reported the same failure first
        ("last-line-without-end", True),
        ("held-at-exit", True),  # the files of the scene were never known
        ("held-last-line-at-exit", True),  # the same, on a last line that only the cleanup reads
        ("resolved-cache-key", False),
        ("unresolved-cache-key-of-a-file-on-disk", False),
    ],
)
def test_the_native_log_is_kept_when_a_line_of_it_is_a_failure(tmp_path, monkeypatch, caplog, case, kept):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name, value in (("_OWN_LOGS", set()), ("_READ_TO", {}), ("_LOG_FAILURES", 0), ("_UNRELEASED", 0)):
        monkeypatch.setattr(nl, name, value, raising=False)
    monkeypatch.delattr(sys, "last_value", raising=False)
    red = tmp_path / "textures" / "red.png"
    red.parent.mkdir()
    red.write_bytes(b"png")
    path = nl.prepare_native_log(SimpleNamespace(log_file_path=None))
    line = {
        "held-then-failure": _body_resource("./textures/red.png", "resolved"),
        "already-recorded": _RED_FAILED,
        "last-line-without-end": _RED_FAILED,
        "held-at-exit": _body_resource("./textures/red.png", "resolved"),
        "held-last-line-at-exit": _body_resource("./textures/red.png", "resolved"),
        "resolved-cache-key": _body_resource("./textures/red.png", "encoded relative to its root module"),
        "unresolved-cache-key-of-a-file-on-disk": _body_resource("./textures/red.png", "resolved"),
    }[case]
    if case == "already-recorded":
        nl.ingest_message("[omni.rtx] Failed load texture file:/scene/red.png", force=True)
    with open(path, "w") as handle:
        handle.write(line if case in ("last-line-without-end", "held-last-line-at-exit") else line + "\n")
    nl.NativeLogTail(path).poll()
    if case == "held-then-failure":
        nl.settle_body_resources(None)
    elif case == "unresolved-cache-key-of-a-file-on-disk":
        nl.settle_body_resources([_texture("/World/Looks/Red", "./textures/red.png", str(red))])

    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        nl.remove_native_logs()

    assert os.path.exists(path) == kept
    assert (f"the native renderer log {path} is kept: the renderer log reported 1 failure(s)" in caplog.text) == kept


def test_the_native_log_is_kept_when_its_last_lines_cannot_be_read(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name, value in (("_OWN_LOGS", set()), ("_READ_TO", {}), ("_LOG_FAILURES", 0), ("_UNRELEASED", 0)):
        monkeypatch.setattr(nl, name, value, raising=False)
    monkeypatch.delattr(sys, "last_value", raising=False)
    path = nl.prepare_native_log(SimpleNamespace(log_file_path=None))
    with open(path, "w") as handle:
        handle.write(_RED_FAILED + "\n")
    os.chmod(path, 0)
    try:
        try:
            open(path, "rb").close()
        except PermissionError:
            pass
        else:
            pytest.skip("this user can read a file that has no read permission (root, or a platform without it)")
        with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
            nl.remove_native_logs()

        assert os.path.exists(path)
        assert f"the native renderer log {path} is kept: its last lines could not be read" in caplog.text
    finally:
        if os.path.exists(path):
            os.chmod(path, 0o600)


def test_body_resource_lines_of_a_closed_scene_are_failures_of_that_scene(tmp_path):
    nl.parse_native_log_line(_body_resource("./textures/red.png"))
    mark = nl.begin_scene_events()
    assert [e["resource"] for e in rd.get_render_diagnostics().events()] == ["./textures/red.png"]
    # The new scene has no files yet: its line is held. The event of the closed scene is retired.
    nl.parse_native_log_line(_body_resource("./textures/blue.png"))
    nl.retire_closed_scene_events(mark)
    assert rd.get_render_diagnostics().events() == []


def test_a_body_resource_that_the_renderer_found_is_not_a_failure():
    assert nl.parse_native_log_line(_body_resource("./textures/red.png", "encoded relative to its root module")) is None
    assert nl.settle_body_resources(None) == 0
    assert rd.get_render_diagnostics().events() == []


def test_prepare_native_log_keeps_an_existing_path_and_sets_a_missing_one(caplog):
    assert nl.prepare_native_log(SimpleNamespace(log_file_path="/x/y.log")) == "/x/y.log"
    config = SimpleNamespace(log_file_path=None)
    path = nl.prepare_native_log(config)
    assert path and config.log_file_path == path
    assert nl.prepare_native_log(None) is None

    class Frozen:
        __slots__ = ()

    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        assert nl.prepare_native_log(Frozen()) is None
    assert "native failures are not read" in caplog.text


# -- the tail and the shutdown: background tasks stop, with a time limit, and a stuck one is named --


def test_tail_keeps_half_a_line_until_it_ends(tmp_path):
    path = tmp_path / "ovrtx.log"
    path.write_text("2026-10-24T16:00:00Z [1ms] [Info] [omni.rtx] start\n")
    diagnostics = rd.RenderDiagnostics()
    tail = nl.NativeLogTail(str(path), diagnostics)
    tail.poll()
    with open(path, "a") as handle:
        handle.write(MISSING[:60])
    tail.poll()
    assert diagnostics.events() == []
    with open(path, "a") as handle:
        handle.write(MISSING[60:] + "\n")
    tail.poll()
    assert [e["resource"] for e in diagnostics.events()] == ["./red.png"]


def test_tail_thread_reads_new_lines(tmp_path):
    path = tmp_path / "ovrtx.log"
    path.write_text("")
    diagnostics = rd.RenderDiagnostics()
    tail = nl.NativeLogTail(str(path), diagnostics, interval=0.05).start()
    with open(path, "a") as handle:
        handle.write(MISSING + "\n")
    assert _wait(lambda: len(diagnostics.events()) == 1)
    assert tail.stop() is True


def test_stop_reads_the_final_lines_that_the_thread_did_not_see(tmp_path):
    """The renderer writes its last failure just before it ends: stop must read it."""

    path = tmp_path / "ovrtx.log"
    path.write_text("")
    diagnostics = rd.RenderDiagnostics()
    tail = nl.NativeLogTail(str(path), diagnostics, interval=3600).start()  # the thread never polls
    with open(path, "a") as handle:
        handle.write(CORRUPT + "\n")
    assert diagnostics.events() == []
    assert tail.stop() is True
    assert [e["resource"] for e in diagnostics.events()] == ["file:/data/kitchen/PotatoRed.png"]
    assert not tail._task.alive and tail._task not in rd.BackgroundTask.running()


class _Renderer:
    """An owner of the log reader, as a renderer adapter is."""


def test_tail_has_one_owner_per_renderer_and_stops_with_the_last(tmp_path):
    path = str(tmp_path / "ovrtx.log")
    open(path, "w").close()
    old, new = _Renderer(), _Renderer()
    first = nl.start_native_log_tail(path, old)
    assert nl.start_native_log_tail(path, new) is first
    assert nl.stop_native_log_tail(path, old) is True and first._task.alive  # a replacement renderer still writes
    assert nl.stop_native_log_tail(path, new) is True and not first._task.alive
    assert nl.native_log_paths() == []


def test_a_reader_whose_renderers_were_freed_without_a_shutdown_ends_by_itself(tmp_path):
    """Review: a renderer adapter that was dropped without a shutdown (USD Viewer without a viewport drops the
    renderer that it built for the opened file; a construction can fail after the reader started) kept the log
    reader thread and the log handler for the rest of the process."""

    path = tmp_path / "ovrtx.log"
    open(path, "w").close()
    kept, dropped = _Renderer(), _Renderer()
    nl.start_native_log(kept, SimpleNamespace(log_file_path=str(path)))
    nl.start_native_log(dropped, SimpleNamespace(log_file_path=str(path)))
    reader = nl._TAILS[str(path)][0]
    del dropped
    time.sleep(1.2)  # more than two reads: a renderer that is still alive keeps the reader
    assert reader._task.alive and nl.native_log_paths() == [str(path)]
    with open(path, "a") as handle:
        handle.write(MDL_ERROR + "\n")
    del kept
    assert _wait(lambda: not reader._task.alive)
    assert nl.native_log_paths() == [] and rd.BackgroundTask.running() == []
    assert [e["kind"] for e in rd.get_render_diagnostics().events()] == ["mdl"]  # read before the reader ended
    assert not any(isinstance(h, nl.RendererLogHandler) for h in logging.getLogger("ovrtx").handlers)


def test_release_native_log_reads_the_last_lines_and_removes_the_handler(tmp_path):
    path = tmp_path / "ovrtx.log"
    open(path, "w").close()
    owner = SimpleNamespace()
    nl.start_native_log(owner, SimpleNamespace(log_file_path=str(path)))
    assert owner._native_log_path == str(path)
    assert any(isinstance(h, nl.RendererLogHandler) for h in logging.getLogger("ovrtx").handlers)
    with open(path, "a") as handle:
        handle.write(MDL_ERROR + "\n")
    nl.release_native_log(owner)
    assert owner._native_log_path is None and nl.native_log_paths() == []
    assert [e["kind"] for e in rd.get_render_diagnostics().events()] == ["mdl"]
    assert not any(isinstance(h, nl.RendererLogHandler) for h in logging.getLogger("ovrtx").handlers)
    nl.release_native_log(owner)  # a second call is harmless


def test_a_task_that_does_not_stop_is_reported_and_raises(caplog):
    release = threading.Event()
    task = rd.BackgroundTask("ovui-test-stuck", release.wait, interval=None).start()
    try:
        with caplog.at_level(logging.ERROR, logger="ovui.render_diagnostics"):
            stuck = rd.shutdown_background_tasks(timeout=0.1)
        assert stuck == ["ovui-test-stuck"] and "did not stop" in caplog.text
        with pytest.raises(rd.BackgroundTaskStuckError, match="ovui-test-stuck"):
            rd.raise_if_stuck(stuck)
    finally:
        release.set()
        assert task.stop(5.0)


def test_release_native_log_raises_when_the_reader_does_not_stop(monkeypatch):
    monkeypatch.setattr(nl, "stop_native_log_tail", lambda path, owner: False)
    owner = SimpleNamespace(_native_log_path="/x/y.log")
    with pytest.raises(rd.BackgroundTaskStuckError, match="/x/y.log"):
        nl.release_native_log(owner)


def test_host_memory_watch_warns_once_near_the_limit_and_its_thread_ends(monkeypatch, caplog):
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.HostMemory(64 * rd.GIB, 60 * rd.GIB, "test"))
    diagnostics = rd.RenderDiagnostics()
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        with rd.HostMemoryWatch("the first native step", interval=0.01, diagnostics=diagnostics) as watch:
            assert _wait(lambda: diagnostics.events())
            time.sleep(0.05)
    assert [e["kind"] for e in diagnostics.events()] == ["memory"]
    assert "60.0 of 64.0 GiB during the first native step" in caplog.text
    assert not watch._task.alive


def _cgroup(tmp_path, current_gib, stat_gib, limit_gib=128, version=2):
    """A cgroup folder as the kernel shows it, with memory use and the named memory.stat lines in GiB."""

    root = tmp_path / "cgroup"
    folder = root if version == 2 else root / "memory"
    folder.mkdir(parents=True)
    names = ("memory.max", "memory.current", "memory.stat") if version == 2 else (
        "memory.limit_in_bytes", "memory.usage_in_bytes", "memory.stat")
    (folder / names[0]).write_text(f"{int(limit_gib * rd.GIB)}\n")
    (folder / names[1]).write_text(f"{int(current_gib * rd.GIB)}\n")
    (folder / names[2]).write_text("".join(f"{k} {int(v * rd.GIB)}\n" for k, v in stat_gib.items()))
    return str(root)


def test_host_memory_leaves_out_the_file_cache_that_the_kernel_can_reclaim(tmp_path):
    """The healthy Factory case of the review: 120.7 of 128 GiB in the cgroup, of it about 103 GiB file cache."""

    root = _cgroup(tmp_path, 120.7, {"anon": 17.0, "file": 103.2, "shmem": 0.2, "active_file": 3.0,
                                      "inactive_file": 100.0, "slab_reclaimable": 0.5})
    host = rd.read_linux_memory(root, meminfo=str(tmp_path / "none"))
    assert host.source == "cgroup2" and host.limit_bytes == 128 * rd.GIB
    assert host.used_bytes == pytest.approx(17.2 * rd.GIB, rel=1e-6)
    assert host.reclaimable_bytes == pytest.approx(103.5 * rd.GIB, rel=1e-6)


def test_host_memory_of_cgroup_v1_leaves_out_its_file_cache(tmp_path):
    root = _cgroup(tmp_path, 60.0, {"total_active_file": 10.0, "total_inactive_file": 30.0, "rss": 20.0},
                   limit_gib=64, version=1)
    host = rd.read_linux_memory(root, meminfo=str(tmp_path / "none"))
    assert host.source == "cgroup1" and host.used_bytes == 20 * rd.GIB and host.reclaimable_bytes == 40 * rd.GIB


@pytest.mark.parametrize("stat,fires", [
    ({"anon": 17.0, "active_file": 3.0, "inactive_file": 100.0}, False),  # a large file cache: no warning
    ({"anon": 110.0, "active_file": 3.0, "inactive_file": 7.6}, True),     # memory that cannot be reclaimed: warning
])
def test_the_first_step_watch_warns_only_for_memory_that_cannot_be_reclaimed(tmp_path, monkeypatch, stat, fires):
    root = _cgroup(tmp_path, 120.7, stat)
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.read_linux_memory(root, meminfo=str(tmp_path / "none")))
    diagnostics = rd.RenderDiagnostics()
    with rd.HostMemoryWatch("the first native step", interval=0.01, diagnostics=diagnostics) as watch:
        if fires:
            assert _wait(lambda: diagnostics.events())
        else:
            time.sleep(0.2)
    assert not watch._task.alive
    events = diagnostics.events()
    if fires:
        assert [e["kind"] for e in events] == ["memory"]
        assert "110.1 of 128.0 GiB (not counting 10.6 GiB of reclaimable cache)" in events[0]["message"]
    else:
        assert events == []


# -- the failures of the open scene ------------------------------------------------------


def test_a_new_scene_retires_the_failures_of_the_scene_that_it_replaces():
    diagnostics = rd.RenderDiagnostics()
    diagnostics.record("/World/Looks/Tex", "./missing_red.png", "texture", "texture unresolved: ./missing_red.png")
    diagnostics.record(rd.SCENE, "", "memory", "out of memory in the old scene")
    mark = diagnostics.begin_scene()
    # While the new scene loads, the old failures stay (a load that fails must not lose them) ...
    assert len(diagnostics.events()) == 2
    # ... and a failure of the new scene with the same key is recorded for the new scene.
    assert diagnostics.record("/World/Looks/Tex", "./missing_red.png", "texture", "again in the new scene") is not None
    diagnostics.record("/World/Looks/Other", "./other.png", "texture", "new")
    assert diagnostics.retire_before(mark) == 1
    assert [(e["material"], e["message"]) for e in diagnostics.events()] == [
        ("/World/Looks/Tex", "again in the new scene"), ("/World/Looks/Other", "new"),
    ]
    assert diagnostics.record("/World/Looks/Other", "./other.png", "texture", "twice") is None


def test_the_scene_boundary_reads_the_old_log_lines_first_and_drops_the_old_check_result(tmp_path):
    log = tmp_path / "ovrtx.log"
    log.write_text("")
    owner = SimpleNamespace()
    nl.start_native_log(owner, SimpleNamespace(log_file_path=str(log)))
    try:
        rd.set_verification({"/World/Looks/Old": {"state": "mismatch"}})
        # A line of the closed scene that the reader thread has not read yet.
        with open(log, "a") as handle:
            handle.write("2026-10-26T20:00:00Z [1ms] [Error] [omni.rtx] Failed load texture file:/old/floor.png. failed\n")
        mark = nl.begin_scene_events()
        assert any(e["resource"] == "file:/old/floor.png" for e in rd.get_render_diagnostics().events())
        nl.retire_closed_scene_events(mark)
        assert rd.get_render_diagnostics().events() == [] and rd.get_verification() == {}
    finally:
        nl.release_native_log(owner)


def test_regression_native_log_lines_stay_when_the_log_handler_sees_a_python_message():
    handler = nl.RendererLogHandler()
    record = logging.LogRecord("ovrtx", logging.ERROR, "", 0, "Failed to load texture /a/b.png: out of memory", None, None)
    handler.emit(record)
    event = rd.get_render_diagnostics().events()[0]
    assert (event["kind"], event["resource"], event["scope"]) == ("memory", "/a/b.png", "resource")


def test_only_the_newest_generated_module_directories_are_kept():
    for index in range(10):
        nl.register_generated_modules_dir(f"/run/x/carb.{index}")
    nl.register_generated_modules_dir("/run/x/carb.9")
    assert nl.generated_modules_dirs() == [f"/run/x/carb.{i}" for i in (6, 7, 8, 9)]


def test_a_directory_or_file_in_a_message_is_not_taken_for_a_material():
    event = nl.ingest_message("Failed to allocate memory in /run/horde-runtime/horde/carb.x for 'MemoryManager-allocate'")
    assert event.material == rd.SCENE and event.kind == "memory"
    named = nl.ingest_message("Failed to load texture '/data/tex/potato.png' for material /World/Kitchen/Looks/PotatoRed: out of memory")
    assert (named.material, named.resource, named.kind) == ("/World/Kitchen/Looks/PotatoRed", "/data/tex/potato.png", "memory")


def test_the_log_context_is_a_prim_path_and_never_a_directory(tmp_path):
    path = tmp_path / "ovrtx.log"
    path.write_text(
        "2026-10-24T16:23:05Z [2,418ms] [Info] [omni.rtx.materials] Registered MDL search path for MaterialX "
        "generated modules: file:/run/horde-runtime/horde/carb.ezTSPw\n"
        "2026-10-24T16:23:05Z [2,543ms] [Info] [omni.rtx.materials] MaterialX::NodeDef for node: "
        "'/World/Looks/red/normalmap' in material: '/World/Looks/red' was upgraded\n"
        "2026-10-24T16:23:05Z [2,600ms] [Info] [omni.rtx.materials] Texture cache is at /var/cache/x\n"
    )
    tail = nl.NativeLogTail(str(path), rd.RenderDiagnostics())
    tail.poll()
    assert tail.context == "/World/Looks/red"


def test_a_file_failure_that_the_renderer_reports_after_the_first_frame_still_names_its_materials():
    """A texture can fail to load long after the first frame (the regression kitchen: about 90 s); the warning and
    health must still name the material, not only the file."""

    from ovui_data_adapters.common.render_material_report import FileEventLinker

    files = [{"material": "/World/Looks/Potato", "uri": "./PotatoRed.png", "resolved": "/scene/PotatoRed.png",
              "kind": "texture", "missing": None}]
    diagnostics = rd.RenderDiagnostics()
    linker = FileEventLinker(files, interval=1.0)
    assert linker.poll(now=0.0, diagnostics=diagnostics) is True  # nothing to link yet
    assert linker.poll(now=5.0, diagnostics=diagnostics) is False  # no new event: no work
    nl.parse_native_log_line(
        "2026-10-26T21:42:25Z [93,304ms] [Error] [omni.rtx] Failed load texture file:/scene/PotatoRed.png. "
        "UJITSO request failed", diagnostics)
    assert linker.poll(now=5.5, diagnostics=diagnostics) is True
    named = [(e["material"], e["kind"]) for e in diagnostics.events() if e["scope"] == "material"]
    assert named == [("/World/Looks/Potato", "texture")]
    nl.parse_native_log_line(
        "2026-10-26T21:42:26Z [94,000ms] [Error] [omni.rtx] Failed load texture file:/scene/Other.png. failed", diagnostics)
    assert linker.poll(now=5.9, diagnostics=diagnostics) is False  # at most once a second
    assert linker.poll(now=6.6, diagnostics=diagnostics) is True
