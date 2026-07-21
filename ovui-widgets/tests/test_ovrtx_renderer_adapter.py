# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""GPU-gated integration tests for :class:`OvRtxRendererAdapter`.

These tests require ``ovrtx`` to be importable AND a working NVIDIA
GPU with ``nvidia-smi`` on PATH. Each test spawns a clean Python
subprocess — ovrtx ships its own bundled USD which conflicts with
``pxr`` at load time under certain import orders, and in-process
re-use of ovrtx after Hydra-init failures has been observed to
segfault subsequent tests. Subprocess isolation makes the suite
deterministic at the cost of a few seconds per test.

Covers Step A.3's acceptance criteria: loading the planet-system
reference scene, rendering a ``(H, W, 4)`` uint8 RGBA frame with
non-zero pixels, camera motion changing the rendered image, resolution
changes, and shutdown-safety.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

# --- Gating ---------------------------------------------------------------

_REFERENCE_SCENE = "<path-to-ovrtx>/examples/python/planet-system/simple_scene.usda"
_OVGEAR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_REASONS = []
# Basic import check — fast, does not hit ovrtx's C library init path.
try:
    import ovrtx  # noqa: F401
except Exception as _exc:  # pragma: no cover — CPU-only machines skip
    _REASONS.append(f"ovrtx import failed: {_exc!r}")
if shutil.which("nvidia-smi") is None:
    _REASONS.append("nvidia-smi not on PATH")
if not os.path.exists(_REFERENCE_SCENE):
    _REASONS.append(f"reference scene missing: {_REFERENCE_SCENE}")
# Check that pxr is importable in the subprocess environment.  The subprocess
# runner scrubs the external usd-build path from PYTHONPATH because ovrtx
# ships its own bundled pxr which conflicts with an externally installed one.
# If pxr is only available via the external usd-build path (and not via a
# venv-installed usd-core wheel), the tests will fail inside the subprocess.
try:
    import subprocess as _sp
    _scrubbed_pp = os.pathsep.join(
        p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if "usd-build" not in p and p
    )
    _pxr_check = _sp.run(
        [sys.executable, "-c", "import pxr"],
        capture_output=True,
        timeout=10,
        env={**os.environ, "PYTHONPATH": _scrubbed_pp},
    )
    if _pxr_check.returncode != 0:
        _REASONS.append(
            "pxr not importable in subprocess env after scrubbing usd-build "
            "(no venv-installed usd-core wheel found)"
        )
except Exception as _exc:
    _REASONS.append(f"pxr subprocess check failed: {_exc!r}")

pytestmark = pytest.mark.skipif(
    bool(_REASONS),
    reason="; ".join(_REASONS) or "unreachable",
)


# --- Subprocess runner ---------------------------------------------------


