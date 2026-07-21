# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Application — OvGear Step 8."""

import os
import pathlib
import sys
import time
import types
from unittest.mock import MagicMock, patch

import pytest

from ovui_widgets.app.application import Application, CallbackHandle
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.settings import Settings
from ovui_widgets.common.undo import UndoManager


@pytest.fixture(autouse=True)
def reset_application():
    """Reset Application and SelectionBus singletons before and after each test."""
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    """Create a fresh Application and shut it down after the test."""
    application = Application()
    yield application
    application.shutdown()


# ---------------------------------------------------------------------------
# Singleton behaviour
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_creates_singleton(self):
        app = Application()
        assert Application._instance is app
        app.shutdown()

    def test_instance_returns_singleton(self, app):
        assert Application.instance() is app

    def test_double_create_raises(self, app):
        with pytest.raises(AssertionError):
            Application()

    def test_instance_before_create_raises(self):
        with pytest.raises(RuntimeError, match="Application not created yet"):
            Application.instance()

    def test_shutdown_allows_recreation(self, app):
        app.shutdown()
        app2 = Application()
        assert Application._instance is app2
        app2.shutdown()

    def test_shutdown_clears_class_instance(self, app):
        app.shutdown()
        assert Application._instance is None


# ---------------------------------------------------------------------------
# request_exit() — issue #35 Step 6 (Codex Round 1 F8)
# ---------------------------------------------------------------------------


class TestRequestExit:
    """``Application.request_exit()`` is the public API every exit
    trigger uses (File → Exit, OS X-button polling, future hotkeys).
    It flips ``self._running = False`` so ``run_async``'s loop exits
    at the next frame boundary, driving the ``finally:`` clause that
    calls :meth:`shutdown` against a live ovui standalone backend.
    """

    def test_request_exit_flips_running_to_false(self, app):
        app._running = True
        app.request_exit()
        assert app._running is False

    def test_request_exit_is_idempotent(self, app):
        """Calling ``request_exit`` repeatedly is harmless — every
        call lands on the same atomic attribute write."""
        app._running = True
        app.request_exit()
        app.request_exit()
        app.request_exit()
        assert app._running is False

    def test_request_exit_does_not_call_shutdown_directly(self, app):
        """``request_exit`` MUST be a fire-and-forget flag flip,
        NOT a direct ``shutdown()`` invocation. ``shutdown()`` runs
        from ``run_async``'s ``finally:`` after the loop exits,
        while ovui is still alive — calling shutdown directly here
        would replay the original Step-1-era timing bug.
        """
        # Spy on Application.shutdown via instance attribute swap.
        shutdown_calls: list[bool] = []
        original = app.shutdown

        def _spy_shutdown() -> None:
            shutdown_calls.append(True)
            return original()

        app.shutdown = _spy_shutdown  # type: ignore[method-assign]
        app._running = True
        app.request_exit()
        assert shutdown_calls == [], (
            "request_exit must not call shutdown() — that's run_async's "
            "finally clause's job"
        )
        assert app._running is False, (
            "even though shutdown wasn't called, _running must still be False"
        )

    def test_request_exit_works_when_running_already_false(self, app):
        """``request_exit`` doesn't care about the prior state —
        a redundant call is fine.
        """
        app._running = False
        app.request_exit()
        assert app._running is False


# ---------------------------------------------------------------------------
# Optional ovinspect integration
# ---------------------------------------------------------------------------


class TestOptionalOvinspect:
    def test_setup_optional_ovinspect_attaches_ovuiinspect_module(self, app, monkeypatch):
        fake = types.SimpleNamespace(attach_application=MagicMock())
        monkeypatch.setitem(sys.modules, "ovuiinspect", fake)

        app._setup_optional_ovinspect()

        assert app._ovinspect_module is fake
        fake.attach_application.assert_called_once_with(app)

    def test_setup_optional_ovinspect_keeps_legacy_ovinspect_fallback(self, app, monkeypatch):
        fake = types.SimpleNamespace(attach_application=MagicMock())
        # Keep this deterministic even when another collected test makes the
        # optional skill package importable from the repository checkout.
        monkeypatch.setitem(sys.modules, "ovuiinspect", None)
        monkeypatch.setitem(sys.modules, "ovinspect", fake)

        app._setup_optional_ovinspect()

        assert app._ovinspect_module is fake
        fake.attach_application.assert_called_once_with(app)

    def test_drain_ovinspect_delegates_to_module(self, app):
        fake = types.SimpleNamespace(drain_pending=MagicMock())
        ui_native = object()
        app._ovinspect_module = fake
        app._ui_native = ui_native

        app._drain_ovinspect()

        fake.drain_pending.assert_called_once_with(ui_native, application=app)

    def test_shutdown_detaches_ovinspect_module(self, app):
        fake = types.SimpleNamespace(detach_application=MagicMock())
        app._ovinspect_module = fake

        app.shutdown()

        fake.detach_application.assert_called_once_with(app)
        assert app._ovinspect_module is None


