# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Subprocess regression test for issue #35 — Step 8.

Encodes the Phase 0 reproduction as an automated test:

    Launch real ``python -m ovwidgets.app cube.usda`` as a subprocess
    Inject auto-close after 60 frames via sitecustomize
    Assert rc == 0 (was 139 before the fix landed)
    Assert ovrtx actually loaded (NOT MockRendererAdapter)

Design constraints (Codex review history):

* Round 1 F11 / Round 2 F8 — invoke the LITERAL command
  ``[sys.executable, "-m", "ovwidgets.app", scene]``. No ``runpy.run_module``
  from a wrapper script: that changes ``sys.argv[0]``, ``sys.path[0]``,
  and ``sys.modules["__main__"]`` semantics relative to a real ``-m``
  launch.
* Round 1 F12 — subprocess timeout = hard test failure. A hung shutdown
  is a regression, not a silent skip.
* Round 1 F13 / Round 2 F9 — assert ovrtx-specific log markers
  (``omni.rtx`` or ``omni.ujitso``) NOT ``VulkanBackend`` (which is
  printed by ovui regardless of whether ovrtx ever loaded).
* Round 1 F14 — HOME and cwd isolation via ``tmp_path``. The
  subprocess writes ``imgui.ini`` and ``~/.ovgear/`` into the temp
  directory, never the user's real config.
* Round 3 F1 — sitecustomize.py only loads if its directory is on
  PYTHONPATH at interpreter init. ``_child_env`` prepends ``tmp_path``
  to PYTHONPATH explicitly.
* Round 6 F5 — also prepend the repo root so ``python -m ovwidgets.app``
  can resolve the ``ovwidgets.app`` package.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCENE = REPO / "tests/fixtures/cube.usda"


def _scrub_external_usd(value: str) -> str:
    """Remove external usd-build paths from a PATH-like environment value."""
    parts = [p for p in value.split(os.pathsep) if p]
    kept = [p for p in parts if "usd-build" not in p]
    return os.pathsep.join(kept)


def _vulkan_gpu_available() -> bool:
    """Return True if a real ovrtx-capable GPU is available.

    This probe is intentionally cheap — it never spins up omni.ui or
    the full OvGear stack. The purpose is the same as the ``DISPLAY``
    guard below: skip the test gracefully when the required hardware is
    absent rather than failing noisily on an environment issue.

    Each tool is guarded with ``shutil.which`` before calling so that
    collection-time failures (``FileNotFoundError``) cannot occur on
    machines where vulkaninfo or nvidia-smi are not installed.

    Two-signal check (both must succeed):

    1. ``vulkaninfo --summary`` must enumerate at least one non-software
       Vulkan device. ``vulkaninfo`` returns rc=0 even when only the
       Mesa software rasterizer (``llvmpipe``, vendor ``0x10005``) is
       present — that fallback cannot satisfy ovrtx, which requires
       hardware ray tracing. We grep the summary output for any GPU
       block whose ``deviceName`` is not ``llvmpipe`` and whose vendor
       id is not the Mesa software-rasterizer id.
    2. ``nvidia-smi`` must exit cleanly. ovrtx initializes NVML during
       device creation, and a broken NVML produces a shutdown segfault
       deep inside libgpu.foundation regardless of how Vulkan looks at
       enumeration time. ``nvidia-smi`` exit-0 is the cheapest reliable
       signal that NVML is operational.

    If either signal fails, ovrtx will fail to create a device and the
    subprocess will segfault during shutdown teardown — which is an
    infrastructure failure, not a regression of the issue-#35 contract
    this test exists to defend. Skip in that case.
    """
    # 1. vulkaninfo must enumerate a real (non-software) GPU.
    real_vulkan = False
    if shutil.which("vulkaninfo"):
        try:
            vulkaninfo = subprocess.run(
                ["vulkaninfo", "--summary"],
                capture_output=True,
                timeout=10,
            )
            if vulkaninfo.returncode == 0:
                summary = vulkaninfo.stdout.decode("utf-8", errors="replace")
                # Scan device blocks; accept the probe only if at least
                # one device is not a software rasterizer.
                for line in summary.splitlines():
                    line = line.strip()
                    if not line.startswith("deviceName"):
                        continue
                    name = line.split("=", 1)[1].strip().lower() if "=" in line else ""
                    if name and "llvmpipe" not in name and "swrast" not in name:
                        real_vulkan = True
                        break
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    if not real_vulkan:
        return False

    # 2. NVML must be healthy. ovrtx loads NVML during device creation
    # and a broken NVML guarantees a shutdown segfault in
    # libgpu.foundation::DriverShaderCacheManager::shutdown — not a
    # regression of issue #35.
    if shutil.which("nvidia-smi"):
        try:
            smi = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                timeout=10,
            )
            if smi.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    return False