def _run_in_subprocess(script: str, timeout: int = 180) -> dict:
    """Run ``script`` in a fresh Python interpreter and return its JSON result.

    The script must print a single-line JSON payload prefixed with
    ``RESULT:`` to stdout. The subprocess receives a scrubbed
    environment: any external USD install (``~/dev/usd-build``) is
    pulled off ``PYTHONPATH``/``LD_LIBRARY_PATH`` because ovrtx ships
    its own bundled pxr and loading two libusd copies in the same
    process aborts on ``SDF_ASSET`` re-registration. The venv's
    ``usd-core`` wheel coexists with ovrtx cleanly.

    Returns the parsed JSON dict. Raises :class:`AssertionError` with a
    truncated stderr tail on crash / non-zero exit / missing RESULT.
    """
    env = os.environ.copy()
    env["OVRTX_SKIP_USD_CHECK"] = "1"

    def _scrub(value: str, needles=("usd-build",)) -> str:
        parts = [p for p in value.split(os.pathsep) if p]
        kept = [p for p in parts if not any(n in p for n in needles)]
        return os.pathsep.join(kept)

    # Make sure the test subprocess can import the project, AND
    # strip any external USD install from the path — see docstring.
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [_OVGEAR_ROOT, _scrub(env.get("PYTHONPATH", ""))])
    )
    env["LD_LIBRARY_PATH"] = _scrub(env.get("LD_LIBRARY_PATH", ""))

    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"subprocess exited with {proc.returncode}\n"
            f"stderr tail:\n{proc.stderr[-2000:]}"
        )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT:"):
            return json.loads(line[len("RESULT:"):])
    raise AssertionError(
        f"no RESULT: line in stdout\nstdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )


_LOAD_ORDER_PREAMBLE = textwrap.dedent(f"""
    # Critical: pxr must be imported and a real stage opened BEFORE the
    # adapter triggers its lazy ovrtx import. Opening the reference scene
    # also warm-starts pxr's asset resolver with the directory ovrtx
    # needs to find its own bundled MDL materials from.
    import json, os
    from pxr import Usd
    _warm = Usd.Stage.Open({_REFERENCE_SCENE!r})

    import numpy as np
    from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter
    from ovui_widgets.viewport.camera_controller import CameraController
    from ovui_data_adapters.common import GpuFrame

    def _frame_summary(frame):
        if isinstance(frame, GpuFrame):
            try:
                return {{
                    "kind": "gpu",
                    "shape": [int(frame.height), int(frame.width), 4],
                    "ptr_nonzero": bool(frame.ptr),
                }}
            finally:
                frame.close()
        return {{
            "kind": "cpu",
            "shape": list(frame.shape),
            "dtype": str(frame.dtype),
            "max": int(frame.max()),
            "mean": float(frame.mean()),
            "nonzero_pixels": int((frame != 0).any(axis=2).sum()),
            "unique_colors": int(len(np.unique(frame.reshape(-1, 4), axis=0))),
        }}
""")


# --- Tests ---------------------------------------------------------------


class TestAppendixAAcceptance:
    def test_render_planet_system_produces_nonzero_frame(self):
        """The primary Step A.3 gate — Appendix A from the viewport behavior."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            stage = Usd.Stage.Open({_REFERENCE_SCENE!r})
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)

            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            view, proj = cam.get_matrices(1280, 720)
            frame = adapter.render_frame(1280, 720, view, proj)
            try:
                result = _frame_summary(frame)
                print("RESULT:" + json.dumps(result))
            finally:
                adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["shape"] == [720, 1280, 4]
        if result["kind"] == "gpu":
            assert result["ptr_nonzero"] is True
            return
        assert result["dtype"] == "uint8"
        assert result["max"] > 0, "rendered frame is all-zero"
        # A lit scene with a red sphere + ground plane + cube must have
        # many unique colors and a big chunk of non-black pixels.
        assert result["nonzero_pixels"] > 720 * 1280 * 0.5
        assert result["unique_colors"] > 100


class TestCameraControllerDrivesRender:
    def test_orbit_changes_image(self):
        """Orbiting CameraController must produce a visibly different frame."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            stage = Usd.Stage.Open({_REFERENCE_SCENE!r})
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)

            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            view1, proj1 = cam.get_matrices(640, 480)
            frame1 = adapter.render_frame(640, 480, view1, proj1)

            cam.orbit(1.0, 0.2)
            view2, proj2 = cam.get_matrices(640, 480)
            frame2 = adapter.render_frame(640, 480, view2, proj2)

            diff_px = int((frame1 != frame2).any(axis=2).sum())
            total = frame1.shape[0] * frame1.shape[1]
            result = {{
                "diff_pixels": diff_px,
                "total_pixels": total,
                "diff_fraction": diff_px / total,
            }}
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        # Orbit of >1 radian should change substantially more than 5%
        # of pixels — empirically we see ~45% on the planet scene.
        assert result["diff_fraction"] > 0.05, (
            f"only {result['diff_fraction'] * 100:.2f}% pixels changed"
        )


class TestResolutionChange:
    def test_different_resolutions_render_correctly(self):
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            stage = Usd.Stage.Open({_REFERENCE_SCENE!r})
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)

            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            frame_a = adapter.render_frame(640, 480, *cam.get_matrices(640, 480))
            frame_b = adapter.render_frame(1024, 768, *cam.get_matrices(1024, 768))
            result = {{
                "frame_a": _frame_summary(frame_a),
                "frame_b": _frame_summary(frame_b),
            }}
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["frame_a"]["shape"] == [480, 640, 4]
        assert result["frame_b"]["shape"] == [768, 1024, 4]
        for frame in (result["frame_a"], result["frame_b"]):
            if frame["kind"] == "gpu":
                assert frame["ptr_nonzero"] is True
            else:
                assert frame["max"] > 0

    def test_set_resolution_does_not_raise(self):
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            adapter = OvRtxRendererAdapter()
            adapter.set_resolution(1920, 1080)
            print("RESULT:" + json.dumps({"pending": list(adapter._pending_resolution)}))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["pending"] == [1920, 1080]