# ---------------------------------------------------------------------------
# Subsystem properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_settings_is_settings_instance(self, app):
        assert isinstance(app.settings, Settings)

    def test_undo_manager_is_undo_manager_instance(self, app):
        assert isinstance(app.undo_manager, UndoManager)

    def test_selection_bus_is_selection_bus_instance(self, app):
        assert isinstance(app.selection_bus, SelectionBus)

    def test_settings_has_theme_default(self, app):
        assert app.settings.get("ui.theme") is not None

    def test_properties_are_same_objects_on_repeated_access(self, app):
        assert app.settings is app.settings
        assert app.undo_manager is app.undo_manager
        assert app.selection_bus is app.selection_bus


# ---------------------------------------------------------------------------
# CallbackHandle
# ---------------------------------------------------------------------------


class TestCallbackHandle:
    def test_not_fired_initially(self):
        handle = CallbackHandle(0.0, lambda: None)
        assert not handle.is_fired

    def test_not_cancelled_initially(self):
        handle = CallbackHandle(0.0, lambda: None)
        assert not handle.is_cancelled

    def test_cancel_sets_is_cancelled(self):
        handle = CallbackHandle(0.0, lambda: None)
        handle.cancel()
        assert handle.is_cancelled

    def test_cancel_idempotent(self):
        handle = CallbackHandle(0.0, lambda: None)
        handle.cancel()
        handle.cancel()
        assert handle.is_cancelled

    def test_is_fired_after_callback_cleared(self):
        handle = CallbackHandle(0.0, lambda: None)
        handle._callback = None
        assert handle.is_fired


# ---------------------------------------------------------------------------
# call_later and _on_frame_update
# ---------------------------------------------------------------------------


class TestCallLater:
    def test_zero_delay_fires_on_next_frame(self, app):
        fired = []
        app.call_later(0, lambda: fired.append(1))
        app._on_frame_update(0.0)
        assert fired == [1]

    def test_returns_callback_handle(self, app):
        handle = app.call_later(0, lambda: None)
        assert isinstance(handle, CallbackHandle)
        app._on_frame_update(0.0)

    def test_handle_is_fired_after_frame_update(self, app):
        handle = app.call_later(0, lambda: None)
        assert not handle.is_fired
        app._on_frame_update(0.0)
        assert handle.is_fired

    def test_cancelled_callback_doesnt_fire(self, app):
        fired = []
        handle = app.call_later(0, lambda: fired.append(1))
        handle.cancel()
        app._on_frame_update(0.0)
        assert fired == []

    def test_cancelled_handle_is_cancelled(self, app):
        handle = app.call_later(0, lambda: None)
        handle.cancel()
        assert handle.is_cancelled

    def test_future_callback_doesnt_fire_immediately(self, app):
        fired = []
        app.call_later(9999.0, lambda: fired.append(1))
        app._on_frame_update(0.0)
        assert fired == []

    def test_multiple_callbacks_fire_in_insertion_order(self, app):
        order = []
        app.call_later(0, lambda: order.append("a"))
        app.call_later(0, lambda: order.append("b"))
        app.call_later(0, lambda: order.append("c"))
        app._on_frame_update(0.0)
        assert order == ["a", "b", "c"]

    def test_fired_callback_removed_from_pending(self, app):
        app.call_later(0, lambda: None)
        app._on_frame_update(0.0)
        assert len(app._pending_callbacks) == 0

    def test_future_callback_stays_pending(self, app):
        app.call_later(9999.0, lambda: None)
        app._on_frame_update(0.0)
        assert len(app._pending_callbacks) == 1

    def test_mixed_delays_only_due_fire(self, app):
        fired = []
        app.call_later(0, lambda: fired.append("immediate"))
        app.call_later(9999.0, lambda: fired.append("future"))
        app._on_frame_update(0.0)
        assert fired == ["immediate"]

    def test_callback_fires_once_not_twice(self, app):
        fired = []
        app.call_later(0, lambda: fired.append(1))
        app._on_frame_update(0.0)
        app._on_frame_update(0.0)
        assert fired == [1]

    def test_callback_scheduled_from_callback_survives_current_drain(self, app):
        fired = []

        def first():
            fired.append("first")
            app.call_later(0, lambda: fired.append("second"))

        app.call_later(0, first)
        app._on_frame_update(0.0)
        assert fired == ["first"]
        assert len(app._pending_callbacks) == 1

        app._on_frame_update(0.0)
        assert fired == ["first", "second"]

    def test_callback_fires_after_real_delay(self, app):
        fired = []
        app.call_later(0.05, lambda: fired.append(1))
        app._on_frame_update(0.0)
        assert fired == []
        deadline = time.monotonic() + 0.5
        while not fired and time.monotonic() < deadline:
            time.sleep(0.01)
            app._on_frame_update(0.01)
        assert fired == [1]

    def test_shutdown_clears_pending_callbacks(self, app):
        app.call_later(9999.0, lambda: None)
        app.shutdown()
        assert app._pending_callbacks == []


# ---------------------------------------------------------------------------
# Theme integration
# ---------------------------------------------------------------------------