_NO_GPU = not _vulkan_gpu_available()
_no_gpu_reason = "no Vulkan-capable GPU available (NVML/Vulkan probe failed)"


# Inline sitecustomize.py source. Written into ``tmp_path`` per test;
# CPython's site.py imports it during interpreter startup IF the
# directory containing it is on PYTHONPATH (or sys.path[0]). For
# ``python -m ovwidgets.app`` in our isolated cwd, sys.path[0] is the cwd
# AFTER site.py runs, so we MUST prepend tmp_path to PYTHONPATH —
# verified empirically (see Round 3 F1 in the plan/investigation).
SITECUSTOMIZE = textwrap.dedent('''
    """sitecustomize injected by tests/test_clean_exit_subprocess.py.

    Installs an auto-close trigger on Application.run_async so the
    subprocess exits naturally after OVGEAR_AUTO_CLOSE_FRAMES frames,
    without bypassing Application.run.
    """
    import os
    _FRAMES = int(os.environ.get("OVGEAR_AUTO_CLOSE_FRAMES", "60"))


    def _install() -> None:
        import asyncio
        from ovwidgets.app.application import Application
        original = Application.run_async

        async def patched(self):
            async def auto_close():
                import omni.ui as ui
                for _ in range(_FRAMES):
                    await ui.next_frame()
                self._running = False
            task = asyncio.ensure_future(auto_close())
            try:
                return await original(self)
            finally:
                task.cancel()

        Application.run_async = patched


    # Defer the install until after ovwidgets.app.application is importable.
    # We schedule it as a sys.audit hook so it fires the first time
    # anyone imports ovwidgets.app.application — i.e. inside ovwidgets.app/__main__.main().
    import sys as _sys
    _ovgear_application_loaded = [False]
    def _audit(event, args):
        if _ovgear_application_loaded[0]:
            return
        if event == "import":
            mod = args[0] if args else ""
            if mod == "ovwidgets.app.application":
                _ovgear_application_loaded[0] = True
                _install()
    try:
        _sys.addaudithook(_audit)
    except Exception:
        pass
''')


def _child_env(headless: bool, tmp_home: Path) -> dict:
    """Build the subprocess's environment.

    See module docstring for the rationale on each variable.
    """
    env = os.environ.copy()
    env["OVRTX_SKIP_USD_CHECK"] = "1"
    # Round 3 F1 + Round 6 F5: PYTHONPATH must contain
    #   1. tmp_home   — for sitecustomize.py discovery
    #   2. REPO       — for ``python -m ovwidgets.app`` to find the package
    #
    # Keep the external usd-build path OUT of the child. ovrtx loads its own
    # USD-adjacent libraries; mixing those with ~/dev/usd-build in the same
    # subprocess can hang during headless renderer startup. The venv now carries
    # the real usd-core==25.11 wheel, which satisfies pxr imports without that
    # external library path.
    pp = (
        f"{tmp_home}:{REPO}:"
        f"{_scrub_external_usd(env.get('PYTHONPATH', ''))}"
    )
    env["PYTHONPATH"] = pp
    env["LD_LIBRARY_PATH"] = _scrub_external_usd(env.get("LD_LIBRARY_PATH", ""))
    env["OVGEAR_AUTO_CLOSE_FRAMES"] = "60"
    # Round 1 F14: HOME isolation. ovgear writes ~/.ovgear/layout.json;
    # we redirect that to tmp_home so the user's real config is
    # untouched.
    real_home = env.get("HOME", "")
    env["HOME"] = str(tmp_home)
    if headless:
        env["OMNIUI_HEADLESS"] = "1"
        env["OMNIUI_BACKEND"] = "vulkan"
    else:
        # Windowed mode needs X11 auth. The default X cookie path is
        # ``$HOME/.Xauthority``, but our HOME isolation above redirects
        # that to ``tmp_path/.Xauthority`` which doesn't exist — the
        # subprocess fails with ``Authorization required, but no
        # authorization protocol specified``. Explicitly point
        # ``XAUTHORITY`` at the real-user cookie file so the GLFW
        # window in the child can authenticate against the X server.
        if "XAUTHORITY" not in env and real_home:
            real_xauth = os.path.join(real_home, ".Xauthority")
            if os.path.exists(real_xauth):
                env["XAUTHORITY"] = real_xauth
    return env


