# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Application renderer construction — ovrtx-only.

OvGear uses ovrtx and only ovrtx. There is no renderer selection, no
fallback, no CLI flag. ``_build_renderer_for_stage`` either returns an
:class:`OvRtxRendererAdapter` or ``None`` when ovrtx is unavailable.
"""

from __future__ import annotations

import os
import types
from unittest.mock import MagicMock

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus


@pytest.fixture
def app():
    """Fresh Application with singleton cleanup."""
    os.environ.pop("OVWIDGETS_REQUIRE_OVRTX", None)
    Application._instance = None
    SelectionBus._instance = None
    application = Application()
    try:
        yield application
    finally:
        os.environ.pop("OVWIDGETS_REQUIRE_OVRTX", None)
        application.shutdown()
        Application._instance = None
        SelectionBus._instance = None


class _FakeOvRtxAdapter:
    """Stand-in for ``OvRtxRendererAdapter`` used by the dispatch tests."""

    instances: list = []

    def __init__(self, *args, **kwargs) -> None:
        self.loaded_stage = None
        self.shutdown_called = False
        _FakeOvRtxAdapter.instances.append(self)

    def load_stage(self, stage) -> None:
        self.loaded_stage = stage

    def shutdown(self) -> None:
        self.shutdown_called = True


class _FailingOvRtxAdapter:
    """``OvRtxRendererAdapter`` stand-in whose ``load_stage`` raises."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def load_stage(self, stage) -> None:
        raise RuntimeError("simulated GPU init failure")

    def shutdown(self) -> None:
        pass


@pytest.fixture
def patched_ovrtx(monkeypatch):
    """Patch the ovrtx adapter module with a success-by-default fake."""
    from ovui_data_adapters.openusd import renderer_adapter as real_mod

    ns = types.SimpleNamespace(adapter_cls=_FakeOvRtxAdapter, available=True)
    _FakeOvRtxAdapter.instances = []

    class _AvailableProxy:
        def __bool__(self) -> bool:
            return ns.available

    monkeypatch.setattr(real_mod, "AVAILABLE", _AvailableProxy())
    monkeypatch.setattr(real_mod, "OvRtxRendererAdapter", ns.adapter_cls)

    def _set_adapter_cls(cls) -> None:
        ns.adapter_cls = cls
        monkeypatch.setattr(real_mod, "OvRtxRendererAdapter", cls)

    ns.set_adapter_cls = _set_adapter_cls
    return ns


@pytest.fixture
def stub_stage():
    stage = MagicMock()
    stage.Traverse.return_value = []
    return stage


