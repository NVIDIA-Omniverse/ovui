# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ErrorReporter and StatusBar.

Step 7: log_error/log_warning/log_info (stderr), show_status/show_error/
show_warning/show_success (stderr fallback or StatusBar), and the StatusBar
widget itself (requires omni.ui — skipped if unavailable).

Step 56: initialize(), show_status() with direct label + color coding,
auto-dismiss timer, timer cancellation, graceful no-op when uninitialized.
"""


import omni.ui as ui
import pytest
from omni.ui import color as cl

from ovwidgets.common.error_reporter import ErrorReporter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _reset_reporter():
    """Reset all ErrorReporter class-level state."""
    ErrorReporter._clear_status_bar()  # clears _status_bar, _status_label, _app, handle


@pytest.fixture(autouse=True)
def reset_status_bar():
    """Ensure ErrorReporter is fully reset before and after each test."""
    _reset_reporter()
    yield
    _reset_reporter()


class MockStatusBar:
    """Minimal stand-in for StatusBar to test ErrorReporter integration."""

    def __init__(self):
        self.calls = []

    def show_message(self, text: str, duration_ms: int, level: str) -> None:
        self.calls.append((text, duration_ms, level))


class MockLabel:
    """Minimal stand-in for ui.Label."""

    def __init__(self):
        self.text = ""
        self._styles = []

    def set_style(self, style: dict) -> None:
        self._styles.append(style)

    @property
    def last_style(self):
        return self._styles[-1] if self._styles else None


class MockHandle:
    """Minimal stand-in for CallbackHandle."""

    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class MockApp:
    """Minimal stand-in for Application providing call_later()."""

    def __init__(self):
        self.scheduled = []  # list of (delay_secs, callback)

    def call_later(self, delay_secs: float, callback) -> MockHandle:
        handle = MockHandle()
        self.scheduled.append((delay_secs, callback, handle))
        return handle

    def fire_all(self):
        """Fire all scheduled callbacks immediately."""
        for _, cb, _ in self.scheduled:
            cb()
        self.scheduled = []


# ---------------------------------------------------------------------------
# Part A: log_error
# ---------------------------------------------------------------------------

class TestLogError:
    def test_outputs_to_stderr(self, capfd):
        ErrorReporter.log_error("Mod", "something broke")
        err = capfd.readouterr().err
        assert err  # non-empty

    def test_includes_module_name(self, capfd):
        ErrorReporter.log_error("MyModule", "oops")
        err = capfd.readouterr().err
        assert "MyModule" in err

    def test_includes_message(self, capfd):
        ErrorReporter.log_error("Mod", "specific failure text")
        err = capfd.readouterr().err
        assert "specific failure text" in err

    def test_error_prefix(self, capfd):
        ErrorReporter.log_error("Mod", "msg")
        err = capfd.readouterr().err
        assert "[ERROR]" in err

    def test_with_exception_includes_exc_type(self, capfd):
        exc = ValueError("bad value")
        ErrorReporter.log_error("Mod", "msg", exc=exc)
        err = capfd.readouterr().err
        assert "ValueError" in err

    def test_with_exception_includes_exc_message(self, capfd):
        exc = RuntimeError("runtime problem")
        ErrorReporter.log_error("Mod", "msg", exc=exc)
        err = capfd.readouterr().err
        assert "runtime problem" in err

    def test_without_exception_no_exception_line(self, capfd):
        ErrorReporter.log_error("Mod", "msg")
        err = capfd.readouterr().err
        assert "Exception:" not in err

    def test_no_output_to_stdout(self, capfd):
        ErrorReporter.log_error("Mod", "msg")
        out = capfd.readouterr().out
        assert out == ""


# ---------------------------------------------------------------------------
# Part B: log_warning
# ---------------------------------------------------------------------------

class TestLogWarning:
    def test_outputs_to_stderr(self, capfd):
        ErrorReporter.log_warning("Mod", "watch out")
        err = capfd.readouterr().err
        assert err

    def test_warning_prefix(self, capfd):
        ErrorReporter.log_warning("Mod", "msg")
        err = capfd.readouterr().err
        assert "[WARNING]" in err

    def test_includes_module(self, capfd):
        ErrorReporter.log_warning("WarnModule", "msg")
        err = capfd.readouterr().err
        assert "WarnModule" in err

    def test_includes_message(self, capfd):
        ErrorReporter.log_warning("Mod", "careful here")
        err = capfd.readouterr().err
        assert "careful here" in err

    def test_no_stdout(self, capfd):
        ErrorReporter.log_warning("Mod", "msg")
        assert capfd.readouterr().out == ""


# ---------------------------------------------------------------------------
# Part C: log_info
# ---------------------------------------------------------------------------

class TestLogInfo:
    def test_outputs_to_stderr(self, capfd):
        ErrorReporter.log_info("Mod", "information")
        err = capfd.readouterr().err
        assert err

    def test_info_prefix(self, capfd):
        ErrorReporter.log_info("Mod", "msg")
        err = capfd.readouterr().err
        assert "[INFO]" in err

    def test_includes_module(self, capfd):
        ErrorReporter.log_info("InfoModule", "msg")
        err = capfd.readouterr().err
        assert "InfoModule" in err

    def test_includes_message(self, capfd):
        ErrorReporter.log_info("Mod", "detail info")
        err = capfd.readouterr().err
        assert "detail info" in err

    def test_no_stdout(self, capfd):
        ErrorReporter.log_info("Mod", "msg")
        assert capfd.readouterr().out == ""


# ---------------------------------------------------------------------------
# Part D: show_status without StatusBar (stderr fallback)
# ---------------------------------------------------------------------------

class TestShowStatusNoBar:
    def test_falls_back_to_stderr(self, capfd):
        ErrorReporter.show_status("hello")
        err = capfd.readouterr().err
        assert "hello" in err

    def test_includes_level_in_output(self, capfd):
        ErrorReporter.show_status("msg", level="error")
        err = capfd.readouterr().err
        assert "error" in err

    def test_no_level_shows_info(self, capfd):
        ErrorReporter.show_status("msg")
        err = capfd.readouterr().err
        assert "info" in err

    def test_includes_message_text(self, capfd):
        ErrorReporter.show_status("my status message")
        err = capfd.readouterr().err
        assert "my status message" in err

    def test_no_stdout(self, capfd):
        ErrorReporter.show_status("msg")
        assert capfd.readouterr().out == ""

    def test_show_error_fallback(self, capfd):
        ErrorReporter.show_error("error text")
        err = capfd.readouterr().err
        assert "error text" in err
        assert "error" in err

    def test_show_warning_fallback(self, capfd):
        ErrorReporter.show_warning("warn text")
        err = capfd.readouterr().err
        assert "warn text" in err
        assert "warning" in err

    def test_show_success_fallback(self, capfd):
        ErrorReporter.show_success("success text")
        err = capfd.readouterr().err
        assert "success text" in err
        assert "success" in err


# ---------------------------------------------------------------------------
# Part E: show_status with mock StatusBar (legacy API)
# ---------------------------------------------------------------------------

class TestShowStatusWithBar:
    def test_calls_show_message(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_status("hello", 2000, "info")
        assert len(mock.calls) == 1
        assert mock.calls[0] == ("hello", 2000, "info")

    def test_does_not_write_stderr(self, capfd):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_status("msg")
        assert capfd.readouterr().err == ""

    def test_show_error_passes_level_error(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_error("err msg")
        assert mock.calls[0][2] == "error"

    def test_show_error_uses_5000ms_default(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_error("err msg")
        assert mock.calls[0][1] == 5000

    def test_show_warning_passes_level_warning(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_warning("warn msg")
        assert mock.calls[0][2] == "warning"

    def test_show_warning_uses_4000ms_default(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_warning("warn msg")
        assert mock.calls[0][1] == 4000

    def test_show_success_passes_level_success(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_success("ok msg")
        assert mock.calls[0][2] == "success"

    def test_show_success_uses_3000ms_default(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_success("ok msg")
        assert mock.calls[0][1] == 3000

    def test_custom_duration_forwarded(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_status("msg", 9999, "")
        assert mock.calls[0][1] == 9999

    def test_multiple_calls_all_forwarded(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_status("a")
        ErrorReporter.show_status("b")
        ErrorReporter.show_status("c")
        assert len(mock.calls) == 3


# ---------------------------------------------------------------------------
# Part F: _set_status_bar / _clear_status_bar lifecycle
# ---------------------------------------------------------------------------

class TestStatusBarLifecycle:
    def test_initially_none(self):
        assert ErrorReporter._status_bar is None

    def test_set_status_bar(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        assert ErrorReporter._status_bar is mock

    def test_clear_status_bar(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter._clear_status_bar()
        assert ErrorReporter._status_bar is None

    def test_after_clear_falls_back_to_stderr(self, capfd):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter._clear_status_bar()
        ErrorReporter.show_status("fallback msg")
        err = capfd.readouterr().err
        assert "fallback msg" in err
        assert mock.calls == []

    def test_replace_status_bar(self):
        mock1 = MockStatusBar()
        mock2 = MockStatusBar()
        ErrorReporter._set_status_bar(mock1)
        ErrorReporter._set_status_bar(mock2)
        ErrorReporter.show_status("msg")
        assert mock1.calls == []
        assert len(mock2.calls) == 1

    def test_clear_idempotent(self):
        ErrorReporter._clear_status_bar()
        ErrorReporter._clear_status_bar()
        assert ErrorReporter._status_bar is None


# ---------------------------------------------------------------------------
# Part G: StatusBar widget (requires omni.ui)
# ---------------------------------------------------------------------------

try:
    import omni.ui as ui
    _OMNI_UI_AVAILABLE = True
except ImportError:
    _OMNI_UI_AVAILABLE = False


@pytest.mark.skipif(not _OMNI_UI_AVAILABLE, reason="omni.ui not available")
class TestStatusBarWidget:
    def _make_bar(self):
        from ovwidgets.app.status_bar import StatusBar
        frame = ui.Frame()
        return StatusBar(frame), frame

    def test_instantiates(self):
        from ovwidgets.app.status_bar import StatusBar
        frame = ui.Frame()
        bar = StatusBar(frame)
        assert bar is not None

    def test_label_initially_empty(self):
        bar, _ = self._make_bar()
        assert bar._label is not None
        assert bar._label.text == ""

    def test_show_message_sets_text(self):
        bar, _ = self._make_bar()
        bar.show_message("Loading…")
        assert bar._label.text == "Loading…"

    def test_show_message_sets_level_name(self):
        bar, _ = self._make_bar()
        bar.show_message("Oops", level="error")
        assert bar._label.name == "error"

    def test_show_message_warning_level(self):
        bar, _ = self._make_bar()
        bar.show_message("Careful", level="warning")
        assert bar._label.name == "warning"

    def test_show_message_success_level(self):
        bar, _ = self._make_bar()
        bar.show_message("Done", level="success")
        assert bar._label.name == "success"

    def test_show_message_no_level_clears_name(self):
        bar, _ = self._make_bar()
        bar.show_message("Info msg", level="error")
        bar.show_message("Info msg")
        assert bar._label.name == ""

    def test_clear_resets_text(self):
        bar, _ = self._make_bar()
        bar.show_message("something")
        bar.clear()
        assert bar._label.text == ""

    def test_clear_resets_name(self):
        bar, _ = self._make_bar()
        bar.show_message("x", level="error")
        bar.clear()
        assert bar._label.name == ""

    def test_show_message_empty_string(self):
        bar, _ = self._make_bar()
        bar.show_message("")
        assert bar._label.text == ""

    def test_show_message_does_not_raise_with_null_label(self):
        from ovwidgets.app.status_bar import StatusBar
        frame = ui.Frame()
        bar = StatusBar(frame)
        bar._label = None
        bar.show_message("should not raise")

    def test_clear_does_not_raise_with_null_label(self):
        from ovwidgets.app.status_bar import StatusBar
        frame = ui.Frame()
        bar = StatusBar(frame)
        bar._label = None
        bar.clear()

    def test_label_height_is_24(self):
        bar, _ = self._make_bar()
        assert bar._label.height.value == 24

    def test_label_style_type_name_override(self):
        bar, _ = self._make_bar()
        # style_type_name_override is a constructor arg; verify label has the right style
        # We can only check that the widget was built without error and has a label
        assert bar._label is not None


# ---------------------------------------------------------------------------
# Part H: initialize() and direct label manipulation (Step 56 API)
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_initialize_stores_app(self):
        app = MockApp()
        label = MockLabel()
        ErrorReporter.initialize(app, label)
        assert ErrorReporter._app is app

    def test_initialize_stores_label(self):
        app = MockApp()
        label = MockLabel()
        ErrorReporter.initialize(app, label)
        assert ErrorReporter._status_label is label

    def test_initialize_with_none_clears_state(self):
        ErrorReporter.initialize(None, None)
        assert ErrorReporter._app is None
        assert ErrorReporter._status_label is None

    def test_initialize_replaces_previous(self):
        app1 = MockApp()
        app2 = MockApp()
        label = MockLabel()
        ErrorReporter.initialize(app1, label)
        ErrorReporter.initialize(app2, label)
        assert ErrorReporter._app is app2


# ---------------------------------------------------------------------------
# Part I: show_status with initialized label
# ---------------------------------------------------------------------------

class TestShowStatusWithLabel:
    def setup_method(self):
        self.app = MockApp()
        self.label = MockLabel()
        ErrorReporter.initialize(self.app, self.label)

    def test_sets_label_text(self):
        ErrorReporter.show_status("hello world")
        assert self.label.text == "hello world"

    def test_default_level_uses_text_primary_color(self):
        ui.set_shade("default")
        ErrorReporter.show_status("msg")
        assert self.label.last_style == {"color": cl.text_primary}

    def test_error_level_uses_status_error_color(self):
        ui.set_shade("default")
        ErrorReporter.show_status("msg", level="error")
        assert self.label.last_style == {"color": cl.status_error}

    def test_warning_level_uses_status_warning_color(self):
        ui.set_shade("default")
        ErrorReporter.show_status("msg", level="warning")
        assert self.label.last_style == {"color": cl.status_warning}

    def test_success_level_uses_status_success_color(self):
        ui.set_shade("default")
        ErrorReporter.show_status("msg", level="success")
        assert self.label.last_style == {"color": cl.status_success}

    def test_unknown_level_falls_back_to_text_primary(self):
        ui.set_shade("default")
        ErrorReporter.show_status("msg", level="banana")
        assert self.label.last_style == {"color": cl.text_primary}

    def test_show_error_uses_error_level(self):
        ui.set_shade("default")
        ErrorReporter.show_error("err")
        assert self.label.last_style == {"color": cl.status_error}

    def test_show_error_default_5000ms_schedules_dismiss(self):
        ErrorReporter.show_error("err")
        assert len(self.app.scheduled) == 1
        delay, _, _ = self.app.scheduled[0]
        assert abs(delay - 5.0) < 0.001

    def test_does_not_write_stderr(self, capfd):
        ErrorReporter.show_status("msg")
        assert capfd.readouterr().err == ""

    def test_prefers_label_over_status_bar(self):
        mock_bar = MockStatusBar()
        ErrorReporter._set_status_bar(mock_bar)
        ErrorReporter.show_status("msg")
        assert self.label.text == "msg"
        assert mock_bar.calls == []


# ---------------------------------------------------------------------------
# Part J: auto-dismiss behavior
# ---------------------------------------------------------------------------

class TestAutoDismiss:
    def setup_method(self):
        self.app = MockApp()
        self.label = MockLabel()
        ErrorReporter.initialize(self.app, self.label)

    def test_positive_duration_schedules_dismiss(self):
        ErrorReporter.show_status("msg", duration_ms=3000)
        assert len(self.app.scheduled) == 1

    def test_zero_duration_no_dismiss_scheduled(self):
        ErrorReporter.show_status("msg", duration_ms=0)
        assert len(self.app.scheduled) == 0

    def test_dismiss_delay_in_seconds(self):
        ErrorReporter.show_status("msg", duration_ms=2500)
        delay, _, _ = self.app.scheduled[0]
        assert abs(delay - 2.5) < 0.001

    def test_dismiss_clears_label_text(self):
        ErrorReporter.show_status("msg", duration_ms=1000)
        _, dismiss_fn, _ = self.app.scheduled[0]
        assert self.label.text == "msg"
        dismiss_fn()
        assert self.label.text == ""

    def test_dismiss_clears_handle(self):
        ErrorReporter.show_status("msg", duration_ms=1000)
        _, dismiss_fn, _ = self.app.scheduled[0]
        dismiss_fn()
        assert ErrorReporter._dismiss_handle is None


# ---------------------------------------------------------------------------
# Part K: timer cancellation
# ---------------------------------------------------------------------------

class TestTimerCancellation:
    def setup_method(self):
        self.app = MockApp()
        self.label = MockLabel()
        ErrorReporter.initialize(self.app, self.label)

    def test_second_message_cancels_first_handle(self):
        ErrorReporter.show_status("first", duration_ms=3000)
        _, _, first_handle = self.app.scheduled[0]
        ErrorReporter.show_status("second", duration_ms=3000)
        assert first_handle.cancelled

    def test_second_message_schedules_new_handle(self):
        ErrorReporter.show_status("first", duration_ms=3000)
        ErrorReporter.show_status("second", duration_ms=3000)
        assert len(self.app.scheduled) == 2

    def test_second_message_sets_new_text(self):
        ErrorReporter.show_status("first", duration_ms=3000)
        ErrorReporter.show_status("second", duration_ms=3000)
        assert self.label.text == "second"

    def test_zero_duration_does_not_cancel_nothing(self):
        # No prior handle — no crash
        ErrorReporter.show_status("msg", duration_ms=0)
        assert ErrorReporter._dismiss_handle is None

    def test_existing_handle_cancelled_on_zero_duration(self):
        ErrorReporter.show_status("first", duration_ms=3000)
        _, _, first_handle = self.app.scheduled[0]
        ErrorReporter.show_status("second", duration_ms=0)
        assert first_handle.cancelled
        assert ErrorReporter._dismiss_handle is None


# ---------------------------------------------------------------------------
# Part L: graceful no-op when not initialized
# ---------------------------------------------------------------------------

class TestNoOpWhenUninitialized:
    def test_show_status_falls_back_to_stderr_not_raises(self, capfd):
        # _status_label is None — must not raise
        ErrorReporter.show_status("msg")
        err = capfd.readouterr().err
        assert "msg" in err

    def test_clear_status_does_not_raise(self):
        ErrorReporter._clear_status()

    def test_clear_status_clears_handle(self):
        # If somehow a handle exists but label is None — handle is cleared safely
        ErrorReporter._dismiss_handle = MockHandle()
        ErrorReporter._clear_status()
        assert ErrorReporter._dismiss_handle is None


# ---------------------------------------------------------------------------
# Part M: integration with real Application class
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Part N: BUG-001 — status text sanitization for multi-line / long strings.
# The ovrtx renderer failure carries a multi-line RuntimeError into
# show_warning, which used to wrap vertically inside the overlay label
# and bleed over the Property Inspector. ErrorReporter now flattens
# whitespace and truncates so the label stays single-line.
# ---------------------------------------------------------------------------

class TestSanitizeStatusText:
    def test_empty_returns_empty(self):
        assert ErrorReporter._sanitize_status_text("") == ""

    def test_plain_text_unchanged(self):
        assert ErrorReporter._sanitize_status_text("hello") == "hello"

    def test_newline_collapsed_to_space(self):
        out = ErrorReporter._sanitize_status_text("line one\nline two")
        assert "\n" not in out
        assert out == "line one line two"

    def test_crlf_and_tabs_collapsed(self):
        out = ErrorReporter._sanitize_status_text("a\r\nb\tc\n\nd")
        assert "\n" not in out
        assert "\t" not in out
        assert out == "a b c d"

    def test_runs_of_whitespace_collapsed(self):
        assert ErrorReporter._sanitize_status_text("x    y     z") == "x y z"

    def test_long_text_truncated_with_ellipsis(self):
        src = "x" * 300
        out = ErrorReporter._sanitize_status_text(src)
        assert len(out) <= ErrorReporter._STATUS_MAX_LEN
        assert out.endswith("\u2026")

    def test_short_text_keeps_ellipsis_free(self):
        out = ErrorReporter._sanitize_status_text("short")
        assert not out.endswith("\u2026")

    def test_threshold_boundary_not_truncated(self):
        src = "y" * ErrorReporter._STATUS_MAX_LEN
        out = ErrorReporter._sanitize_status_text(src)
        assert out == src
        assert not out.endswith("\u2026")

    def test_threshold_plus_one_truncated(self):
        src = "y" * (ErrorReporter._STATUS_MAX_LEN + 1)
        out = ErrorReporter._sanitize_status_text(src)
        assert len(out) <= ErrorReporter._STATUS_MAX_LEN
        assert out.endswith("\u2026")


class TestShowStatusWithLabelSanitized:
    """show_status writes the sanitized form to the label, not the raw."""

    def setup_method(self):
        self.app = MockApp()
        self.label = MockLabel()
        ErrorReporter.initialize(self.app, self.label)

    def teardown_method(self):
        ErrorReporter._clear_status_bar()

    def test_multiline_message_flattened_before_label_set(self):
        ErrorReporter.show_status("first line\nsecond\nthird")
        assert self.label.text == "first line second third"
        assert "\n" not in self.label.text

    def test_long_message_truncated_on_label(self):
        ErrorReporter.show_status("z" * 500)
        assert len(self.label.text) <= ErrorReporter._STATUS_MAX_LEN
        assert self.label.text.endswith("\u2026")

    def test_ovrtx_style_error_stays_single_line(self):
        msg = (
            "ovrtx renderer failed (RuntimeError: Failed to load "
            "libovrtx-dynamic.so. Tried:\n"
            "  <path-to-ovgear>/libovrtx-dynamic.so\n"
            "  <path-to-ovui>/python/omni/ui/libovrtx-dynamic.so\n"
            "  /usr/bin/libovrtx-dynamic.so)"
        )
        ErrorReporter.show_warning(msg)
        assert "\n" not in self.label.text
        assert len(self.label.text) <= ErrorReporter._STATUS_MAX_LEN


class TestShowStatusWithBarSanitized:
    """show_status also sanitizes text forwarded to the legacy StatusBar."""

    def test_multiline_forwarded_flat(self):
        mock = MockStatusBar()
        ErrorReporter._set_status_bar(mock)
        ErrorReporter.show_status("a\nb\nc")
        assert mock.calls[0][0] == "a b c"


class TestIntegrationWithApplication:
    """Verify ErrorReporter wires correctly to real Application.call_later()."""

    @pytest.fixture(autouse=True)
    def reset_app(self):
        from ovwidgets.app.application import Application
        from ovwidgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None
        yield
        if Application._instance is not None:
            Application._instance = None
        SelectionBus._instance = None

    def test_initialize_with_real_app_and_mock_label(self):
        from ovwidgets.app.application import Application
        app = Application()
        label = MockLabel()
        ErrorReporter.initialize(app, label)

        ErrorReporter.show_status("test msg", duration_ms=1000)
        assert label.text == "test msg"
        assert len(app._pending_callbacks) == 1
        app.shutdown()

    def test_show_error_schedules_5s_dismiss(self):
        import time

        from ovwidgets.app.application import Application
        app = Application()
        label = MockLabel()
        ErrorReporter.initialize(app, label)

        ErrorReporter.show_error("oops")
        assert label.last_style == {"color": cl.status_error}
        assert len(app._pending_callbacks) == 1
        handle = app._pending_callbacks[0]
        expected_due = time.monotonic() + 5.0
        assert abs(handle._due_time - expected_due) < 0.1
        app.shutdown()

    def test_clear_status_bar_resets_on_shutdown(self):
        from ovwidgets.app.application import Application
        app = Application()
        label = MockLabel()
        ErrorReporter.initialize(app, label)
        app.shutdown()
        ErrorReporter._clear_status_bar()
        assert ErrorReporter._status_label is None
        assert ErrorReporter._app is None