class TestLoadStageAcceptsBoth:
    def test_load_from_path_string(self):
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)
            adapter = OvRtxRendererAdapter()
            adapter.load_stage({_REFERENCE_SCENE!r})
            frame = adapter.render_frame(320, 240, *cam.get_matrices(320, 240))
            result = _frame_summary(frame)
            result.update({{
                "stage_is_not_none": adapter._stage is not None,
            }})
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["stage_is_not_none"] is True
        assert result["shape"] == [240, 320, 4]
        if result["kind"] == "gpu":
            assert result["ptr_nonzero"] is True
        else:
            assert result["max"] > 0

    def test_load_anonymous_stage_uses_inline_root_when_supported(self):
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            from pxr import UsdGeom
            from ovui_data_adapters.openusd import renderer_adapter as renderer_mod
            stage = Usd.Stage.CreateInMemory()
            world = UsdGeom.Xform.Define(stage, "/World")
            stage.SetDefaultPrim(world.GetPrim())
            UsdGeom.Cube.Define(stage, "/World/Cube")
            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            tmp = adapter._owned_tmp_path
            exists = os.path.exists(tmp) if tmp else False
            inline_supported = (
                getattr(adapter._renderer, "open_usd_from_string", None) is not None
            )
            result = {
                "inline_supported": inline_supported,
                "tmp_path": tmp,
                "exists": exists,
                "uses_root_sentinel": adapter._usd_handle is renderer_mod._ROOT_STAGE_SENTINEL,
            }
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        if result["inline_supported"]:
            assert result["tmp_path"] is None
            assert result["exists"] is False
            assert result["uses_root_sentinel"] is True
        else:
            assert result["tmp_path"], "legacy anonymous stage should produce a temp path"
            assert result["exists"] is True

    def test_reloading_anonymous_stage_replaces_inline_root(self):
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            from pxr import UsdGeom
            from ovrtx import Device
            from ovui_data_adapters.openusd import renderer_adapter as renderer_mod

            def _make_stage(root_name, child_name):
                stage = Usd.Stage.CreateInMemory()
                root = UsdGeom.Xform.Define(stage, f"/{root_name}")
                stage.SetDefaultPrim(root.GetPrim())
                UsdGeom.Cube.Define(stage, f"/{root_name}/{child_name}")
                return stage

            def _debug_dump(adapter):
                products = adapter._renderer.step(
                    render_products={"ovrtx_debug_dump_stage"}, delta_time=0.0
                )
                rv = products["ovrtx_debug_dump_stage"].frames[0].render_vars["debug"]
                with rv.map(device=Device.CPU) as mapping:
                    return mapping.tensor.to_bytes().decode("utf-8")

            adapter = OvRtxRendererAdapter()
            adapter.load_stage(_make_stage("FirstRoot", "OnlyInFirst"))
            inline_supported = (
                getattr(adapter._renderer, "open_usd_from_string", None) is not None
            )
            first_uses_sentinel = (
                adapter._usd_handle is renderer_mod._ROOT_STAGE_SENTINEL
            )
            first_tmp = adapter._owned_tmp_path

            adapter.load_stage(_make_stage("SecondRoot", "OnlyInSecond"))
            second_uses_sentinel = (
                adapter._usd_handle is renderer_mod._ROOT_STAGE_SENTINEL
            )
            second_tmp = adapter._owned_tmp_path
            dump = _debug_dump(adapter)
            result = {
                "inline_supported": inline_supported,
                "first_uses_sentinel": first_uses_sentinel,
                "second_uses_sentinel": second_uses_sentinel,
                "first_tmp": first_tmp,
                "second_tmp": second_tmp,
                "has_first_root": "FirstRoot" in dump or "OnlyInFirst" in dump,
                "has_second_root": "SecondRoot" in dump and "OnlyInSecond" in dump,
            }
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["has_second_root"] is True
        assert result["has_first_root"] is False
        if result["inline_supported"]:
            assert result["first_uses_sentinel"] is True
            assert result["second_uses_sentinel"] is True
            assert result["first_tmp"] is None
            assert result["second_tmp"] is None