class TestOvrtxConstruction:
    def test_available_returns_ovrtx(self, app, patched_ovrtx, stub_stage):
        patched_ovrtx.available = True

        renderer = app._build_renderer_for_stage(stub_stage)

        assert isinstance(renderer, _FakeOvRtxAdapter)
        assert renderer.loaded_stage is stub_stage
        assert len(_FakeOvRtxAdapter.instances) == 1

    def test_unavailable_returns_none_and_warns(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = False

        warnings: list = []
        from ovwidgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda msg, duration_ms=4000: warnings.append(msg),
        )

        renderer = app._build_renderer_for_stage(stub_stage)

        assert renderer is None
        assert _FakeOvRtxAdapter.instances == []
        assert len(warnings) == 1
        assert "ovrtx" in warnings[0].lower()

    def test_load_stage_failure_returns_none(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        """If ``AVAILABLE`` is True but ``load_stage`` raises (flaky GPU),
        the dispatcher must return ``None`` and warn — never swallow silently."""
        patched_ovrtx.available = True
        patched_ovrtx.set_adapter_cls(_FailingOvRtxAdapter)

        warnings: list = []
        from ovwidgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda msg, duration_ms=4000: warnings.append(msg),
        )
        monkeypatch.setattr(ErrorReporter, "log_error", lambda *a, **kw: None)

        renderer = app._build_renderer_for_stage(stub_stage)

        assert renderer is None
        assert len(warnings) == 1

    def test_require_ovrtx_unavailable_raises(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = False
        monkeypatch.setenv("OVWIDGETS_REQUIRE_OVRTX", "1")

        with pytest.raises(RuntimeError, match="ovrtx is required"):
            app._build_renderer_for_stage(stub_stage)

    def test_require_ovrtx_load_stage_failure_raises(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = True
        patched_ovrtx.set_adapter_cls(_FailingOvRtxAdapter)
        monkeypatch.setenv("OVWIDGETS_REQUIRE_OVRTX", "1")

        from ovwidgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(ErrorReporter, "log_error", lambda *a, **kw: None)

        with pytest.raises(RuntimeError, match="ovrtx is required"):
            app._build_renderer_for_stage(stub_stage)


class TestPreconstructOrdering:
    """ovrtx's MDL loader fails if pxr's ``Usd.Stage.Open`` runs first in the
    process. ``Application.open_file`` pre-builds the adapter BEFORE opening
    the stage; ``_build_renderer_for_stage`` must accept the pre-built one
    and reuse it instead of constructing a second ``OvRtxRendererAdapter``.
    """

    def test_prebuilt_is_reused(self, app, patched_ovrtx, stub_stage):
        patched_ovrtx.available = True

        prebuilt = _FakeOvRtxAdapter()
        _FakeOvRtxAdapter.instances.remove(prebuilt)  # construct-only, clean counter

        renderer = app._build_renderer_for_stage(stub_stage, prebuilt=prebuilt)

        assert renderer is prebuilt, "pre-built adapter should not be replaced"
        assert prebuilt.loaded_stage is stub_stage
        assert _FakeOvRtxAdapter.instances == [], (
            "no new adapter should have been constructed when prebuilt was supplied"
        )

    def test_preconstruct_returns_adapter(self, app, patched_ovrtx):
        patched_ovrtx.available = True
        _FakeOvRtxAdapter.instances = []

        adapter = app._preconstruct_ovrtx_renderer()

        assert isinstance(adapter, _FakeOvRtxAdapter)
        assert adapter.loaded_stage is None, (
            "preconstruct must not load a stage — that is the load_stage call's job"
        )

    def test_preconstruct_returns_none_when_unavailable(
        self, app, patched_ovrtx, monkeypatch
    ):
        patched_ovrtx.available = False

        from ovwidgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda *args, **kwargs: None,
        )

        adapter = app._preconstruct_ovrtx_renderer()

        assert adapter is None


class TestCliNoRendererFlag:
    """The ``--renderer`` flag has been removed — ovrtx is the only backend."""

    def test_renderer_flag_is_rejected(self):
        from ovwidgets.app.__main__ import _parse_args
        with pytest.raises(SystemExit):
            _parse_args(["--renderer", "ovrtx"])

    def test_parse_without_flag(self):
        from ovwidgets.app.__main__ import _parse_args
        ns = _parse_args([])
        assert ns.usd_file is None

    def test_parse_positional_usd_file(self):
        from ovwidgets.app.__main__ import _parse_args
        ns = _parse_args(["scene.usda"])
        assert ns.usd_file == "scene.usda"


class TestSetRendererShutsDownOld:
    """``set_renderer()`` must call ``shutdown()`` on the previously-installed
    renderer before swapping — the GPU resources of the old renderer need to
    be released before the new one starts touching the frame."""

    def test_shutdown_called_on_old_renderer(self):
        from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
        from ovwidgets.viewport.viewport_widget import ViewportWidget

        old = MockRendererAdapter()
        new = MockRendererAdapter()
        widget = ViewportWidget.__new__(ViewportWidget)
        widget._renderer = old
        widget._bus = None
        widget._manipulator_registry = None

        widget.set_renderer(new)

        assert old._shutdown_called is True
        assert widget._renderer is new

    def test_same_renderer_not_shutdown(self):
        from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
        from ovwidgets.viewport.viewport_widget import ViewportWidget

        r = MockRendererAdapter()
        widget = ViewportWidget.__new__(ViewportWidget)
        widget._renderer = r
        widget._bus = None
        widget._manipulator_registry = None

        widget.set_renderer(r)

        assert r._shutdown_called is False

    def test_set_renderer_propagates_zero_copy_state(self):
        from ovui_data_adapters.common import ZeroCopyState, _Mode

        from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
        from ovwidgets.viewport.viewport_widget import ViewportWidget

        class ZeroCopyAwareRenderer(MockRendererAdapter):
            def __init__(self):
                super().__init__()
                self.zero_copy_state = None

            def set_zero_copy_state(self, state):
                self.zero_copy_state = state

        old = MockRendererAdapter()
        new = ZeroCopyAwareRenderer()
        state = ZeroCopyState(_Mode.PROBING)
        widget = ViewportWidget.__new__(ViewportWidget)
        widget._renderer = old
        widget._bus = None
        widget._zero_copy_state = state

        widget.set_renderer(new)

        assert widget._renderer is new
        assert new.zero_copy_state is state