def _run_ovgear_subprocess(headless: bool, tmp_path: Path):
    """Drive the test machinery (sitecustomize write + subprocess
    launch + decode). Returns the completed-process record.

    Raises ``pytest.fail`` on subprocess timeout (Round 1 F12).
    """
    # Round 3 F1: write sitecustomize.py to tmp_path. The
    # _child_env's PYTHONPATH prefix puts tmp_path on sys.path so
    # site.py finds it during interpreter startup.
    (tmp_path / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")

    try:
        return subprocess.run(
            # Round 2 F8: literal `python -m ovwidgets.app` — same as a real user.
            [sys.executable, "-m", "ovwidgets.app", str(SCENE)],
            env=_child_env(headless, tmp_path),
            cwd=str(tmp_path),
            capture_output=True,
            timeout=120,             # Round 1 F12: hard fail on hang.
        )
    except subprocess.TimeoutExpired as e:
        pytest.fail(
            f"OvGear hung past 120s — likely shutdown stuck. "
            f"stdout tail:\n"
            f"{(e.stdout or b'').decode(errors='replace')[-1500:]}\n"
            f"stderr tail:\n"
            f"{(e.stderr or b'').decode(errors='replace')[-1500:]}"
        )


@pytest.mark.parametrize(
    "headless", [False, True], ids=["windowed", "headless"]
)
@pytest.mark.parametrize("run_idx", [1, 2, 3])
@pytest.mark.skipif(_NO_GPU, reason=_no_gpu_reason)
def test_clean_exit(headless: bool, run_idx: int, tmp_path: Path) -> None:
    """OvGear must exit with rc=0 after a normal close, with ovrtx loaded.

    Three runs per backend so a non-deterministic regression
    (e.g., a Py_FinalizeEx GC ordering issue that depends on hash
    randomisation) shows up.
    """
    if not headless and not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY for windowed mode")

    proc = _run_ovgear_subprocess(headless, tmp_path)

    # Round 1 F13 + Round 2 F9: assert ovrtx ACTUALLY loaded. If it
    # silently fell back to MockRendererAdapter, this test would
    # spuriously pass against the original buggy code.
    #
    # Markers are ovrtx-specific. ``VulkanBackend`` was DROPPED in
    # Round 2 F9 because that line is printed by ovui's standalone
    # Vulkan backend regardless of whether ovrtx ever loaded.
    #
    # The original Round 2 F9 list was ``omni.rtx`` and
    # ``omni.ujitso`` — but those are LEAK warnings emitted during
    # buggy shutdown (Phase 0's run4 log). Now that issue #35 fixes
    # the cleanup, those leak markers don't fire. We need markers
    # that appear on EVERY ovrtx-loaded run (clean or buggy):
    #
    #   - HD_ENABLE_SCENE_INDEX_EMULATION  — emitted by ovrtx's USD
    #     bootstrap when it overrides the USD env. Always at startup.
    #   - OMNI_USD_RESOLVER_MDL_BUILTIN_BYPASS — same path, also at
    #     startup.
    #   - omni.rtx / omni.ujitso — Phase-0-style leak warnings; kept
    #     for backward compatibility against the buggy regression case.
    #
    # The mock renderer brings up neither USD nor carb plugins, so
    # none of these markers appear in a mock-fallback run.
    stderr_text = proc.stderr.decode("utf-8", errors="replace")
    stdout_text = proc.stdout.decode("utf-8", errors="replace")
    combined = stderr_text + "\n" + stdout_text
    ovrtx_markers = (
        "HD_ENABLE_SCENE_INDEX_EMULATION",
        "OMNI_USD_RESOLVER_MDL_BUILTIN_BYPASS",
        "omni.rtx",
        "omni.ujitso",
    )
    assert any(m in combined for m in ovrtx_markers), (
        "ovrtx did not load — likely fell back to MockRendererAdapter. "
        "Without a real ovrtx renderer, the issue-35 segfault never "
        "reproduces and this test would silently pass against the bug. "
        f"None of {ovrtx_markers!r} appeared in the subprocess output.\n"
        f"stderr tail:\n{stderr_text[-2000:]}\n"
        f"stdout tail:\n{stdout_text[-2000:]}"
    )

    # The headline contract: rc=0, NOT 139 (SIGSEGV in Py_FinalizeEx).
    assert proc.returncode == 0, (
        f"rc={proc.returncode}; "
        f"stderr tail:\n{stderr_text[-2000:]}"
    )
