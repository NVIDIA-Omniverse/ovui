# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Application renderer construction — ovrtx primary.

USD Viewer uses ovrtx as the primary renderer. ``_build_renderer_for_stage``
returns an :class:`OvRtxRendererAdapter` when ovrtx is available, fails by
default when it is unavailable, and returns ``None`` only when the explicit
fallback opt-out env var is set and the selected provider permits fallback.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from ovui_widgets.app.application import (
    _NO_PREBUILT_RENDERER,
    Application,
    _renderer_required_for_session,
    _require_ovrtx_enabled,
)
from ovui_widgets.common.selection import SelectionBus


@pytest.fixture
def app(monkeypatch):
    """Fresh Application with singleton cleanup."""
    monkeypatch.delenv("OVUI_WIDGETS_REQUIRE_OVRTX", raising=False)
    Application._instance = None
    SelectionBus._instance = None
    application = Application()
    try:
        yield application
    finally:
        application.shutdown()
        Application._instance = None
        SelectionBus._instance = None


class _FakeOvRtxAdapter:
    """Stand-in for ``OvRtxRendererAdapter`` used by the dispatch tests."""

    instances: list = []

    def __init__(self, *args, **kwargs) -> None:
        self.loaded_stage = None
        self.shutdown_called = False
        self.shutdown_calls = 0
        _FakeOvRtxAdapter.instances.append(self)

    def load_stage(self, stage) -> None:
        self.loaded_stage = stage

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.shutdown_called = True


