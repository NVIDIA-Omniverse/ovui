# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The OpenUSD renderer adapter reports a failed step and stops its log reader at shutdown."""

from __future__ import annotations

import time
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from ovui_data_adapters.common import render_diagnostics as rd
from ovui_data_adapters.common import render_native_log as nl
from ovui_data_adapters.common import render_probe as probe
from ovui_data_adapters.common._ldr_overlap import LdrOverlapState
from ovui_data_adapters.openusd import renderer_adapter as mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

W, H = 64, 36
PRODUCT = "/Products/front"


class _FailingRenderer:
    def __init__(self, error):
        self.error = error

    def step(self, render_products, delta_time):
        raise self.error

    def write_attribute(self, *args, **kwargs):
        return None


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    yield
    assert nl.native_log_paths() == []  # every test released its reader
    assert rd.shutdown_background_tasks(5.0) == []


def _adapter(monkeypatch, renderer):
    monkeypatch.setattr(mod, "_ovrtx", SimpleNamespace(Device=SimpleNamespace(CPU="cpu", CUDA="cuda"),
                                                       Semantic=SimpleNamespace(XFORM_MAT4x4="xform")))
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: None))
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._renderer = renderer
    adapter._stage = object()
    adapter._usd_handle = object()
    adapter._default_render_product_path = mod._RENDER_PRODUCT_PATH
    adapter._default_camera_path = mod._CAMERA_PATH
    adapter._render_product_path = PRODUCT
    adapter._camera_path = "/Cameras/front"
    adapter._last_resolution = (W, H)
    adapter._zero_copy_state = None
    adapter._ldr_overlap = LdrOverlapState()
    adapter._in_flight_pick_queries = deque()
    adapter._dt_clock = time.monotonic()
    adapter._file_check_due = False
    adapter._live_check_due = False
    adapter._material_check_requests = probe.MaterialCheckRequests()
    return adapter


def _frame(adapter):
    view = np.eye(4)
    proj = np.array([[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]])
    return adapter.render_frame(W, H, view, proj)


def test_a_failed_step_is_recorded_with_its_cause_and_the_frame_is_black(monkeypatch):
    adapter = _adapter(monkeypatch, _FailingRenderer(RuntimeError("rtx step failed")))
    image = _frame(adapter)
    assert image is not None and not image.any()  # the viewer shows black ...
    (event,) = rd.get_render_diagnostics().events()  # ... and now says why
    assert (event["kind"], event["scope"]) == ("step", "scene")
    assert "Renderer.step failed: RuntimeError: rtx step failed" in event["message"]


def test_a_step_that_fails_for_memory_names_the_file_and_not_a_made_up_material(monkeypatch, tmp_path):
    log = tmp_path / "ovrtx.log"
    log.write_text("2026-10-24T16:00:00Z [1ms] [Info] [omni.rtx.materials] [UsdToMdl] Prim '/World/Looks/blue/OpenPBR' parameter 'p': ok: 'x'\n")
    owner = SimpleNamespace()
    nl.start_native_log(owner, SimpleNamespace(log_file_path=str(log)))
    try:
        nl._TAILS[str(log)][0].poll()
        adapter = _adapter(monkeypatch, _FailingRenderer(MemoryError("Failed to allocate texture /data/PotatoRed.png")))
        _frame(adapter)
    finally:
        nl.release_native_log(owner)
    (event,) = rd.get_render_diagnostics().events()
    assert event["kind"] == "memory" and event["resource"] == "/data/PotatoRed.png"
    assert event["material"] == rd.SCENE  # the material is not known; nothing is made up


def test_a_step_failure_with_no_name_is_scene_wide_and_keeps_the_log_hint(monkeypatch, tmp_path):
    log = tmp_path / "ovrtx.log"
    log.write_text(
        "2026-10-24T16:00:00Z [1ms] [Info] [omni.rtx.materials] [UsdToMdl] Prim '/World/Looks/blue/OpenPBR' parameter 'p': ok: 'x'\n")
    owner = SimpleNamespace()
    nl.start_native_log(owner, SimpleNamespace(log_file_path=str(log)))
    try:
        nl._TAILS[str(log)][0].poll()
        _frame(_adapter(monkeypatch, _FailingRenderer(RuntimeError("device lost"))))
    finally:
        nl.release_native_log(owner)
    (event,) = [e for e in rd.get_render_diagnostics().events() if e["kind"] == "step"]
    assert (event["scope"], event["context"]) == ("scene", "/World/Looks/blue/OpenPBR")