class TestSelectionAndPicking:
    def test_selection_highlight_stores_paths(self):
        """``set_selection_highlight`` is a setter — paths stored verbatim."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            adapter = OvRtxRendererAdapter()
            adapter.set_selection_highlight(["/World/Cube", "/World/Sphere"])
            result = {"selected_paths": list(adapter._selected_paths)}
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["selected_paths"] == ["/World/Cube", "/World/Sphere"]

    def test_pick_before_load_is_miss(self):
        """No stage loaded → pick fires callback with (None, None)."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            adapter = OvRtxRendererAdapter()
            pick_results = []
            adapter.pick(0.0, 0.0, lambda p, pos: pick_results.append((p, pos)), "q")
            rect_results = []
            adapter.pick_rect(-1.0, -1.0, 1.0, 1.0, lambda paths: rect_results.append(paths))
            result = {
                "pick_call_count": len(pick_results),
                "pick_result": pick_results[0] if pick_results else None,
                "rect_call_count": len(rect_results),
                "rect_result": rect_results[0] if rect_results else None,
            }
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["pick_call_count"] == 1
        assert result["pick_result"] == [None, None]
        assert result["rect_call_count"] == 1
        assert result["rect_result"] == []

    def test_cancel_pick_before_stage_load_is_harmless(self):
        """Without a stage loaded, ``pick`` early-misses synchronously.

        ``cancel_pick`` targets the async in-flight FIFO. When no stage
        is loaded the adapter never enqueues an ovrtx query and the
        ``pick`` callback fires inline as a miss; calling ``cancel_pick``
        is then a defensible early-miss-only no-op. Async cancellation
        semantics with a real stage are covered by
        ``test_ovrtx_pick_outline_path::test_two_rapid_picks_do_not_inherit_canceled_hit``
        and ``::test_explicit_cancel_pick_drains_without_dispatch``.
        """
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            adapter = OvRtxRendererAdapter()
            adapter.cancel_pick("q1")
            calls = []
            adapter.pick(0.0, 0.0, lambda p, pos: calls.append((p, pos)), "q1")
            adapter.cancel_pick("q1")
            adapter.pick(0.0, 0.0, lambda p, pos: calls.append((p, pos)), "q1")
            result = {
                "call_count": len(calls),
                "all_misses": all(c == (None, None) for c in calls),
                "in_flight": len(adapter._in_flight_pick_queries),
            }
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        # Both picks fire inline as misses; no ovrtx query was enqueued
        # so the FIFO stays empty.
        assert result["call_count"] == 2
        assert result["all_misses"] is True
        assert result["in_flight"] == 0

    def test_pick_rect_on_loaded_stage_captures_multiple_prims(self):
        """A full-frustum marquee captures every visible Gprim on the stage."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            stage = Usd.Stage.Open({_REFERENCE_SCENE!r})
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)
            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            view, proj = cam.get_matrices(640, 480)
            adapter.render_frame(640, 480, view, proj)
            rect_results = []
            adapter.pick_rect(
                -1.0, -1.0, 1.0, 1.0,
                lambda paths: rect_results.append(list(paths)),
            )
            adapter.render_frame(640, 480, view, proj)
            result = {{
                "call_count": len(rect_results),
                "path_count": len(rect_results[0]) if rect_results else 0,
                "first_path": rect_results[0][0] if rect_results and rect_results[0] else None,
            }}
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["call_count"] == 1
        # Full-NDC marquee on a loaded multi-prim scene captures at
        # least one Gprim (sphere + cube + plane).
        assert result["path_count"] >= 1
        assert result["first_path"] is not None

    def test_pick_on_loaded_stage_hits_cube(self):
        """With a stage loaded, a centre-screen NDC pick hits the focused prim."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            stage = Usd.Stage.Open({_REFERENCE_SCENE!r})
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)
            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            # Prime matrices by rendering one frame.
            view, proj = cam.get_matrices(640, 480)
            adapter.render_frame(640, 480, view, proj)
            pick_results = []
            # NDC (0, 0) = screen centre — with the framed camera, the ray
            # hits one of the scene's prims.
            adapter.pick(0.0, 0.0, lambda p, pos: pick_results.append((p, pos)), "q")
            adapter.render_frame(640, 480, view, proj)
            result = {{
                "pick_call_count": len(pick_results),
                "hit_path": pick_results[0][0] if pick_results else None,
                "has_world_point": pick_results[0][1] is not None if pick_results else False,
            }}
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["pick_call_count"] == 1
        # Reference scene has multiple prims at origin — the exact one
        # depends on framing, but *some* path must be hit (not None).
        assert result["hit_path"] is not None
        assert result["hit_path"].startswith("/")
        assert result["has_world_point"] is True

    def test_rapid_same_render_product_pick_delivers_latest_hit(self):
        """Rapid same-name picks must deliver the latest ovrtx 0.3 hit."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            stage = Usd.Stage.Open({_REFERENCE_SCENE!r})
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)
            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            view, proj = cam.get_matrices(640, 480)
            adapter.render_frame(640, 480, view, proj)

            control_results = []
            adapter.pick(
                0.0, 0.0,
                lambda p, pos: control_results.append((p, pos)),
                "control",
            )
            adapter.render_frame(640, 480, view, proj)

            first_results = []
            second_results = []
            adapter.pick(
                0.0, 0.0,
                lambda p, pos: first_results.append((p, pos)),
                "viewport_click",
            )
            adapter.pick(
                0.0, 0.0,
                lambda p, pos: second_results.append((p, pos)),
                "viewport_click",
            )
            adapter.render_frame(640, 480, view, proj)
            after_frame_1 = {{
                "first_results": list(first_results),
                "second_results": list(second_results),
                "in_flight": len(adapter._in_flight_pick_queries),
            }}
            adapter.render_frame(640, 480, view, proj)

            result = {{
                "control_results": control_results,
                "first_results": first_results,
                "second_results": second_results,
                "after_frame_1": after_frame_1,
                "last_pick_path": adapter._last_pick_path,
                "in_flight": len(adapter._in_flight_pick_queries),
            }}
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["control_results"][0][0] == "/World/Sphere"
        assert result["first_results"] == []
        assert result["second_results"] == [["/World/Sphere", [0.0, 0.0, 0.0]]]
        assert result["last_pick_path"] == "/World/Sphere"
        assert result["in_flight"] == 0



class TestShutdown:
    def test_shutdown_on_fresh_adapter_is_clean(self):
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            adapter = OvRtxRendererAdapter()
            adapter.shutdown()
            result = {"renderer_after": adapter._renderer, "stage_after": adapter._stage}
            print("RESULT:" + json.dumps({"ok": True, "renderer_is_none": adapter._renderer is None}))
        """)
        result = _run_in_subprocess(script)
        assert result["ok"]
        assert result["renderer_is_none"] is True

    def test_shutdown_cleans_anonymous_root_resource(self):
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            from pxr import UsdGeom
            from ovui_data_adapters.openusd import renderer_adapter as renderer_mod
            stage = Usd.Stage.CreateInMemory()
            world = UsdGeom.Xform.Define(stage, "/World")
            stage.SetDefaultPrim(world.GetPrim())
            UsdGeom.Cube.Define(stage, "/World/Cube")
            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)
            tmp = adapter._owned_tmp_path
            inline_supported = (
                getattr(adapter._renderer, "open_usd_from_string", None) is not None
            )
            uses_root_sentinel = adapter._usd_handle is renderer_mod._ROOT_STAGE_SENTINEL
            tmp_existed_before = os.path.exists(tmp) if tmp else False
            adapter.shutdown()
            tmp_exists_after = os.path.exists(tmp) if tmp else False
            result = {
                "inline_supported": inline_supported,
                "uses_root_sentinel": uses_root_sentinel,
                "tmp_path": tmp,
                "existed_before": tmp_existed_before,
                "exists_after": tmp_exists_after,
                "owned_tmp_after": adapter._owned_tmp_path,
            }
            print("RESULT:" + json.dumps(result))
        """)
        result = _run_in_subprocess(script)
        if result["inline_supported"]:
            assert result["uses_root_sentinel"] is True
            assert result["tmp_path"] is None
            assert result["existed_before"] is False
        else:
            assert result["tmp_path"], "legacy anonymous stage should produce a temp path"
            assert result["existed_before"] is True
        assert result["exists_after"] is False
        assert result["owned_tmp_after"] is None


class TestRenderWithoutStage:
    def test_no_stage_returns_black_frame(self):
        """``render_frame`` before ``load_stage`` must not crash."""
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent("""
            adapter = OvRtxRendererAdapter()
            frame = adapter.render_frame(100, 100, np.eye(4), np.eye(4))
            result = {
                "shape": list(frame.shape),
                "dtype": str(frame.dtype),
                "max": int(frame.max()),
            }
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        assert result["shape"] == [100, 100, 4]
        assert result["dtype"] == "uint8"
        assert result["max"] == 0