class _ReusableOvRtxAdapter(_FakeOvRtxAdapter):
    """A renderer that supports in-place stage swap, like the real
    ``OvRtxRendererAdapter`` — the app must reuse it for a document
    replacement instead of constructing a second live renderer."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fail_next_load = False

    def supports_in_place_stage_swap(self) -> bool:
        return True

    def is_stage_current(self, stage) -> bool:
        return self.loaded_stage is stage

    def load_stage(self, stage) -> None:
        if self.fail_next_load:
            raise RuntimeError("in-place transition failed")
        self.loaded_stage = stage


class _FailingOvRtxAdapter:
    """``OvRtxRendererAdapter`` stand-in whose ``load_stage`` raises."""

    instances: list = []

    def __init__(self, *args, **kwargs) -> None:
        self.shutdown_called = False
        self.instances.append(self)

    def load_stage(self, stage) -> None:
        raise RuntimeError("simulated GPU init failure")

    def shutdown(self) -> None:
        self.shutdown_called = True


class _CleanupFailingOvRtxAdapter(_FailingOvRtxAdapter):
    """Partially loaded renderer that cannot safely release its resources."""

    def shutdown(self) -> None:
        raise RuntimeError("simulated detach failure")


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


class TestRequireOvrtxPolicy:
    @pytest.mark.parametrize("value", [None, "1", "true", "yes", "on", "garbage"])
    def test_default_and_truthy_values_require_ovrtx(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("OVUI_WIDGETS_REQUIRE_OVRTX", raising=False)
        else:
            monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", value)

        assert _require_ovrtx_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_explicit_false_values_allow_fallback(self, monkeypatch, value):
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", value)

        assert _require_ovrtx_enabled() is False

    def test_provider_can_forbid_explicit_renderer_fallback(self, monkeypatch):
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

        assert _renderer_required_for_session(
            types.SimpleNamespace(allows_renderer_fallback=False)
        ) is True
        assert _renderer_required_for_session(types.SimpleNamespace()) is False


class TestOvrtxConstruction:
    def test_available_returns_ovrtx(self, app, patched_ovrtx, stub_stage):
        patched_ovrtx.available = True

        renderer = app._build_renderer_for_stage(stub_stage)

        assert isinstance(renderer, _FakeOvRtxAdapter)
        assert app._adapter_session is not None
        assert renderer.loaded_stage is stub_stage
        assert len(_FakeOvRtxAdapter.instances) == 1

    def test_explicit_fallback_unavailable_returns_none_and_warns(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = False
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

        warnings: list = []
        from ovui_widgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda msg, duration_ms=4000: warnings.append(msg),
        )

        renderer = app._build_renderer_for_stage(stub_stage)

        assert renderer is None
        assert _FakeOvRtxAdapter.instances == []
        assert len(warnings) == 1
        assert "ovrtx" in warnings[0].lower()

    def test_explicit_fallback_load_stage_failure_returns_none(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        """If ``AVAILABLE`` is True but ``load_stage`` raises (flaky GPU),
        the dispatcher must return ``None`` and warn — never swallow silently."""
        patched_ovrtx.available = True
        patched_ovrtx.set_adapter_cls(_FailingOvRtxAdapter)
        _FailingOvRtxAdapter.instances = []
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

        warnings: list = []
        from ovui_widgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda msg, duration_ms=4000: warnings.append(msg),
        )
        monkeypatch.setattr(ErrorReporter, "log_error", lambda *a, **kw: None)

        renderer = app._build_renderer_for_stage(stub_stage)

        assert renderer is None
        assert _FailingOvRtxAdapter.instances[-1].shutdown_called is True
        assert len(warnings) == 1

    def test_provider_policy_blocks_explicit_fallback(
        self,
        app,
        patched_ovrtx,
        stub_stage,
        monkeypatch,
    ):
        patched_ovrtx.available = False
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")
        app.get_adapter_session().allows_renderer_fallback = False

        with pytest.raises(RuntimeError, match="ovrtx is required"):
            app._build_renderer_for_stage(stub_stage)

    def test_default_unavailable_raises(self, app, patched_ovrtx, stub_stage):
        patched_ovrtx.available = False

        with pytest.raises(RuntimeError, match="ovrtx is required"):
            app._build_renderer_for_stage(stub_stage)

    def test_default_load_stage_failure_raises(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = True
        patched_ovrtx.set_adapter_cls(_FailingOvRtxAdapter)
        _FailingOvRtxAdapter.instances = []

        from ovui_widgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(ErrorReporter, "log_error", lambda *a, **kw: None)

        with pytest.raises(RuntimeError, match="ovrtx is required"):
            app._build_renderer_for_stage(stub_stage)
        assert _FailingOvRtxAdapter.instances[-1].shutdown_called is True

    def test_require_ovrtx_unavailable_raises(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = False
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "1")

        with pytest.raises(RuntimeError, match="ovrtx is required"):
            app._build_renderer_for_stage(stub_stage)

    def test_require_ovrtx_load_stage_failure_raises(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = True
        patched_ovrtx.set_adapter_cls(_FailingOvRtxAdapter)
        _FailingOvRtxAdapter.instances = []
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "1")

        from ovui_widgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(ErrorReporter, "log_error", lambda *a, **kw: None)

        with pytest.raises(RuntimeError, match="ovrtx is required"):
            app._build_renderer_for_stage(stub_stage)
        assert _FailingOvRtxAdapter.instances[-1].shutdown_called is True

    def test_load_failure_with_cleanup_failure_is_always_fail_closed(
        self, app, patched_ovrtx, stub_stage, monkeypatch
    ):
        patched_ovrtx.available = True
        patched_ovrtx.set_adapter_cls(_CleanupFailingOvRtxAdapter)
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

        from ovui_widgets.common.error_reporter import ErrorReporter

        monkeypatch.setattr(ErrorReporter, "log_error", lambda *a, **kw: None)

        with pytest.raises(RuntimeError, match="could not be safely shut down"):
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

    @staticmethod
    def _install_document_wiring_fakes(app, viewport):
        stage_adapter = MagicMock()
        stage_adapter.get_root.return_value = object()
        stage_adapter.get_children.return_value = []
        stage_adapter.read_bound_camera.return_value = None
        layer_adapter = MagicMock()
        app._adapter_factories = types.SimpleNamespace(
            stage=lambda *_args: stage_adapter,
            properties=lambda *_args: MagicMock(),
            transforms=lambda *_args: MagicMock(),
            layers=lambda *_args: layer_adapter,
        )
        app._viewport_window = viewport
        return stage_adapter, layer_adapter

    def test_document_replacement_installs_fresh_prebuilt_renderer(
        self,
        app,
    ):
        old_renderer = _FakeOvRtxAdapter()
        fresh_renderer = _FakeOvRtxAdapter()
        viewport = MagicMock()
        viewport._renderer = old_renderer
        self._install_document_wiring_fakes(app, viewport)
        app._viewport_render_clock = MagicMock()
        stage = object()

        app._load_stage(
            stage,
            title="reopened.usd",
            prebuilt_renderer=fresh_renderer,
        )

        assert fresh_renderer.loaded_stage is stage
        viewport.set_renderer.assert_called_once_with(fresh_renderer)
        app._viewport_render_clock.reset.assert_called_once_with()

    @pytest.mark.parametrize(
        "primary",
        [RuntimeError("wire failed"), KeyboardInterrupt("wire interrupted")],
        ids=["exception", "baseexception"],
    )
    def test_post_commit_wire_failure_reclaims_unoffered_fresh_renderer(
        self, app, primary
    ):
        """A cold/fresh renderer remains transaction-owned until the
        viewport handoff, so an earlier Stage/Property/transform wire fault
        cannot drop the only GPU/native owner."""
        fresh = _FakeOvRtxAdapter()
        viewport = MagicMock()
        viewport._renderer = None
        viewport.set_renderer.return_value = True
        self._install_document_wiring_fakes(app, viewport)
        app._stage_window = MagicMock()
        app._stage_window.set_adapter.side_effect = primary
        stage = object()

        with pytest.raises(BaseException) as caught:
            app._load_stage(
                stage, title="cold.usd", prebuilt_renderer=fresh
            )

        assert caught.value is primary
        assert fresh.loaded_stage is stage
        assert fresh.shutdown_calls == 1
        assert app.unresolved_renderer is None
        assert app._stage_adapter is None
        assert all(
            not call.args or call.args[0] is not fresh
            for call in viewport.set_renderer.call_args_list
        )
        viewport.set_renderer.assert_called_once_with(None)

    def test_post_commit_wire_failure_retains_failed_fresh_cleanup_for_retry(
        self, app
    ):
        primary = SystemExit("wire exited")
        cleanup_fault = KeyboardInterrupt("fresh shutdown refused")

        class _RetryableFresh(_FakeOvRtxAdapter):
            blocked = True

            def shutdown(self):
                self.shutdown_calls += 1
                if self.blocked:
                    raise cleanup_fault
                self.shutdown_called = True

        fresh = _RetryableFresh()
        viewport = MagicMock()
        viewport._renderer = None
        self._install_document_wiring_fakes(app, viewport)
        app._stage_window = MagicMock()
        app._stage_window.set_adapter.side_effect = primary

        with pytest.raises(SystemExit) as caught:
            app._load_stage(
                object(), title="cold.usd", prebuilt_renderer=fresh
            )
        assert caught.value is primary
        assert app.unresolved_renderer is fresh
        assert app.unresolved_renderer_error is cleanup_fault
        assert fresh.shutdown_calls == 1
        assert app._admit_stage_load() is False
        assert app.unresolved_renderer is fresh
        assert app.unresolved_renderer_error is cleanup_fault
        assert fresh.shutdown_calls == 2

        fresh.blocked = False
        assert app._admit_stage_load() is True
        assert app.unresolved_renderer is None
        assert app.unresolved_renderer_error is None
        assert fresh.shutdown_calls == 3

    def test_document_replacement_reuses_in_place_capable_renderer(
        self,
        app,
    ):
        """A live renderer that supports in-place stage swap is REUSED for a
        document replacement: no second renderer is constructed (two live
        ovrtx renderers contending is the File > New freeze), the attached
        renderer is transitioned to the new stage, the viewport receives the
        SAME renderer object, and the live renderer is never shut down."""
        reused = _ReusableOvRtxAdapter()
        _FakeOvRtxAdapter.instances = [reused]
        viewport = MagicMock()
        viewport._renderer = reused
        viewport.set_renderer.return_value = True
        self._install_document_wiring_fakes(app, viewport)
        app._viewport_render_clock = MagicMock()
        new_stage = object()

        # The in-memory path supplies NO prebuilt renderer, so the reuse must
        # be discovered from the live viewport renderer itself.
        app.open_stage(new_stage)

        assert reused.loaded_stage is new_stage, (
            "the already-attached renderer must be transitioned in place"
        )
        assert _FakeOvRtxAdapter.instances == [reused], (
            "document replacement must not construct a second live renderer"
        )
        viewport.set_renderer.assert_called_once_with(reused)
        assert reused.shutdown_called is False, (
            "the reused live renderer must never be shut down by the replacement"
        )

    def test_reused_renderer_survives_replacement_build_failure(
        self,
        app,
        monkeypatch,
    ):
        """If the in-place transition fails, the reused viewport renderer is
        NOT shut down by the replacement — its own load_stage rolled the old
        scene back and the viewport still owns it."""
        reused = _ReusableOvRtxAdapter()
        reused.fail_next_load = True
        _FakeOvRtxAdapter.instances = [reused]
        viewport = MagicMock()
        viewport._renderer = reused
        self._install_document_wiring_fakes(app, viewport)
        monkeypatch.setattr(app, "_viewport_render_clock", MagicMock())
        from ovui_widgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(ErrorReporter, "log_error", lambda *a, **kw: None)

        with pytest.raises(RuntimeError, match="in-place transition failed"):
            app.open_stage(object())

        assert reused.shutdown_called is False, (
            "a failed in-place transition must not shut the live renderer down"
        )
        viewport.set_renderer.assert_not_called()

    @pytest.mark.parametrize(
        "primary",
        [
            RuntimeError("committed new with cleanup debt"),
            SystemExit("committed new then exited"),
        ],
        ids=["exception", "baseexception"],
    )
    def test_reused_throwing_commit_converges_no_document_then_recovers(
        self, app, primary
    ):
        """Direct open_stage cannot retain OLD adapters when the in-place
        renderer proves a throwing load nevertheless committed NEW."""
        old_stage = object()
        new_stage = object()

        class _CommitThenRaise(_ReusableOvRtxAdapter):
            def load_stage(self, stage):
                self.loaded_stage = stage
                raise primary

        renderer = _CommitThenRaise()

        class _Viewport:
            unresolved_predecessor = None

            def __init__(self):
                self._renderer = renderer
                self.calls = []

            def set_renderer(self, value):
                self.calls.append(value)
                if value is None and self._renderer is not None:
                    self._renderer.shutdown()
                self._renderer = value
                return True

            def attach_stage(self, **_kwargs):
                return None

            def set_scene_name(self, _title):
                return None

            def update_prim_count(self, _count):
                return None

            def apply_camera_pose(self, _pose):
                return False

            def frame_paths(self, _paths):
                return None

            def destroy(self):
                if self._renderer is not None:
                    self._renderer.shutdown()
                self._renderer = None

        viewport = _Viewport()
        old_adapter = MagicMock()
        old_adapter.stage = old_stage
        new_adapter = MagicMock()
        new_adapter.stage = new_stage
        new_adapter.get_root.return_value = object()
        new_adapter.get_children.return_value = []
        new_adapter.read_bound_camera.return_value = None
        app._stage_adapter = old_adapter
        app._viewport_window = viewport
        app._adapter_factories = types.SimpleNamespace(
            stage=lambda *_args: new_adapter,
            properties=lambda *_args: MagicMock(),
            transforms=lambda *_args: MagicMock(),
            layers=lambda *_args: MagicMock(),
        )
        from ovui_widgets.common.error_reporter import ErrorReporter
        original_log = ErrorReporter.log_error
        ErrorReporter.log_error = staticmethod(lambda *a, **kw: None)
        try:
            with pytest.raises(BaseException) as caught:
                app.open_stage(new_stage)
        finally:
            ErrorReporter.log_error = original_log

        if isinstance(primary, Exception):
            assert caught.value.__cause__ is primary
        else:
            assert caught.value is primary
        assert app._stage_adapter is None
        assert viewport._renderer is None
        assert renderer.shutdown_calls == 1
        old_adapter.dispose.assert_called()
        new_adapter.dispose.assert_called()

        # A later admitted fresh renderer establishes one complete NEW state.
        recovery_stage = object()
        recovery_renderer = _FakeOvRtxAdapter()
        recovery_adapter = MagicMock()
        recovery_adapter.get_root.return_value = object()
        recovery_adapter.get_children.return_value = []
        recovery_adapter.read_bound_camera.return_value = None
        app._adapter_factories.stage = lambda *_args: recovery_adapter
        app._load_stage(
            recovery_stage,
            title="recovery.usd",
            prebuilt_renderer=recovery_renderer,
        )
        assert app._stage_adapter is recovery_adapter
        assert viewport._renderer is recovery_renderer
        assert recovery_renderer.loaded_stage is recovery_stage

    def test_reused_throwing_load_with_unknown_identity_fails_closed(
        self, app
    ):
        """A reusable third-party renderer that cannot prove OLD vs NEW
        cannot authorize preservation of the old adapter."""
        primary = RuntimeError("ambiguous in-place load")

        class _UnknownRenderer:
            def __init__(self):
                self.shutdown_calls = 0

            def supports_in_place_stage_swap(self):
                return True

            def load_stage(self, _stage):
                raise primary

            def shutdown(self):
                self.shutdown_calls += 1

        renderer = _UnknownRenderer()
        viewport = MagicMock()
        viewport._renderer = renderer

        def _clear(value):
            if value is None:
                renderer.shutdown()
                viewport._renderer = None
            return True

        viewport.set_renderer.side_effect = _clear
        self._install_document_wiring_fakes(app, viewport)
        old_adapter = MagicMock()
        old_adapter.stage = object()
        app._stage_adapter = old_adapter
        from ovui_widgets.common.error_reporter import ErrorReporter
        original_log = ErrorReporter.log_error
        ErrorReporter.log_error = staticmethod(lambda *a, **kw: None)
        try:
            with pytest.raises(RuntimeError) as caught:
                app.open_stage(object())
        finally:
            ErrorReporter.log_error = original_log
        assert caught.value.__cause__ is primary
        assert app._stage_adapter is None
        assert viewport._renderer is None
        assert renderer.shutdown_calls == 1

    def test_document_replacement_failure_preserves_live_renderer(
        self,
        app,
        monkeypatch,
    ):
        """A pre-commit build failure never touches the installed renderer:
        the old document — including its live, usable renderer — stays
        exactly as it was before the attempt."""
        old_renderer = _FakeOvRtxAdapter()
        viewport = MagicMock()
        viewport._renderer = old_renderer
        self._install_document_wiring_fakes(app, viewport)
        monkeypatch.setattr(
            app,
            "_build_renderer_for_stage",
            MagicMock(side_effect=RuntimeError("replacement attach failed")),
        )

        with pytest.raises(RuntimeError, match="replacement attach failed"):
            app._load_stage(
                object(),
                title="reopened.usd",
                prebuilt_renderer=_FakeOvRtxAdapter(),
            )

        viewport.set_renderer.assert_not_called()
        assert old_renderer.shutdown_called is False, (
            "a failed pre-commit replacement must not destroy the old "
            "document's live renderer"
        )

    def test_public_replacement_failure_keeps_old_document_and_live_renderer(
        self,
        app,
        monkeypatch,
    ):
        """PUBLIC-path atomicity with a genuinely live old renderer: a
        failed ``open_stage()`` replacement preserves the ENTIRE old
        document — adapter (undisposed), stage wiring, and the live
        renderer — propagates the original exception by identity, and a
        later replacement succeeds unimpaired."""
        adapters = []

        def _stage_factory(stage, _undo, _call_later):
            adapter = MagicMock()
            adapter.get_root.return_value = object()
            adapter.get_children.return_value = []
            adapter.read_bound_camera.return_value = None
            adapters.append(adapter)
            return adapter

        viewport = MagicMock()
        viewport.set_renderer.return_value = True
        app._adapter_factories = types.SimpleNamespace(
            stage=_stage_factory,
            properties=lambda *_args: MagicMock(),
            transforms=lambda *_args: MagicMock(),
            layers=lambda *_args: MagicMock(),
        )
        app._viewport_window = viewport
        app._viewport_render_clock = MagicMock()

        old_renderer = _FakeOvRtxAdapter()
        injected = RuntimeError("replacement renderer build failed")
        new_renderer = _FakeOvRtxAdapter()
        build = MagicMock(side_effect=[old_renderer, injected, new_renderer])
        monkeypatch.setattr(app, "_build_renderer_for_stage", build)

        app.open_stage(object())
        old_adapter = app._stage_adapter
        assert old_adapter is adapters[0]
        # Reflect the successful install on the fake viewport.
        viewport._renderer = old_renderer
        viewport.set_renderer.reset_mock()

        with pytest.raises(RuntimeError) as excinfo:
            app.open_stage(object())

        assert excinfo.value is injected, "original exception identity lost"
        assert app._stage_adapter is old_adapter, (
            "old document adapter must remain installed"
        )
        old_adapter.dispose.assert_not_called()
        viewport.set_renderer.assert_not_called()
        assert old_renderer.shutdown_called is False, (
            "old document's live renderer must remain installed and usable"
        )

        # The preserved document replaces successfully afterwards.
        app.open_stage(object())
        assert app._stage_adapter is adapters[-1]
        viewport.set_renderer.assert_called_once_with(new_renderer)
        assert build.call_count == 3

    def test_cold_empty_stage_consumes_early_bootstrap_renderer(
        self,
        app,
        monkeypatch,
    ):
        prebuilt = _FakeOvRtxAdapter()
        stage = object()
        app._startup_prebuilt_renderer = prebuilt
        monkeypatch.setattr(app, "_can_create_empty_startup_stage", lambda: True)
        monkeypatch.setattr(app, "_create_empty_startup_stage", lambda: stage)
        monkeypatch.setattr(
            app,
            "_preconstruct_ovrtx_renderer",
            lambda: pytest.fail("cold startup must not construct OVRTX after UI init"),
        )
        app._load_stage = MagicMock()

        assert app._load_empty_startup_stage() is True

        app._load_stage.assert_called_once_with(
            stage,
            title="New Stage",
            prebuilt_renderer=prebuilt,
        )
        assert app._startup_prebuilt_renderer is _NO_PREBUILT_RENDERER

    def test_cold_empty_stage_keeps_failed_early_attempt_sticky(
        self,
        app,
        monkeypatch,
    ):
        stage = object()
        app._startup_prebuilt_renderer = None
        monkeypatch.setattr(app, "_can_create_empty_startup_stage", lambda: True)
        monkeypatch.setattr(app, "_create_empty_startup_stage", lambda: stage)
        monkeypatch.setattr(
            app,
            "_preconstruct_ovrtx_renderer",
            lambda: pytest.fail("failed early OVRTX attempt must not be retried"),
        )
        app._load_stage = MagicMock()

        assert app._load_empty_startup_stage() is True

        app._load_stage.assert_called_once_with(
            stage,
            title="New Stage",
            prebuilt_renderer=None,
        )
        assert app._startup_prebuilt_renderer is None

    def test_failed_early_attempt_is_not_retried_after_stage_open(
        self, app, stub_stage, monkeypatch
    ):
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")
        monkeypatch.setattr(
            app,
            "_preconstruct_ovrtx_renderer",
            lambda: pytest.fail("late OVRTX construction must not be retried"),
        )
        from ovui_widgets.common.error_reporter import ErrorReporter

        monkeypatch.setattr(ErrorReporter, "show_warning", lambda *args, **kwargs: None)

        assert app._build_renderer_for_stage(stub_stage, prebuilt=None) is None

    def test_failed_early_attempt_remains_sticky_across_file_opens(
        self, app, monkeypatch
    ):
        """A second open must not retry OVRTX after UI/OVStage is live."""

        app._startup_prebuilt_renderer = None
        app._adapter_session = types.SimpleNamespace(
            open_stage=lambda path: f"stage:{path}"
        )
        monkeypatch.setattr(
            app,
            "_preconstruct_ovrtx_renderer",
            lambda: pytest.fail("late OVRTX construction must not be retried"),
        )
        loaded: list[tuple[object, str, object]] = []

        def _load_stage(stage, title, prebuilt_renderer):
            loaded.append((stage, title, prebuilt_renderer))

        monkeypatch.setattr(app, "_load_stage", _load_stage)

        app.open_file("first.usda")
        app.open_file("second.usda")

        assert loaded == [
            ("stage:first.usda", "first.usda", None),
            ("stage:second.usda", "second.usda", None),
        ]
        assert app._startup_prebuilt_renderer is None

    def test_preconstruct_returns_adapter(self, app, patched_ovrtx):
        patched_ovrtx.available = True
        _FakeOvRtxAdapter.instances = []

        adapter = app._preconstruct_ovrtx_renderer()

        assert isinstance(adapter, _FakeOvRtxAdapter)
        assert app._adapter_session is not None
        assert adapter.loaded_stage is None, (
            "preconstruct must not load a stage — that is the load_stage call's job"
        )

    def test_preconstruct_returns_none_when_unavailable(
        self, app, patched_ovrtx, monkeypatch
    ):
        patched_ovrtx.available = False
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

        from ovui_widgets.common.error_reporter import ErrorReporter
        monkeypatch.setattr(
            ErrorReporter, "show_warning",
            lambda *args, **kwargs: None,
        )

        adapter = app._preconstruct_ovrtx_renderer()

        assert adapter is None
        assert app._adapter_session is not None


class TestCliNoRendererFlag:
    """The ``--renderer`` flag has been removed — ovrtx is the only backend."""

    def test_renderer_flag_is_rejected(self):
        from ovui_widgets.app.__main__ import _parse_args
        with pytest.raises(SystemExit):
            _parse_args(["--renderer", "ovrtx"])

    def test_parse_without_flag(self):
        from ovui_widgets.app.__main__ import _parse_args
        ns = _parse_args([])
        assert ns.usd_file is None

    def test_parse_positional_usd_file(self):
        from ovui_widgets.app.__main__ import _parse_args
        ns = _parse_args(["scene.usda"])
        assert ns.usd_file == "scene.usda"


class TestSetRendererShutsDownOld:
    """``set_renderer()`` must call ``shutdown()`` on the previously-installed
    renderer before swapping — the GPU resources of the old renderer need to
    be released before the new one starts touching the frame."""

    @staticmethod
    def _seed_viewport_init_state(widget):
        from collections import deque

        from ovui_widgets.viewport.resolution_state import (
            ViewportAvailabilitySnapshot,
            ViewportResolutionState,
        )

        widget._services = getattr(widget, "_services", None)
        widget._fps_sample_intervals = deque()
        widget._fps_sample_seconds = 0.0
        widget._last_fps = None
        widget._last_resolution = None
        widget._resolution_state = ViewportResolutionState.default()
        widget._resolution_state_observers_closed = False
        widget._viewport_id_released = False
        widget._resolution_availability_owner_alive = True
        widget._resolution_availability = ViewportAvailabilitySnapshot(
            renderer_available=widget._renderer is not None,
            settings_available=False,
        )
        widget._resolution_availability_observers = {}
        widget._resolution_availability_observers_closed = False
        widget._scene_name = None
        widget._scene_value_label = None
        widget._scene_row = None
        widget._fps_value_label = None
        widget._resolution_value_label = None
        widget._fps_res_row = None
        widget._resolution_label = None
        widget._fps_res_separator_label = None
        widget._livestream_row = None
        widget._livestream_value_label = None

    def test_shutdown_called_on_old_renderer(self):
        from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
        from ovui_widgets.viewport.viewport_widget import ViewportWidget

        old = MockRendererAdapter()
        new = MockRendererAdapter()
        widget = ViewportWidget.__new__(ViewportWidget)
        widget._renderer = old
        widget._bus = None
        widget._manipulator_registry = None
        self._seed_viewport_init_state(widget)

        widget.set_renderer(new)

        assert old._shutdown_called is True
        assert widget._renderer is new

    def test_same_renderer_not_shutdown(self):
        from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
        from ovui_widgets.viewport.viewport_widget import ViewportWidget

        r = MockRendererAdapter()
        widget = ViewportWidget.__new__(ViewportWidget)
        widget._renderer = r
        widget._bus = None
        widget._manipulator_registry = None
        self._seed_viewport_init_state(widget)

        widget.set_renderer(r)

        assert r._shutdown_called is False

    def test_set_renderer_propagates_zero_copy_state(self):
        from ovui_data_adapters.common import ZeroCopyState, _Mode

        from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
        from ovui_widgets.viewport.viewport_widget import ViewportWidget

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
        self._seed_viewport_init_state(widget)

        widget.set_renderer(new)

        assert widget._renderer is new
        assert new.zero_copy_state is state

    def test_set_renderer_updates_transform_model_reference_only(self):
        from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
        from ovui_widgets.viewport.prim_transform_model import PrimTransformModel
        from ovui_widgets.viewport.viewport_widget import ViewportWidget

        class PreviewSpyRenderer(MockRendererAdapter):
            def __init__(self):
                super().__init__()
                self.preview_calls = []

            @property
            def supports_live_local_transform(self):
                self.preview_calls.append("supports_live_local_transform")
                return True

            def set_live_local_transform(self, path, matrix):
                self.preview_calls.append(("set_live_local_transform", path, matrix))
                return True

            def clear_live_local_transforms(self, paths):
                self.preview_calls.append(
                    ("clear_live_local_transforms", tuple(paths or ()))
                )

        old = PreviewSpyRenderer()
        new = PreviewSpyRenderer()
        widget = ViewportWidget.__new__(ViewportWidget)
        widget._renderer = old
        widget._transform_model = PrimTransformModel(renderer=old)
        widget._bus = None
        self._seed_viewport_init_state(widget)

        widget.set_renderer(new)

        assert widget._renderer is new
        assert widget._transform_model.renderer_adapter is new
        assert old.preview_calls == []
        assert new.preview_calls == []


class TestUnresolvedRendererOwnership:
    """The application owns any renderer whose shutdown is unproven and
    gates the next load on resolving it (single-slot, never forgotten)."""

    def _app(self):
        from ovui_widgets.app.application import Application

        app = Application.__new__(Application)
        app._unresolved_renderer = None
        app._unresolved_renderer_error = None
        return app

    def test_resolver_blocks_until_shutdown_proven(self):
        app = self._app()
        assert app._resolve_unresolved_renderer() is True
        pending = type("R", (), {})()
        calls = {"n": 0}

        def failing():
            calls["n"] += 1
            raise RuntimeError("still failing")

        pending.shutdown = failing
        app._unresolved_renderer = pending
        assert app._resolve_unresolved_renderer() is False
        assert app.unresolved_renderer is pending
        first_error = app.unresolved_renderer_error
        assert isinstance(first_error, RuntimeError)
        assert str(first_error) == "still failing"
        pending.shutdown = lambda: calls.__setitem__("n", calls["n"] + 1)
        assert app._resolve_unresolved_renderer() is True
        assert app.unresolved_renderer is None
        assert app.unresolved_renderer_error is None
        assert calls["n"] == 2

    def test_every_load_route_is_gated_before_any_side_effect(self):
        # An Application seeded ONLY with debt: any pre-gate side effect
        # (subscription cancel, selection clear, factory, preconstruct,
        # native open, adapter/UI work) would raise AttributeError or
        # hit the recorders below.
        from types import SimpleNamespace

        from ovui_widgets.app.application import (
            _NO_PREBUILT_RENDERER,
            Application,
        )

        def _debt():
            r = type("R", (), {})()
            def _fail():
                raise RuntimeError("shutdown unproven")
            r.shutdown = _fail
            return r

        events = []
        app = Application.__new__(Application)
        app._unresolved_renderer = _debt()
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: events.append("subscription_cancel")
        )
        app._selection_bus = SimpleNamespace(
            clear=lambda: events.append("selection_clear")
        )
        app._require_factory = lambda kind: events.append(f"factory:{kind}")
        app._load_stage(object(), title="probe")
        assert events == []
        assert app.unresolved_renderer is not None

        app2 = Application.__new__(Application)
        app2._unresolved_renderer = _debt()
        app2._startup_prebuilt_renderer = _NO_PREBUILT_RENDERER
        app2._preconstruct_ovrtx_renderer = (
            lambda: events.append("renderer_preconstruct")
        )
        app2.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: events.append("native_stage_open")
        )
        app2.open_file("/tmp/never-opened.usda")
        assert events == []

        app3 = Application.__new__(Application)
        app3._unresolved_renderer = _debt()
        app3._can_create_empty_startup_stage = (
            lambda: events.append("can_create_probe") or True
        )
        assert app3._load_empty_startup_stage() is False
        assert events == []

    def test_shutdown_retains_backing_chain_until_disposal_proven(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        events = []
        pending = type("R", (), {})()

        def _fail():
            events.append("renderer_shutdown_attempt")
            raise RuntimeError("shutdown unproven")

        pending.shutdown = _fail
        app = Application.__new__(Application)
        app._unresolved_renderer = pending
        app._adapter_session = SimpleNamespace(
            shutdown_scene=lambda: events.append("backing_scene_shutdown")
        )
        app.shutdown()
        # nothing dismantled, not reported done, debt still reachable
        assert events == ["renderer_shutdown_attempt"]
        assert getattr(app, "_shutdown_done", False) is False
        assert app.unresolved_renderer is pending
        # retries stay bounded and safe
        app.shutdown()
        assert events == ["renderer_shutdown_attempt"] * 2
        # once disposal is proven, teardown proceeds exactly once
        pending.shutdown = lambda: events.append("renderer_shutdown_ok")
        app.shutdown()
        assert app.unresolved_renderer is None
        assert "backing_scene_shutdown" in events
        assert getattr(app, "_shutdown_done", False) is True
        n = len(events)
        app.shutdown()  # idempotent
        assert len(events) == n

    def test_panel_renderer_refusal_is_raised_and_viewport_owner_is_retained(
        self,
    ):
        """A viewport-level renderer refusal cannot become app success."""
        from ovui_widgets.app.application import Application

        app = Application()
        refusal = RuntimeError("exact viewport renderer refusal")

        class _RetryableViewport:
            def __init__(self):
                self.calls = 0
                self.blocked = True

            def destroy(self):
                self.calls += 1
                if self.blocked:
                    raise refusal

        viewport = _RetryableViewport()
        app._viewport_window = viewport

        with pytest.raises(RuntimeError) as caught:
            app.shutdown()
        assert caught.value is refusal
        assert app._viewport_window is viewport
        assert getattr(app, "_shutdown_done", False) is False
        assert viewport.calls >= 1

        viewport.blocked = False
        app.shutdown()
        assert app._viewport_window is None
        assert getattr(app, "_shutdown_done", False) is True