def test_shutdown_stops_the_log_reader_after_a_last_read(monkeypatch, tmp_path):
    log = tmp_path / "ovrtx.log"
    log.write_text("")
    config = SimpleNamespace(log_file_path=str(log))
    adapter = _adapter(monkeypatch, SimpleNamespace(destroy=lambda: None))
    nl.start_native_log(adapter, config)
    tail = nl._TAILS[str(log)][0]
    log.write_text("2026-10-24T16:00:00Z [1ms] [Error] [omni.rtx] Failed load texture file:/data/PotatoRed.png. UJITSO request failed\n")
    assert tail._task.alive
    # Release exactly as shutdown does once the renderer is gone.
    nl.release_native_log(adapter)
    assert not tail._task.alive and nl.native_log_paths() == [] and adapter._native_log_path is None
    assert [e["resource"] for e in rd.get_render_diagnostics().events()] == ["file:/data/PotatoRed.png"]


class _EmptyStepRenderer(_FailingRenderer):
    """The renderer ran out of device memory: the step returns, but without the LdrColor image."""

    def __init__(self, products):
        self.products = products

    def step(self, render_products, delta_time):
        return self.products


@pytest.mark.parametrize("products,reason", [
    ({}, "no output for product /Products/front"),
    ({PRODUCT: SimpleNamespace(frames=[])}, "has no frame"),
    ({PRODUCT: SimpleNamespace(frames=[SimpleNamespace(render_vars={})])}, "has no LdrColor"),
])
def test_a_step_that_returns_no_image_is_reported_and_the_frame_is_black(monkeypatch, products, reason):
    image = _frame(_adapter(monkeypatch, _EmptyStepRenderer(products)))
    assert image is not None and not image.any()
    (event,) = rd.get_render_diagnostics().events()
    assert (event["kind"], event["scope"]) == ("step", "scene")
    assert "the renderer returned no image" in event["message"] and reason in event["message"]
    assert "native renderer log" in event["message"]


# -- the live material check ---------------------------------------------------------------

import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402


GENERATOR = Path(__file__).resolve().parents[1] / "data" / "make_material_regression_scene.py"
RUNNER = "/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner"
GREENS = "/World/Kitchen/Looks/Greens"


class _Mapped(np.ndarray):
    def unmap(self):
        self.unmapped = True


class _LiveRenderer:
    """Records the native calls of the check; draws every real cube like its reference, except those in ``wrong``."""

    def __init__(self, wrong=(), fail_step=False):
        self.calls, self.wrong, self.fail_step, self.layer = [], set(wrong), fail_step, None

    def add_usd_reference_from_string(self, text, prefix):
        self.calls.append(("add", prefix))
        self.layer = text
        return "handle"

    def remove_usd(self, handle):
        self.calls.append(("remove", handle))

    def clone_usd(self, source, targets):
        self.calls.append(("clone", source, tuple(targets)))

    def write_attribute(self, prim_paths=None, attribute_name=None, tensor=None, semantic=None):
        if attribute_name == "omni:xform" and prim_paths and prim_paths[0].startswith("/OvuiProbe/Clone_"):
            self.calls.append(("xform", prim_paths[0], tuple(tensor.shape)))

    def step(self, render_products, delta_time):
        (product,) = render_products
        self.calls.append(("step", product))
        if self.fail_step:
            raise RuntimeError("step failed")
        image = np.full((probe.HEIGHT, probe.WIDTH, 4), 120, dtype=np.uint8)
        for index in self.wrong:
            rx, ry, _fx, _fy = probe._pixel(index)
            half = int(0.5 * probe._PER_UNIT) + 3
            image[ry - half:ry + half, rx - half:rx + half, :3] = (230, 90, 90)
        depth = np.full((probe.HEIGHT, probe.WIDTH, 1), 5.0, dtype=np.float32).view(_Mapped)  # everything is covered
        variables = {
            "/OvuiProbe/Render_0/LdrColor": SimpleNamespace(map=lambda device=None: image.view(_Mapped)),
            "/OvuiProbe/Render_0/DistanceToImagePlaneSD": SimpleNamespace(map=lambda device=None: depth),
        }
        return {product: SimpleNamespace(frames=[SimpleNamespace(render_vars=variables)])}