class TestCameraIntrinsicsPushedToOvrtx:
    """Issue #22 regression: per-frame ``write_attribute`` for camera
    intrinsics must reach ovrtx, so the rendered image's effective
    camera matches the projection used by the ``omni.ui.scene`` overlay.
    """

    def test_v_aperture_tracks_widget_aspect(self):
        """``verticalAperture`` written into ovrtx must equal
        ``20.955 / aspect`` where ``aspect = width / height`` of the
        viewport. Verified by rendering at two distinct aspects and
        reading ovrtx's stage debug dump.
        """
        script = _LOAD_ORDER_PREAMBLE + textwrap.dedent(f"""
            stage = Usd.Stage.Open({_REFERENCE_SCENE!r})
            cam = CameraController()
            cam.focus(target=[0, 50, 0], distance=500.0)
            adapter = OvRtxRendererAdapter()
            adapter.load_stage(stage)

            from ovrtx import Device

            def _read_v_aperture_for(camera_path):
                products = adapter._renderer.step(
                    render_products={{"ovrtx_debug_dump_stage"}}, delta_time=0.0
                )
                rv = products["ovrtx_debug_dump_stage"].frames[0].render_vars["debug"]
                with rv.map(device=Device.CPU) as mapping:
                    dump = mapping.tensor.to_bytes().decode("utf-8")
                # The dump nests prim specs under enclosing scopes, e.g.
                # ``def Camera "Main"``. Find the camera with the matching
                # leaf name and read the ``verticalAperture =`` line that
                # belongs to it. ``verticalApertureOffset`` and similar
                # neighbours are skipped via a strict prefix match.
                lines = dump.splitlines()
                # ``camera_path`` ends with the leaf name (e.g. "/Main").
                leaf = camera_path.rsplit("/", 1)[-1]
                in_target = False
                depth = 0
                for line in lines:
                    s = line.strip()
                    if not in_target:
                        if s.startswith(f'def Camera "{{leaf}}"'):
                            in_target = True
                            depth = 0
                        continue
                    if s == "{{":
                        depth += 1
                        continue
                    if s == "}}":
                        depth -= 1
                        if depth <= 0:
                            return None
                        continue
                    # Strict prefix match — "verticalAperture =" only,
                    # not "verticalApertureOffset =".
                    if s.startswith("float verticalAperture ") or s.startswith(
                        "float verticalAperture="
                    ):
                        return float(s.split("=", 1)[1].strip())
                return None

            def _read_v_aperture():
                # Only the OvGearSession camera is the live one. The
                # planet-system scene composes other cameras; we want
                # ours, addressed by adapter._camera_path.
                return _read_v_aperture_for(adapter._camera_path)

            # 16:9 — the bug was visible here before the fix.
            view_169, proj_169 = cam.get_matrices(1280, 720)
            adapter.render_frame(1280, 720, view_169, proj_169)
            v_169 = _read_v_aperture()

            # 1:1 — different aspect, so v_aperture must change.
            view_11, proj_11 = cam.get_matrices(720, 720)
            adapter.render_frame(720, 720, view_11, proj_11)
            v_11 = _read_v_aperture()

            result = {{
                "v_169": v_169,
                "v_11": v_11,
            }}
            print("RESULT:" + json.dumps(result))
            adapter.shutdown()
        """)
        result = _run_in_subprocess(script)
        # 20.955 / (1280/720) = 11.7872; 20.955 / 1.0 = 20.955.
        assert result["v_169"] is not None and result["v_11"] is not None, (
            "verticalAperture missing from ovrtx stage dump"
        )
        assert abs(result["v_169"] - 20.955 / (1280.0 / 720.0)) < 1e-3, result
        assert abs(result["v_11"] - 20.955) < 1e-3, result
        # And — critically — the two values must differ. This is the
        # entire point of the fix: aperture must follow widget aspect
        # rather than staying at the hardcoded 15.2908.
        assert abs(result["v_169"] - result["v_11"]) > 1.0, result
