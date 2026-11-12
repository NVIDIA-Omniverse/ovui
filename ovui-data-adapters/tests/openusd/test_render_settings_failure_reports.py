# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Failures and fallbacks of the render-settings work of the regression are reported.

Each failed operation is reported once with its name and its cause, and each
fallback says which way is in use; the work then goes on as before. These
tests need no GPU: they drive the adapter's own functions with fakes of the
renderer, of ovui's native frame pacing and of the ovrtx library.
"""

from __future__ import annotations

import ctypes
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from ovui_data_adapters.common import ovrtx_carb_settings as carb
from ovui_data_adapters.common.ovrtx_carb_settings import OvrtxCarbSettingsError, read_carb_bool
from ovui_data_adapters.openusd import renderer_adapter as mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

PRODUCT = "/OvGearSession/Render/Viewport"


@pytest.fixture
def reports(monkeypatch, capsys):
    """The lines that the adapter reports, with no earlier report kept."""

    monkeypatch.setattr(mod, "_REPORTED_CASES", {}, raising=False)
    capsys.readouterr()

    def lines():
        return [line for line in capsys.readouterr().err.splitlines() if line.startswith("[OvRtxRendererAdapter]")]

    return lines


def _adapter():
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._render_product_path = PRODUCT
    adapter._frame_pacing_token = 0
    return adapter


# --- The settings-read extension of the renderer -------------------------------------------------


def _fake_ovrtx(monkeypatch, bindings):
    name = "fake_ovrtx_for_reports"
    package = types.ModuleType(name)
    if bindings is not None:
        bindings.__name__ = f"{name}._src.bindings"
        monkeypatch.setitem(sys.modules, f"{name}._src.bindings", bindings)
    else:
        monkeypatch.setitem(sys.modules, f"{name}._src.bindings", None)  # import fails
    return package


def _bindings(lib):
    bindings = types.ModuleType("bindings")
    bindings.ovrtx_result_t = ctypes.c_int
    bindings.ovx_string_t = ctypes.c_char_p
    bindings.OVRTX_API_SUCCESS = 0
    bindings._ovrtx_loader = SimpleNamespace(_lib=lib)
    return bindings


def _lib(query):
    def last_error():
        return b"no error"

    return SimpleNamespace(ovrtx_query_extension=query, ovrtx_get_last_error=last_error)


def test_read_carb_bool_names_why_a_setting_cannot_be_read(monkeypatch):
    key = "/app/hydra/renderSettings/useFabricAttributes"
    with pytest.raises(OvrtxCarbSettingsError, match="does not load"):
        read_carb_bool(_fake_ovrtx(monkeypatch, None), key)
    with pytest.raises(OvrtxCarbSettingsError, match="renderer library .* is not loaded"):
        read_carb_bool(_fake_ovrtx(monkeypatch, _bindings(None)), key)
    no_extension = _lib(lambda name, pointer: SimpleNamespace(status=1))
    with pytest.raises(OvrtxCarbSettingsError, match="has no extension ovrtx.settings.read_settings.v1"):
        read_carb_bool(_fake_ovrtx(monkeypatch, _bindings(no_extension)), key)

    bindings = _bindings(None)
    vtable = carb._read_vtable_type(bindings)(abi_version=2, struct_size=8)

    def query(name, pointer):
        pointer._obj.value = ctypes.addressof(vtable)
        return SimpleNamespace(status=0)

    bindings._ovrtx_loader = SimpleNamespace(_lib=_lib(query))
    with pytest.raises(OvrtxCarbSettingsError, match="ABI version 2"):
        read_carb_bool(_fake_ovrtx(monkeypatch, bindings), key)


def test_the_reset_fallback_of_render_setting_changes_is_reported_with_its_cause(monkeypatch, reports):
    adapter = _adapter()
    adapter._renderer = object()
    monkeypatch.setattr(mod, "_ovrtx", object())

    def no_extension(ovrtx, key):
        raise OvrtxCarbSettingsError("Cannot read: this ovrtx has no extension ovrtx.settings.read_settings.v1.")

    monkeypatch.setattr(mod, "read_carb_bool", no_extension)
    assert adapter._renderer_reads_render_settings_from_fabric() is False
    assert adapter._renderer_reads_render_settings_from_fabric() is False
    lines = reports()
    assert len(lines) == 1, lines
    assert "renderer reset" in lines[0] and "no extension ovrtx.settings.read_settings.v1" in lines[0]

    values = {mod._FABRIC_RENDER_SETTINGS_KEY: None, mod._USD_RENDER_SETTINGS_KEY: None}
    monkeypatch.setattr(mod, "read_carb_bool", lambda ovrtx, key: values[key])
    assert adapter._renderer_reads_render_settings_from_fabric() is False
    lines = reports()
    assert len(lines) == 1 and "useFabricAttributes=not a bool" in lines[0], lines

    values[mod._FABRIC_RENDER_SETTINGS_KEY] = True
    values[mod._USD_RENDER_SETTINGS_KEY] = False
    assert adapter._renderer_reads_render_settings_from_fabric() is True
    assert reports() == []


# --- Native frame pacing ---------------------------------------------------------------------------


class _BrokenStatus:
    def _get_native_frame_pacing_status(self):
        raise RuntimeError("the status table is closed")


def test_a_failed_read_of_the_native_pacing_status_is_reported_once(monkeypatch, reports):
    adapter = _adapter()
    adapter._frame_pacing_token = 3
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: _BrokenStatus()))
    for _ in range(3):
        assert adapter._rendered_frames_marker() is None
        assert adapter._settled_picture_on_screen(False) is None
    lines = reports()
    assert len(lines) == 2, lines
    assert all(
        "reading the native frame pacing status failed: RuntimeError: the status table is closed" in line
        for line in lines
    )
    assert "Eco Mode" in lines[0] and "not stored" in lines[1]


def test_a_status_without_render_idle_is_reported_as_a_fallback(monkeypatch, reports):
    adapter = _adapter()
    adapter._frame_pacing_token = 3
    status = {"session_token": 3, "real_render_completions": 5}
    native = SimpleNamespace(_get_native_frame_pacing_status=lambda: status)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: native))
    assert adapter._settled_picture_on_screen(False) == "partial"
    assert adapter._settled_picture_on_screen(False) == "partial"
    lines = reports()
    assert len(lines) == 1 and "has no render_idle" in lines[0] and "fallback" in lines[0], lines


def test_the_fallback_to_the_resume_that_renders_is_reported(reports):
    calls = []

    def resume(token, **options):
        if options:
            raise TypeError("incompatible function arguments")
        calls.append(token)
        return True

    native = SimpleNamespace(_native_frame_pacing_resume_render=resume)
    adapter = _adapter()
    adapter._frame_pacing_token = 4
    for _ in range(2):
        adapter._frame_pacing_resume_renders = False
        assert adapter._resume_native_render(native) is True
    assert calls == [4, 4]
    lines = reports()
    assert len(lines) == 1, lines
    assert "native resume" in lines[0] and "incompatible function arguments" in lines[0]
    assert "the fallback is the resume that renders" in lines[0]


# --- Stored pictures -------------------------------------------------------------------------------


class _Mapping:
    def __enter__(self):
        raise RuntimeError("map failed: device lost")

    def __exit__(self, *exc):
        return False


def test_a_failed_copy_of_a_picture_is_reported(monkeypatch, reports):
    adapter = _adapter()
    var = SimpleNamespace(map=lambda device=None: _Mapping())
    products = {PRODUCT: SimpleNamespace(frames=[SimpleNamespace(render_vars={"LdrColor": var})])}
    monkeypatch.setattr(OvRtxRendererAdapter, "_step_renderer", lambda self: products)
    monkeypatch.setattr(mod, "_ovrtx", SimpleNamespace(Device=SimpleNamespace(CPU="cpu")))
    assert adapter._step_cpu_picture(8, 4) is None
    assert adapter._step_cpu_picture(8, 4) is None
    lines = reports()
    assert len(lines) == 1, lines
    assert f"copying the picture of the render product {PRODUCT!r} to the CPU failed" in lines[0]
    assert "RuntimeError: map failed: device lost" in lines[0]


def test_a_failed_camera_write_stops_the_step_and_stores_no_picture(monkeypatch, reports):
    adapter = _adapter()
    steps = []

    class _Renderer:
        def write_attribute(self, **kwargs):
            raise RuntimeError("the camera prim is gone")

    adapter._renderer = _Renderer()
    adapter._renderer_setting_values = {}
    adapter.set_render_policy("on_change", 2)
    monkeypatch.setattr(OvRtxRendererAdapter, "_step_renderer", lambda self: steps.append("step") or {})
    monkeypatch.setattr(mod, "_ovrtx", SimpleNamespace(Semantic=SimpleNamespace(XFORM_MAT4x4="xform")))
    for name in ("_apply_camera_projection", "_apply_resolution_if_allowed"):
        monkeypatch.setattr(OvRtxRendererAdapter, name, lambda self, value: None)
    monkeypatch.setattr(OvRtxRendererAdapter, "_runtime_camera_path", lambda self: "/OvGearSession/Camera")
    monkeypatch.setattr(OvRtxRendererAdapter, "_runtime_camera_xform", lambda self, world, path: world)
    scene = ("scene",)
    settings = adapter._render_settings_state(waiting=False)
    for _ in range(4):
        assert adapter._advance_settled_job(scene, settings, 8, 4, np.eye(4), np.eye(4)) is None
    assert steps == [], "a step ran with a camera that the renderer may not have"
    assert len(adapter._settled_pictures_store()) == 0
    lines = reports()
    assert len(lines) == 1, lines
    assert "writing the camera /OvGearSession/Camera for a step that is not shown failed" in lines[0]
    assert "RuntimeError: the camera prim is gone" in lines[0]


def test_a_picture_larger_than_the_store_is_reported(monkeypatch, reports):
    monkeypatch.setattr(mod, "_SETTLED_PICTURES_MAX_BYTES", 100)
    adapter = _adapter()
    adapter._last_resolution = (8, 4)
    adapter._still_frame_output = np.zeros((4, 8, 4), dtype=np.uint8)
    adapter._store_settled_picture(("scene",), ("state",), 8, 4)
    assert len(adapter._settled_pictures_store()) == 0
    lines = reports()
    assert len(lines) == 1 and "a picture of 8x4" in lines[0] and "fallback" in lines[0], lines


def test_a_gpu_frame_that_cannot_be_stored_is_reported(reports):
    adapter = _adapter()
    adapter._still_frame_output = SimpleNamespace(width=8, height=4)
    assert adapter._settled_picture_on_screen(True) is None
    lines = reports()
    assert len(lines) == 1 and "is a GPU frame" in lines[0] and "fallback" in lines[0], lines


def test_a_failed_surface_query_on_a_stored_picture_is_reported(monkeypatch, reports):
    adapter = _adapter()

    class _Renderer:
        def write_attribute(self, **kwargs):
            pass

        def enqueue_pick_query(self, product, *rect):
            raise RuntimeError("pick queue is full")

    adapter._renderer = _Renderer()
    adapter._settled_hold = ((8, 4, np.eye(4).tobytes(), np.eye(4).tobytes()), (), None)
    native = SimpleNamespace(_native_frame_pacing_query_surface=lambda *rect: 1)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: native))
    monkeypatch.setattr(OvRtxRendererAdapter, "_write_settled_job_camera", lambda self, *args: True)
    monkeypatch.setattr(OvRtxRendererAdapter, "_ndc_rect_to_pick_pixels", lambda self, *ndc: (1, 1, 2, 2))
    monkeypatch.setattr(OvRtxRendererAdapter, "_pick_pixels_to_query_rect", lambda self, *px: px)
    number = adapter.query_surface(0.1, 0.1)
    assert number != 0 and adapter.surface_hit() == (number, None)
    lines = reports()
    assert len(lines) == 1, lines
    assert "asking the renderer for the surface under the cursor failed: RuntimeError: pick queue is full" in lines[0]
    assert "the point at the target's depth" in lines[0]


def test_a_surface_hit_with_no_position_is_ray_cast_and_reported(monkeypatch, reports):
    adapter = _adapter()

    class _Renderer:
        def enqueue_pick_query(self, product, *rect, flags=0):
            pass

    adapter._renderer = _Renderer()
    adapter._stage = object()
    adapter._settled_hold = ((8, 4, np.eye(4).tobytes(), np.eye(4).tobytes()), (), None)
    native = SimpleNamespace(_native_frame_pacing_query_surface=lambda *rect: 1)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: native))
    monkeypatch.setattr(OvRtxRendererAdapter, "_write_settled_job_camera", lambda self, *args: True)
    monkeypatch.setattr(OvRtxRendererAdapter, "_ndc_rect_to_pick_pixels", lambda self, *ndc: (1, 1, 2, 2))
    monkeypatch.setattr(OvRtxRendererAdapter, "_pick_pixels_to_query_rect", lambda self, *px: px)
    monkeypatch.setattr(OvRtxRendererAdapter, "_step_renderer", lambda self: {PRODUCT: None})
    monkeypatch.setattr(
        OvRtxRendererAdapter, "_read_pick_hits", lambda self, products, product_path=None: [("/World/Floor", None)]
    )
    monkeypatch.setattr(mod, "_pick_surface_point", lambda stage, path, view, projection, x, y: (1.0, 2.0, 3.0))
    number = adapter.query_surface(0.1, 0.1)
    assert number != 0 and adapter.surface_hit() == (number, (1.0, 2.0, 3.0))
    lines = reports()
    assert len(lines) == 1, lines
    assert "gave no position for the surface /World/Floor" in lines[0] and "ray cast" in lines[0]


# --- Values of render settings ----------------------------------------------------------------------


def test_values_that_cannot_be_compared_are_reported(reports):
    descriptor = SimpleNamespace(
        setting_id=f"{PRODUCT}:omni:rtx:post:lensFlares:cutoffPoint",
        value_state=SimpleNamespace(current_value=[1.0, [2.0, 3.0]]),
    )
    assert mod._render_setting_value_unchanged(descriptor, [1.0, [2.0, 3.0]]) is False
    lines = reports()
    assert len(lines) == 1, lines
    assert "comparing the value of the render setting" in lines[0] and "cutoffPoint" in lines[0]
    assert "ValueError" in lines[0] and "counts as a new value" in lines[0]


def test_unknown_eco_mode_values_are_reported(monkeypatch, reports):
    adapter = _adapter()
    monkeypatch.setattr(OvRtxRendererAdapter, "read_render_setting_value", lambda self, attr, render_product_path=None: None)
    assert adapter._eco_mode_state(PRODUCT, mod._ECO_MODE_ENABLED_ATTR, True) is None
    monkeypatch.setattr(mod, "_render_setting_builtin_spec", lambda attr: {})
    assert OvRtxRendererAdapter._eco_mode_final_frames() is None
    lines = reports()
    assert len(lines) == 2, lines
    assert "Eco Mode values of the render product" in lines[0] and "fallback is a new picture" in lines[0]
    assert "declares no default" in lines[1] and "fallback" in lines[1]