@pytest.fixture
def live(monkeypatch, tmp_path):
    from pxr import Usd

    subprocess.run([sys.executable, str(GENERATOR), str(tmp_path)], check=True, capture_output=True)
    scene = str(tmp_path / "kitchen.usda")
    monkeypatch.setattr(mod, "_ovrtx", SimpleNamespace(Device=SimpleNamespace(CPU="cpu", CUDA="cuda"),
                                                       Semantic=SimpleNamespace(XFORM_MAT4x4="xform")))

    def make(renderer, stage=None):
        adapter = _adapter(monkeypatch, renderer)
        adapter._stage = stage if stage is not None else Usd.Stage.Open(scene)
        return adapter

    make.scene = scene
    return make


def test_the_live_check_adds_the_cubes_to_the_applications_renderer_and_removes_them(live):
    renderer = _LiveRenderer()
    adapter = live(renderer)
    result = adapter.verify_materials_live()
    kinds = [c[0] for c in renderer.calls]
    assert kinds[0] == "add" and kinds[-1] == "remove" and kinds.count("step") == 4  # 1 product, 4 steps
    assert renderer.calls[0] == ("add", probe.LIVE_PREFIX) and renderer.calls[-1] == ("remove", "handle")
    # each material is drawn on a copy of ITS ORIGINAL geometry, which keeps the original binding
    clones = {c[1]: c[2] for c in renderer.calls if c[0] == "clone"}
    assert set(clones) == {f"/World/Kitchen/{n}_geo" for n in ("Whitewash", "PotatoRed", "Greens", "Blues", "Runner")}
    assert all(len(t) == 1 and t[0].startswith("/OvuiProbe/Clone_") for t in clones.values())
    assert [c[2] for c in renderer.calls if c[0] == "xform"] == [(1, 4, 4)] * 5
    assert kinds.index("add") < kinds.index("clone") < kinds.index("step")
    assert {i["state"] for i in result["materials"].values()} == {"ok"} and result["failures"] == []
    assert rd.get_verification()[RUNNER]["state"] == "ok"
    assert "/OvuiProbe/Render_0" in {c[1] for c in renderer.calls if c[0] == "step"}


def test_the_live_check_finds_a_material_that_is_shown_wrong(live):
    renderer = _LiveRenderer(wrong=[1])  # the real cube of the second material
    result = live(renderer).verify_materials_live()
    assert len(result["mismatches"]) == 1 and "shown wrong" in result["failures"][0]
    (event,) = [e for e in rd.get_render_diagnostics().events() if e["kind"] == "mismatch"]
    assert event["material"] == result["mismatches"][0] and event["scope"] == "material"


def test_the_live_check_removes_its_layer_when_a_step_fails(live):
    renderer = _LiveRenderer(fail_step=True)
    with pytest.raises(RuntimeError, match="step failed"):
        live(renderer).verify_materials_live()
    assert renderer.calls[-1] == ("remove", "handle")


def test_a_wrong_scene_is_loud_and_strict_mode_refuses_it(live, monkeypatch, caplog):
    renderer = _LiveRenderer(wrong=[1])
    adapter = live(renderer)
    monkeypatch.setenv(probe.VERIFY_ENV, "1")
    adapter._live_check_due = True
    with caplog.at_level("ERROR", logger="ovui.render_diagnostics"):
        adapter._after_first_frames()
    assert "The renderer shows this scene wrong" in caplog.text
    rd.set_verification({})
    monkeypatch.setenv(probe.VERIFY_ENV, "strict")
    refused = live(_LiveRenderer(wrong=[1]))
    refused._live_check_due = True
    with pytest.raises(probe.MaterialMismatchError, match="shows this scene wrong"):
        refused._after_first_frames()
    # a host that catches the error of one frame (USD Workbench does) gets it at every frame
    for _ in range(3):
        with pytest.raises(probe.MaterialMismatchError, match="CrimsonRunner|Greens|Blues|Whitewash|PotatoRed"):
            _frame(refused)