class TestThemeIntegration:
    def test_theme_change_calls_set_theme(self, app):
        with patch("ovui_widgets.app.style.set_theme") as mock_set_theme:
            app.settings.set("ui.theme", "light")
            mock_set_theme.assert_called_once_with("light")

    def test_theme_change_back_calls_set_theme_again(self, app):
        with patch("ovui_widgets.app.style.set_theme") as mock_set_theme:
            app.settings.set("ui.theme", "light")
            app.settings.set("ui.theme", "dark")
            assert mock_set_theme.call_count == 2
            mock_set_theme.assert_called_with("dark")

    def test_on_theme_changed_calls_set_theme_directly(self, app):
        with patch("ovui_widgets.app.style.set_theme") as mock_set_theme:
            app._on_theme_changed("ui.theme", "light")
            mock_set_theme.assert_called_once_with("light")

    def test_settings_subscription_wired_at_init(self, app):
        with patch("ovui_widgets.app.style.set_theme") as mock_set_theme:
            # The subscription was set up in __init__; changing ui.theme
            # must trigger _on_theme_changed without any manual wiring.
            app.settings.set("ui.theme", "light")
            mock_set_theme.assert_called_once_with("light")


# ---------------------------------------------------------------------------
# Shutdown cleanup
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_resets_instance(self, app):
        app.shutdown()
        assert Application._instance is None

    def test_shutdown_stops_running(self, app):
        app._running = True
        app.shutdown()
        assert not app._running

    def test_can_create_new_app_after_shutdown(self, app):
        app.shutdown()
        app2 = Application()
        assert Application.instance() is app2
        app2.shutdown()

    def test_shutdown_twice_is_safe(self, app):
        app.shutdown()
        # Second shutdown should not raise
        app.shutdown()


# ---------------------------------------------------------------------------
# Content window wiring (Step 11)
# ---------------------------------------------------------------------------


def _make_teardown_safe_fake():
    """Minimal panel fake: ``.window`` is None (skipped by _collect_layout),
    ``destroy`` is a no-op. Used as a post-assertion swap-in so the shared
    ``app`` fixture's teardown doesn't trip over per-test fakes that only
    implemented the method under test."""

    class _FakeMW:
        window = None

        def destroy(self):
            pass

    return _FakeMW()


class TestContentWindowField:
    """Application exposes a _content_window slot for Step 11 wiring."""

    def test_content_window_attribute_exists(self, app):
        assert hasattr(app, "_content_window")

    def test_content_window_is_none_before_run(self, app):
        assert app._content_window is None

    def test_shortcuts_loop_includes_content_window(self, app):
        """``_register_shortcuts`` must iterate over the content window too.

        The loop is the only thing that attaches the shared hotkey handler
        to per-panel focus, so forgetting the content window means keyboard
        shortcuts die the moment the user clicks into it.
        """
        handled: list[object] = []

        class _FakeWin:
            def set_key_pressed_fn(self, fn):
                handled.append(fn)

        class _FakeMW:
            window = _FakeWin()  # .window truthy so _collect_layout skips safely

        app._main_win = None
        app._stage_window = None
        app._property_window = None
        app._viewport_window = None
        app._content_window = _FakeMW()
        app._register_shortcuts()
        # Swap to a teardown-safe fake (no ``.window`` → _collect_layout skip path)
        # so the shared fixture's ``application.shutdown`` doesn't re-read the
        # _FakeWin via _save_layout.
        app._content_window = _make_teardown_safe_fake()
        assert handled == [app._on_key_pressed]

    def test_theme_refresh_loop_includes_content_window(self, app):
        """``_on_theme_changed`` must refresh the content window's frame style."""
        called: list[bool] = []

        class _FakeMW:
            window = None

            def on_theme_changed(self):
                called.append(True)

            def destroy(self):
                pass

        app._stage_window = None
        app._property_window = None
        app._viewport_window = None
        app._content_window = _FakeMW()
        with patch("ovui_widgets.app.style.set_theme"):
            app._on_theme_changed("ui.theme", "light")
        assert called == [True]

    def test_shutdown_destroys_content_window(self, app):
        """``shutdown`` must call ``destroy`` on the content window."""
        called: list[bool] = []

        # ``_save_layout`` (called from shutdown) reads ``managed_win.window``
        # before destroy, so the fake needs a truthy ``.window``.
        class _FakeMW:
            window = None  # None-truthy shortcut: _collect_layout skips this panel

            def destroy(self):
                called.append(True)

        app._content_window = _FakeMW()
        app.shutdown()
        assert called == [True]

    def test_shutdown_clears_content_window(self, app):
        class _FakeMW:
            window = None

            def destroy(self):
                pass

        app._content_window = _FakeMW()
        app.shutdown()
        assert app._content_window is None