def test_a_check_that_cannot_run_is_reported_and_only_strict_mode_raises(live, monkeypatch, caplog):
    monkeypatch.setenv(probe.VERIFY_ENV, "1")
    adapter = live(_LiveRenderer(fail_step=True))
    adapter._live_check_due = True
    with caplog.at_level("ERROR", logger="ovui.render_diagnostics"):
        adapter._after_first_frames()
    assert "the material check could not run: RuntimeError: step failed" in caplog.text
    (event,) = [e for e in rd.get_render_diagnostics().events() if e["scope"] == "scene"]
    assert event["kind"] == "unverified"  # a check that could not run is a failure of the scene
    monkeypatch.setenv(probe.VERIFY_ENV, "strict")
    strict = live(_LiveRenderer(fail_step=True))
    strict._live_check_due = True
    with pytest.raises(RuntimeError, match="step failed"):
        strict._after_first_frames()


def test_after_the_first_step_render_frame_checks_the_files_and_draws_no_check_unless_asked(live, monkeypatch):
    monkeypatch.delenv(probe.VERIFY_ENV, raising=False)
    renderer = _LiveRenderer()
    adapter = live(renderer)
    files = []
    monkeypatch.setattr(mod, "record_file_events", lambda found: files.append(len(found)))
    adapter._file_check_due, adapter._live_check_due, adapter._first_step_done = True, False, False
    _frame(adapter)  # the first frame: nothing yet (the scene is not compiled)
    assert files == [] and "add" not in [c[0] for c in renderer.calls]
    adapter._first_step_done = True
    _frame(adapter)
    _frame(adapter)
    assert len(files) == 1 and adapter._file_check_due is False
    assert "add" not in [c[0] for c in renderer.calls]  # no extra frames of the material check by default
    monkeypatch.setenv(probe.VERIFY_ENV, "1")
    adapter._live_check_due = True
    _frame(adapter)
    _frame(adapter)
    assert [c[0] for c in renderer.calls].count("add") == 1 and adapter._live_check_due is False


def test_material_verify_runs_at_the_next_frame_and_checks_the_unsaved_scene_as_shown(live, monkeypatch, tmp_path):
    """The command asks the adapter; the check runs at its next frame, in this renderer, with the edited stage."""

    import subprocess as sp

    from pxr import Gf, Usd, UsdShade

    sp.run([sys.executable, str(GENERATOR), str(tmp_path / "flat"), "--break", "flat-colors"], check=True,
           capture_output=True)
    stage = Usd.Stage.Open(str(tmp_path / "flat" / "kitchen.usda"))
    UsdShade.Shader.Get(stage, GREENS + "/OpenPBR").GetInput("base_color").Set(Gf.Vec3f(0.9, 0.1, 0.7))  # not saved
    assert stage.GetRootLayer().dirty
    renderer = _LiveRenderer()
    adapter = live(renderer, stage)
    pending = adapter.request_material_check(GREENS, 10)
    assert not pending.done() and renderer.calls == []  # nothing runs outside a frame
    _frame(adapter)
    result = pending.result(timeout=0)
    assert set(result["materials"]) == {GREENS} and result["stage_dirty"] is True
    # The reference has the edited colour, not the colour of the file on disk (0.157, 0.745, 0.235).
    reference = Usd.Stage.CreateInMemory()
    reference.GetRootLayer().ImportFromString(renderer.layer)
    assert reference.GetPrimAtPath("/P/RefLook_0/Surface").GetAttribute("inputs:base_color").Get() == pytest.approx(
        Gf.Vec3f(0.9, 0.1, 0.7))
    cancelled = adapter.request_material_check()
    cancelled.cancel()
    calls = len(renderer.calls)
    _frame(adapter)
    assert len([c for c in renderer.calls[calls:] if c[0] == "add"]) == 0  # a cancelled request does not run


class _NativePacing:
    """The Python bindings of a running native frame pacing session (RTX Tools): the native worker draws the
    viewport, so ``render_frame`` only publishes the camera and no frame comes to the Python step."""

    def __init__(self, log):
        self.log = log

    def _get_present_rate(self):
        return -1.0

    def _get_native_frame_pacing_status(self):
        return {}

    def _native_frame_pacing_start(self, *args):
        raise AssertionError("this test does not restart the session")

    def _native_frame_pacing_publish(self, token, *args):
        self.log.append(("publish", token))
        return True

    def _native_frame_pacing_pause_render(self, token):
        self.log.append(("pause", token))
        return True

    def _native_frame_pacing_resume_render(self, token):
        self.log.append(("resume", token))
        return True

    def _native_frame_pacing_stop(self, token):
        self.log.append(("stop", token))
        return True


class _ViewportAndCheckRenderer(_LiveRenderer):
    """The live check renderer that also draws the viewport product, as the synchronous frame after a check does."""

    def step(self, render_products, delta_time):
        (product,) = render_products
        if product.startswith(probe.LIVE_PREFIX):
            return super().step(render_products, delta_time)
        self.calls.append(("step", product))
        image = np.full((H, W, 4), 90, dtype=np.uint8).view(_Mapped)
        return {product: SimpleNamespace(frames=[SimpleNamespace(
            render_vars={"LdrColor": SimpleNamespace(map=lambda device=None: image)})])}


def test_material_verify_runs_at_the_next_frame_while_native_frame_pacing_draws_the_viewport(live, monkeypatch):
    """Defect: with RTX Tools installed the check never ran and material_verify timed out after 300 s.

    Native frame pacing draws the viewport, so ``render_frame`` returns after it publishes the camera and no frame
    comes to the Python step, where the requests were run. The request must run at the next frame, after the native
    session is drained (no Python renderer call while the native worker owns the renderer). A request whose caller
    stopped waiting leaves the queue at once, without waiting for a frame.
    """

    renderer = _ViewportAndCheckRenderer()
    adapter = live(renderer)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: _NativePacing(renderer.calls)))
    proj = np.array([[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]])
    adapter._ldr_overlap = None
    adapter._livestream = None
    adapter._point_cloud_requests = {}
    adapter._render_var_output_requests = {}
    adapter._frame_pacing_provider = object()
    adapter._frame_pacing_token = 1  # a running native session owns the viewport
    adapter._frame_pacing_needs_sync_step = False
    adapter._frame_pacing_render_paused = False
    adapter._frame_pacing_size = (W, H)
    adapter._frame_pacing_projection = proj.copy()
    adapter._frame_pacing_camera_path = adapter._runtime_camera_path()
    adapter._frame_pacing_last_raw_world = None
    adapter._frame_pacing_last_intent_time = 0.0
    adapter._frame_pacing_restore_overlap = False
    adapter._frame_pacing_pick_snapshot = None
    adapter._frame_pacing_presented_snapshot = None
    adapter._frame_pacing_pick_generated = False
    adapter._frame_pacing_pick_association_unavailable = False
    assert _frame(adapter) is None and renderer.calls == [("publish", 1)]  # native pacing: no Python renderer call

    cancelled = adapter.request_material_check()
    cancelled.cancel()
    assert len(adapter._material_check_requests) == 0  # it does not wait for a frame to leave the queue

    pending = adapter.request_material_check(GREENS, 10)
    _frame(adapter)
    result = pending.result(timeout=0)
    assert set(result["materials"]) == {GREENS} and result["materials"][GREENS]["state"] == "ok"
    kinds = [call[0] for call in renderer.calls]
    assert kinds.count("add") == 1 and kinds.index("stop") < kinds.index("add")  # drained first
    assert ("publish", 1) not in renderer.calls[kinds.index("stop"):]  # the stopped session gets no camera
    assert adapter._frame_pacing_token == 0 and len(adapter._material_check_requests) == 0


def test_a_scene_with_nothing_checkable_is_reported_as_unverified_not_as_right(monkeypatch, caplog):
    from pxr import Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    material = UsdShade.Material.Define(stage, "/World/Looks/Runner")
    shader = UsdShade.Shader.Define(stage, "/World/Looks/Runner/mdl")
    shader.SetSourceAsset(Sdf.AssetPath("./runner.mdl"), "mdl")  # module defaults: no authored colour
    material.CreateSurfaceOutput("mdl").ConnectToSource(shader.CreateOutput("out", Sdf.ValueTypeNames.Token))
    renderer = _LiveRenderer()
    adapter = _adapter(monkeypatch, renderer)
    adapter._stage = stage
    monkeypatch.setenv(probe.VERIFY_ENV, "1")
    adapter._live_check_due = True
    with caplog.at_level("WARNING", logger="ovui.render_diagnostics"):
        adapter._after_first_frames()
    assert renderer.calls == []  # nothing to draw: the renderer is not touched
    assert rd.get_verification()["/World/Looks/Runner"]["state"] == "unverifiable"
    (event,) = rd.get_render_diagnostics().events()
    assert (event["material"], event["kind"]) == ("/World/Looks/Runner", "unverified")
    assert "1 material(s) could not be checked and are not known to be right" in caplog.text
    from ovui_data_adapters.common.render_diagnostics_service import inspector_status

    status = inspector_status()
    # Not hidden: named and counted. It is not evidence of a wrong render, so health is not degraded by it
    # (on Factory 467 of the first 500 materials cannot be checked; a health that is always degraded hides failures).
    assert status["materials_unverified"] == ["/World/Looks/Runner"] and status["materials_unverified_count"] == 1
    assert status["materials_shown_wrong"] == [] and status["material_check"] == {"unverifiable": 1}
    assert status["degraded"] is False and status["failure_events"] == 0
    # A failure that the renderer reports does degrade it.
    rd.get_render_diagnostics().record("/World/Looks/Runner", "./runner.mdl", "mdl", "C100 '}' expected")
    status = inspector_status()
    assert status["degraded"] is True and status["failure_kinds"] == {"mdl": 1}