class TestSaveStageTo:
    """the content browser implementation step 55 — :meth:`Application.save_stage_to`."""

    class _ExportSession:
        def __init__(self, *, supported: bool) -> None:
            self.export_calls = []
            self.supported = supported

        def get_capabilities(self):
            from ovui_data_adapters.common import (
                AdapterCapabilities,
                AdapterCapability,
                StageCapabilities,
            )

            export_stage = (
                AdapterCapability.supported()
                if self.supported
                else AdapterCapability.unsupported("test adapter cannot export")
            )
            return AdapterCapabilities(
                stage=StageCapabilities(export_stage=export_stage)
            )

        def can_export_stage(self):
            raise AssertionError("save_stage_to must read explicit capabilities")

        def export_stage(self, stage, path):
            self.export_calls.append((stage, path))

    def test_current_file_path_initially_none(self, app):
        assert app._current_file_path is None

    def test_save_with_no_stage_returns_false(self, app):
        """No stage loaded → ErrorReporter fires, return False, no crash."""
        assert app._stage_adapter is None
        result = app.save_stage_to("/tmp/does-not-matter.usd")
        assert result is False
        assert app._current_file_path is None  # not updated on failure

    def test_save_with_empty_path_returns_false(self, app):
        """Empty path short-circuits before hitting the adapter."""
        app._stage_adapter = MagicMock()
        result = app.save_stage_to("")
        assert result is False

    def test_save_calls_stage_export(self, app, tmp_path):
        """Happy path: Export is called with the path."""
        target = str(tmp_path / "out.usd")
        fake_stage = MagicMock()
        app._stage_adapter = MagicMock(stage=fake_stage)
        result = app.save_stage_to(target)
        assert result is True
        fake_stage.Export.assert_called_once_with(target)

    def test_save_updates_current_file_path(self, app, tmp_path):
        """On success, the current path is updated so subsequent Save works."""
        target = str(tmp_path / "out.usd")
        app._stage_adapter = MagicMock(stage=MagicMock())
        app.save_stage_to(target)
        assert app._current_file_path == target

    def test_save_appends_to_recent_files(self, app, tmp_path):
        target = str(tmp_path / "out.usd")
        app._stage_adapter = MagicMock(stage=MagicMock())
        app.save_stage_to(target)
        assert target in app._recent_files.get_ordered()

    def test_save_returns_false_when_export_raises(self, app, tmp_path):
        """Export raising is surfaced as False, no current_file_path update."""
        target = str(tmp_path / "broken.usd")
        fake_stage = MagicMock()
        fake_stage.Export.side_effect = RuntimeError("disk full")
        app._stage_adapter = MagicMock(stage=fake_stage)
        result = app.save_stage_to(target)
        assert result is False
        assert app._current_file_path is None

    def test_save_with_adapter_but_no_stage_returns_false(self, app):
        """Adapter present but ``.stage`` is None → fail-safe."""
        app._stage_adapter = MagicMock(stage=None)
        result = app.save_stage_to("/tmp/out.usd")
        assert result is False

    def test_save_uses_explicit_export_capability_not_legacy_can_export_stage(
        self, app, tmp_path,
    ):
        """The write path must consume Step 1 capabilities, not shim methods."""
        target = str(tmp_path / "out.usd")
        fake_stage = object()
        session = self._ExportSession(supported=True)
        app._adapter_session = session
        app._stage_adapter = types.SimpleNamespace(stage=fake_stage)

        result = app.save_stage_to(target)

        assert result is True
        assert session.export_calls == [(fake_stage, target)]
        assert app._current_file_path == target

    def test_current_document_save_persists_layer_state_once_before_export(
        self,
        app,
        tmp_path,
    ):
        target = str(tmp_path / "current.usd")
        fake_stage = object()
        events = []
        session = self._ExportSession(supported=True)
        session.export_stage = lambda stage, path: events.append(
            ("export", stage, path)
        )
        app._adapter_session = session
        app._stage_adapter = types.SimpleNamespace(stage=fake_stage)
        app._layer_adapter = types.SimpleNamespace(
            persist_layer_state_before_save=lambda stage: events.append(
                ("persist", stage)
            )
        )
        app._current_file_path = target

        assert app.save_stage_to(target) is True

        assert events == [
            ("persist", fake_stage),
            ("export", fake_stage, target),
        ]

    def test_save_as_does_not_persist_source_layer_state(self, app, tmp_path):
        source = str(tmp_path / "source.usd")
        target = str(tmp_path / "save-as.usd")
        fake_stage = object()
        session = self._ExportSession(supported=True)
        app._adapter_session = session
        app._stage_adapter = types.SimpleNamespace(stage=fake_stage)
        layer_adapter = MagicMock()
        app._layer_adapter = layer_adapter
        app._current_file_path = source

        assert app.save_stage_to(target) is True

        layer_adapter.persist_layer_state_before_save.assert_not_called()
        assert session.export_calls == [(fake_stage, target)]

    def test_layer_state_persistence_failure_aborts_current_document_save(
        self,
        app,
        tmp_path,
    ):
        target = str(tmp_path / "current.usd")
        fake_stage = object()
        session = self._ExportSession(supported=True)
        app._adapter_session = session
        app._stage_adapter = types.SimpleNamespace(stage=fake_stage)
        app._layer_adapter = types.SimpleNamespace(
            persist_layer_state_before_save=MagicMock(
                side_effect=RuntimeError("metadata write failed")
            )
        )
        app._current_file_path = target

        assert app.save_stage_to(target) is False

        assert session.export_calls == []
        assert app._current_file_path == target

    def test_save_normalizes_local_file_url_before_export(self, app, monkeypatch):
        """Direct save calls may receive LocalFSBackend file:// URLs."""
        import ovui_widgets.app.application as application_module

        monkeypatch.setattr(application_module.os, "name", "nt")
        fake_stage = object()
        session = self._ExportSession(supported=True)
        app._adapter_session = session
        app._stage_adapter = types.SimpleNamespace(stage=fake_stage)

        result = app.save_stage_to("file:///C:/Users/user/Stage.usda")

        assert result is True
        assert session.export_calls == [(fake_stage, "C:/Users/user/Stage.usda")]
        assert app._current_file_path == "C:/Users/user/Stage.usda"

    def test_save_without_export_capability_does_not_write(self, app, tmp_path):
        """A non-exporting adapter cannot reach its export method."""
        target = str(tmp_path / "blocked.usd")
        session = self._ExportSession(supported=False)
        app._adapter_session = session
        app._stage_adapter = types.SimpleNamespace(stage=object())

        result = app.save_stage_to(target)

        assert result is False
        assert session.export_calls == []
        assert not os.path.exists(target)
        assert app._current_file_path is None