def test_a_renderer_without_clone_usd_fails_with_the_name_of_the_missing_api(live):
    renderer = _LiveRenderer()
    del _LiveRenderer.clone_usd
    try:
        with pytest.raises(RuntimeError, match="no Renderer.clone_usd"):
            live(renderer).verify_materials_live()
    finally:
        _LiveRenderer.clone_usd = lambda self, source, targets: self.calls.append(("clone", source, tuple(targets)))


def test_the_automatic_check_records_every_missing_file_with_its_material(monkeypatch, tmp_path):
    from pxr import Sdf, Usd, UsdShade

    stage = Usd.Stage.CreateInMemory()
    material = UsdShade.Material.Define(stage, "/World/Looks/Fence")
    shader = UsdShade.Shader.Define(stage, "/World/Looks/Fence/Shader")
    shader.SetSourceAsset(Sdf.AssetPath("OmniPBR.mdl"), "mdl")  # a module name: found by the renderer's search path
    shader.CreateInput("diffuse_texture", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(tmp_path / "gone.png")))
    material.CreateSurfaceOutput("mdl").ConnectToSource(shader.CreateOutput("out", Sdf.ValueTypeNames.Token))
    adapter = _adapter(monkeypatch, _LiveRenderer())
    adapter._stage = stage
    monkeypatch.delenv(probe.VERIFY_ENV, raising=False)  # the file check runs by default
    adapter._file_check_due = True
    adapter._after_first_frames()
    missing = [e for e in rd.get_render_diagnostics().events() if e["kind"] == "texture"]
    assert [(e["material"], e["resource"]) for e in missing] == [("/World/Looks/Fence", str(tmp_path / "gone.png"))]
    from ovui_data_adapters.common.render_diagnostics_service import inspector_status

    assert inspector_status()["degraded"] is True


def test_the_report_of_the_adapter_describes_the_stage_that_it_loaded(live):
    """A host whose application has no stage attribute (only its renderer) gets the report from the adapter."""

    report = live(_LiveRenderer()).describe_materials(GREENS, 10)
    assert [m["path"] for m in report["materials"]] == [GREENS] and report["total"] == 1


def test_the_files_of_the_shaders_are_read_while_the_first_step_runs_and_cost_no_frame(live, monkeypatch):
    """The scan of the shader files (Factory: 0.3 s) runs in a thread while the renderer compiles the scene in its
    first step, so no later frame waits for it."""

    import threading

    scanned = threading.Event()
    calls = []

    def scan(stage):
        calls.append(threading.current_thread().name)
        scanned.set()
        return [{"material": "/M", "uri": "./a.png", "resolved": "", "kind": "texture", "missing": "unresolved"}]

    class _CompilingRenderer(_LiveRenderer):
        def step(self, render_products, delta_time):
            # The first step: the scan runs meanwhile, in its own thread.
            assert scanned.wait(5.0), "the scan did not run during the step"
            return super().step(render_products, delta_time)

    monkeypatch.setattr(mod, "shader_files", scan)
    monkeypatch.delenv(probe.VERIFY_ENV, raising=False)
    adapter = live(_CompilingRenderer())
    adapter._file_check_due, adapter._first_step_done = True, False
    _frame(adapter)
    _frame(adapter)
    assert calls == ["ovui-shader-file-scan"]  # once, not on the main thread
    assert [(e["material"], e["kind"]) for e in rd.get_render_diagnostics().events() if e["kind"] == "texture"] == [
        ("/M", "texture")]