# ---------------------------------------------------------------------------
# Layers Step 9 — UsdLayerStackAdapter wiring in _load_stage
# ---------------------------------------------------------------------------


class TestEmptyStartupStageUnsupported:
    """No-file startup must tolerate adapters that cannot create an empty stage."""

    @staticmethod
    def _bare_app() -> Application:
        app = Application.__new__(Application)
        app._adapter_session = None
        app._scratch_stage_dirs = []
        app._stage_adapter = None
        return app

    class _UnsupportedCreateStageSession:
        def __init__(self) -> None:
            self.create_stage_calls: list[str] = []

        def get_capabilities(self):
            from ovui_data_adapters.common import (
                AdapterCapabilities,
                AdapterCapability,
                StageCapabilities,
            )

            return AdapterCapabilities(
                stage=StageCapabilities(
                    create_stage=AdapterCapability.unsupported("not supported")
                )
            )

        def create_stage(self, path: str):
            self.create_stage_calls.append(path)
            raise AssertionError("unsupported create_stage must not be called")

    class _NotImplementedCreateStageSession:
        def __init__(self) -> None:
            self.create_stage_calls: list[str] = []

        def get_capabilities(self):
            from ovui_data_adapters.common import (
                AdapterCapabilities,
                AdapterCapability,
                StageCapabilities,
            )

            return AdapterCapabilities(
                stage=StageCapabilities(create_stage=AdapterCapability.supported())
            )

        def create_stage(self, path: str):
            self.create_stage_calls.append(path)
            raise NotImplementedError("create_stage not implemented")

    class _LegacyNoCreateStageSession:
        def get_capabilities(self):
            return types.SimpleNamespace(stage=types.SimpleNamespace())

    class _SupportedCreateStageSession:
        def __init__(self, stage: object) -> None:
            self.stage = stage
            self.create_stage_calls: list[str] = []

        def get_capabilities(self):
            from ovui_data_adapters.common import (
                AdapterCapabilities,
                AdapterCapability,
                StageCapabilities,
            )

            return AdapterCapabilities(
                stage=StageCapabilities(create_stage=AdapterCapability.supported())
            )

        def create_stage(self, path: str):
            self.create_stage_calls.append(path)
            return self.stage

    def test_empty_startup_stage_skips_explicitly_unsupported_create_stage(self):
        app = self._bare_app()
        session = self._UnsupportedCreateStageSession()
        app._adapter_session = session

        stage = app._create_empty_startup_stage()

        assert stage is None
        assert session.create_stage_calls == []
        assert app._scratch_stage_dirs == []

    def test_empty_startup_stage_tolerates_not_implemented_create_stage(self):
        app = self._bare_app()
        session = self._NotImplementedCreateStageSession()
        app._adapter_session = session

        stage = app._create_empty_startup_stage()

        assert stage is None
        assert len(session.create_stage_calls) == 1
        assert not os.path.exists(os.path.dirname(session.create_stage_calls[0]))
        assert app._scratch_stage_dirs == []

    def test_empty_startup_stage_tolerates_missing_create_stage_method(self):
        app = self._bare_app()
        app._adapter_session = self._LegacyNoCreateStageSession()

        stage = app._create_empty_startup_stage()

        assert stage is None
        assert app._scratch_stage_dirs == []

    def test_startup_leaves_no_active_stage_when_create_stage_is_unsupported(self):
        app = self._bare_app()
        app._adapter_session = self._UnsupportedCreateStageSession()
        app._preconstruct_ovrtx_renderer = MagicMock(
            side_effect=AssertionError("renderer should not be prebuilt")
        )
        app._load_stage = MagicMock()

        app._load_empty_startup_stage()

        app._preconstruct_ovrtx_renderer.assert_not_called()
        app._load_stage.assert_not_called()
        assert app._stage_adapter is None

    def test_startup_closes_prebuilt_renderer_when_create_stage_is_not_implemented(self):
        app = self._bare_app()
        app._adapter_session = self._NotImplementedCreateStageSession()
        prebuilt = MagicMock()
        app._preconstruct_ovrtx_renderer = MagicMock(return_value=prebuilt)
        app._load_stage = MagicMock()

        app._load_empty_startup_stage()

        app._preconstruct_ovrtx_renderer.assert_called_once_with()
        app._load_stage.assert_not_called()
        prebuilt.shutdown.assert_called_once_with()
        assert app._stage_adapter is None

    def test_public_new_stage_uses_provider_create_and_normal_load_path(self):
        app = self._bare_app()
        stage = object()
        session = self._SupportedCreateStageSession(stage)
        app._adapter_session = session
        app._current_file_path = "old.usda"
        app._undo_manager = MagicMock()
        prebuilt = MagicMock()
        app._preconstruct_ovrtx_renderer = MagicMock(return_value=prebuilt)
        app._load_stage = MagicMock()

        try:
            assert app.new_stage() is True
            assert len(session.create_stage_calls) == 1
            created_path = session.create_stage_calls[0]
            assert os.path.basename(created_path) == "NewStage.usda"
            app._load_stage.assert_called_once_with(
                stage,
                title="New Stage",
                prebuilt_renderer=prebuilt,
            )
            assert app._current_file_path is None
            app._undo_manager.clear.assert_called_once_with()
        finally:
            for stage_dir in app._scratch_stage_dirs:
                try:
                    os.rmdir(stage_dir)
                except OSError:
                    pass
            app._scratch_stage_dirs = []

    def test_new_stage_save_as_survives_scratch_cleanup(
        self,
        app,
        tmp_path,
    ):
        from ovui_data_adapters.common import (
            AdapterCapabilities,
            AdapterCapability,
            StageCapabilities,
        )

        stage = object()

        class _CreateExportSession:
            def __init__(self) -> None:
                self.source_path: pathlib.Path | None = None
                self.shutdown_saw_source = False

            def get_capabilities(self):
                return AdapterCapabilities(
                    stage=StageCapabilities(
                        create_stage=AdapterCapability.supported(),
                        export_stage=AdapterCapability.supported(),
                    )
                )

            def create_stage(self, path: str):
                self.source_path = pathlib.Path(path)
                self.source_path.write_text("#usda 1.0\n", encoding="utf-8")
                return stage

            def export_stage(self, exported_stage, path: str) -> None:
                assert exported_stage is stage
                pathlib.Path(path).write_text(
                    '#usda 1.0\ndef Xform "Saved" {}\n',
                    encoding="utf-8",
                )

            def shutdown_scene(self) -> None:
                assert self.source_path is not None
                self.shutdown_saw_source = self.source_path.is_file()

        session = _CreateExportSession()
        app._adapter_session = session
        app._startup_prebuilt_renderer = None

        def load_created_stage(loaded_stage, **_kwargs) -> None:
            assert loaded_stage is stage
            app._stage_adapter = types.SimpleNamespace(stage=loaded_stage)

        app._load_stage = MagicMock(side_effect=load_created_stage)

        assert app.new_stage() is True
        assert session.source_path is not None
        scratch_source = session.source_path
        scratch_directory = scratch_source.parent
        assert scratch_source.is_file()
        assert app._current_file_path is None

        save_as_path = tmp_path / "saved-new-stage.usda"
        assert app.save_stage_to(str(save_as_path)) is True
        assert app._current_file_path == str(save_as_path)
        assert save_as_path.is_file()

        app.shutdown()

        assert session.shutdown_saw_source is True
        assert not scratch_directory.exists()
        assert save_as_path.is_file()
        assert 'def Xform "Saved"' in save_as_path.read_text(encoding="utf-8")

    def test_public_new_stage_failure_preserves_document_and_history(self):
        app = self._bare_app()
        prior_adapter = object()
        app._stage_adapter = prior_adapter
        app._adapter_session = self._NotImplementedCreateStageSession()
        app._undo_manager = MagicMock()
        prebuilt = MagicMock()
        app._preconstruct_ovrtx_renderer = MagicMock(return_value=prebuilt)
        app._load_stage = MagicMock()

        assert app.new_stage() is False
        assert app._stage_adapter is prior_adapter
        app._load_stage.assert_not_called()
        app._undo_manager.clear.assert_not_called()
        prebuilt.shutdown.assert_called_once_with()


try:
    from pxr import Usd as _Usd  # noqa: F401
    _HAS_USD = True
except ImportError:
    _HAS_USD = False


@pytest.mark.skipif(not _HAS_USD, reason="pxr not available")
class TestEmptyStartupStage:
    """No-file startup must create a stage that follows file-open wiring."""

    def test_empty_startup_stage_uses_file_backed_root_layer(self, app):
        stage = app._create_empty_startup_stage()
        root = stage.GetRootLayer()

        assert root.anonymous is False
        assert root.realPath
        assert os.path.exists(root.realPath)
        assert os.path.basename(root.realPath) == "NewStage.usda"
        assert app._current_file_path is None

    def test_shutdown_removes_empty_startup_stage_directory(self, app):
        stage = app._create_empty_startup_stage()
        stage_dir = os.path.dirname(stage.GetRootLayer().realPath)

        assert os.path.isdir(stage_dir)

        app.shutdown()

        assert not os.path.exists(stage_dir)


@pytest.mark.skipif(not _HAS_USD, reason="pxr not available")
class TestLayerAdapterWiring:
    """LAYERS-PLAN Step 9: Application builds + wires a UsdLayerStackAdapter
    whenever a stage is loaded, stores it as ``_layer_adapter``, and hands
    the reference to the LayerWindow via ``set_adapter``."""

    def test_layer_adapter_slot_defaults_none(self, app):
        assert app._layer_adapter is None

    def test_load_stage_constructs_layer_adapter(self, app):
        from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
        from pxr import Usd

        stage = Usd.Stage.CreateInMemory()
        app.open_stage(stage)

        assert isinstance(app._layer_adapter, UsdLayerStackAdapter)

    def test_load_stage_passes_adapter_to_layer_window(self, app):
        from pxr import Usd

        # Stand in for the LayerWindow (created only in run_async).
        layer_window = MagicMock()
        app._layer_window = layer_window

        stage = Usd.Stage.CreateInMemory()
        app.open_stage(stage)

        layer_window.set_adapter.assert_called_once_with(app._layer_adapter)

    def test_reopening_stage_detaches_prior_adapter(self, app):
        from pxr import Usd

        stage1 = Usd.Stage.CreateInMemory()
        app.open_stage(stage1)
        first_adapter = app._layer_adapter
        assert first_adapter is not None
        assert first_adapter._destroyed is False

        stage2 = Usd.Stage.CreateInMemory()
        app.open_stage(stage2)

        assert app._layer_adapter is not first_adapter
        assert first_adapter._destroyed is True
        assert app._layer_adapter._destroyed is False

    def test_shutdown_detaches_layer_adapter(self, app):
        from pxr import Usd

        stage = Usd.Stage.CreateInMemory()
        app.open_stage(stage)
        adapter = app._layer_adapter
        assert adapter is not None

        app.shutdown()

        assert adapter._destroyed is True
        assert app._layer_adapter is None


class TestBoundCameraSeam:
    """Step 16: Application drives bound-camera lookup through the stage
    adapter and applies the resulting :class:`BoundCameraPose` value object
    to the viewport via the new ``apply_camera_pose`` API. The widget no
    longer accepts a raw ``Usd.Stage`` for camera metadata.

    Four cases cover the seam rule:

      1. ``stage_adapter.read_bound_camera()`` is consulted on every
         stage open.
      2. When it returns a pose AND ``viewport.apply_camera_pose(pose)``
         returns ``True``, the bbox-framing fallback is NOT called.
      3. When it returns ``None``, ``viewport.frame_paths(["/"])`` IS
         called.
      4. When it returns a pose but ``apply_camera_pose`` returns
         ``False`` (e.g., the camera setter raised), the bbox-framing
         fallback IS called.
    """

    @pytest.fixture(autouse=True)
    def _stub_renderer_build(self, monkeypatch):
        from ovui_widgets.app.application import _NO_PREBUILT_RENDERER
        from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter

        def _build_renderer_for_stage(_app, _stage, prebuilt=None):
            renderer = (
                MockRendererAdapter()
                if prebuilt is _NO_PREBUILT_RENDERER
                else prebuilt
            )
            renderer.load_stage(_stage)
            return renderer

        monkeypatch.setattr(
            Application,
            "_build_renderer_for_stage",
            _build_renderer_for_stage,
        )

    def _make_pose(self):
        from ovui_data_adapters.common import BoundCameraPose
        return BoundCameraPose(
            eye=(0.0, 3.0, 8.0),
            target=(0.0, 0.0, 0.0),
            up_axis="Y",
            fov_degrees=45.0,
            prim_path="/World/QACam",
        )

    def test_read_bound_camera_is_consulted(self, app):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Usd

        viewport = MagicMock()
        viewport.apply_camera_pose.return_value = True
        app._viewport_window = viewport

        with patch.object(UsdStageAdapter, "read_bound_camera",
                          autospec=True, return_value=None) as mock_rbc:
            stage = Usd.Stage.CreateInMemory()
            app.open_stage(stage)
            mock_rbc.assert_called()

    def test_pose_applied_skips_fallback_framing(self, app):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Usd

        viewport = MagicMock()
        viewport.apply_camera_pose.return_value = True
        app._viewport_window = viewport

        pose = self._make_pose()
        with patch.object(UsdStageAdapter, "read_bound_camera",
                          autospec=True, return_value=pose):
            stage = Usd.Stage.CreateInMemory()
            app.open_stage(stage)

        viewport.apply_camera_pose.assert_called_once_with(pose)
        # bbox-framing fallback must NOT fire when the pose was applied.
        # Note: viewport.frame_paths may legitimately be called during
        # other parts of _load_stage; the assertion is specifically that
        # the post-pose fallback path was skipped, which means
        # apply_camera_pose returned True so the ``or`` short-circuited.
        # We verify by checking ``apply_camera_pose`` returned truthy
        # (configured above) and ``frame_paths(["/"])`` was not called.
        for call in viewport.frame_paths.call_args_list:
            assert call.args != (["/"],), (
                f"frame_paths(['/']) should not run when pose was applied; "
                f"unexpected call: {call}"
            )

    def test_no_pose_falls_back_to_frame_paths(self, app):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Usd

        viewport = MagicMock()
        # apply_camera_pose return value is irrelevant when pose is None
        # (the ``or`` short-circuits before the call).
        app._viewport_window = viewport

        with patch.object(UsdStageAdapter, "read_bound_camera",
                          autospec=True, return_value=None):
            stage = Usd.Stage.CreateInMemory()
            app.open_stage(stage)

        # The new seam: pose is None → frame_paths(["/"]) is the bbox
        # fallback. apply_camera_pose may or may not be called depending
        # on the precise expression evaluation; the expected behavior is that the
        # bbox fallback fires.
        viewport.frame_paths.assert_any_call(["/"])

    def test_apply_pose_failure_falls_back_to_frame_paths(self, app):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Usd

        viewport = MagicMock()
        viewport.apply_camera_pose.return_value = False  # apply failed
        app._viewport_window = viewport

        pose = self._make_pose()
        with patch.object(UsdStageAdapter, "read_bound_camera",
                          autospec=True, return_value=pose):
            stage = Usd.Stage.CreateInMemory()
            app.open_stage(stage)

        viewport.apply_camera_pose.assert_called_once_with(pose)
        # apply returned False → bbox fallback must fire.
        viewport.frame_paths.assert_any_call(["/"])

    def test_viewport_widget_has_no_set_camera_from_stage_metadata(self):
        from ovui_widgets.viewport.viewport_widget import ViewportWidget
        # Step 16: the raw-stage entry point is gone.
        assert not hasattr(ViewportWidget, "set_camera_from_stage_metadata")
        # And the new pose-based entry point is present.
        assert hasattr(ViewportWidget, "apply_camera_pose")


class TestDeleteSelectedClearsSelection:
    """Codex final-UI-QA rerun (2026-05-08) regression backstop.

    After ``Application._delete_selected`` removes a prim, the
    ``SelectionBus`` must not still point at the now-invalid path —
    otherwise downstream consumers (Stage tree, Property panel, status
    bar) iterate the stale selection on the next ``call_later`` notice
    flush and raise ``RuntimeError: Accessed invalid null prim``.
    Codex captured this on `tests/data/simple_scene.usda` →
    `/World/Cube`. The fix clears the selection bus before the
    deletion runs (via a ``Command`` first in the undo group); undo
    restores the selection AFTER prims are restored.
    """

    @pytest.fixture
    def app_with_simple_scene(self, tmp_path):
        pytest.importorskip("pxr", reason="pxr not available")
        import os
        import shutil

        from pxr import Usd

        application = Application()
        try:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            fixture = os.path.join(repo_root, "tests", "data", "simple_scene.usda")
            fixture_copy = tmp_path / "simple_scene.usda"
            shutil.copyfile(fixture, fixture_copy)
            stage = Usd.Stage.Open(str(fixture_copy))
            application.open_stage(stage)
            yield application
        finally:
            application.shutdown()

    def test_delete_clears_selection_bus(self, app_with_simple_scene):
        """After Delete, the selection bus must be empty so consumers
        don't iterate the deleted prim's path on the next notice flush."""
        app = app_with_simple_scene
        # Publish a selection on /World/Cube the way the Stage tree would.
        app.selection_bus.publish(["/World/Cube"], source="stage")
        snap_before = app.selection_bus.get_snapshot()
        assert [item.path for item in snap_before.items] == ["/World/Cube"]

        app._delete_selected()

        # Live stage no longer has the prim.
        cube = app._stage_adapter.stage.GetPrimAtPath("/World/Cube")
        assert not cube.IsValid()
        # Selection bus is empty — consumers won't access the stale path.
        snap_after = app.selection_bus.get_snapshot()
        assert snap_after.items == ()

    def test_undo_restores_both_prim_and_selection(self, app_with_simple_scene):
        """Undo must restore the prim AND the selection bus state, in
        the right order (prim first, then selection — otherwise the
        re-published selection points at an invalid prim again).
        """
        app = app_with_simple_scene
        app.selection_bus.publish(["/World/Cube"], source="stage")
        app._delete_selected()
        assert not app._stage_adapter.stage.GetPrimAtPath("/World/Cube").IsValid()
        assert app.selection_bus.get_snapshot().items == ()

        ok = app._undo_manager.undo()
        assert ok

        # Prim restored.
        cube = app._stage_adapter.stage.GetPrimAtPath("/World/Cube")
        assert cube.IsValid()
        # Selection restored.
        snap = app.selection_bus.get_snapshot()
        assert [item.path for item in snap.items] == ["/World/Cube"]
        # And the restored selection points at a VALID prim.
        for item in snap.items:
            assert app._stage_adapter.stage.GetPrimAtPath(item.path).IsValid()

    def test_delete_then_immediate_call_later_does_not_access_invalid_prim(
        self, app_with_simple_scene
    ):
        """Direct backstop for the Codex `RuntimeError: Accessed invalid
        null prim` callback error: any subscriber that reads the
        selection on the post-Delete tick must NOT see the deleted
        path. This tests the rule structurally — there is no
        selected path that resolves to an invalid prim.
        """
        app = app_with_simple_scene
        app.selection_bus.publish(["/World/Cube"], source="stage")
        app._delete_selected()

        # The rule: every path still in the selection bus must
        # resolve to a valid prim. With the fix this is trivially
        # true (selection is empty); without the fix the bus would
        # report ["/World/Cube"] which resolves to an invalid prim.
        for item in app.selection_bus.get_snapshot().items:
            prim = app._stage_adapter.stage.GetPrimAtPath(item.path)
            assert prim.IsValid(), (
                f"selection bus retained an invalid prim path "
                f"{item.path!r} after Delete"
            )
