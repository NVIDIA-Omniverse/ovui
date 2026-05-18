# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for drag-and-drop file open — OvGear Step 68.

Covers: _on_drop with all valid USD extensions, invalid extension warning,
empty path no-op, case-insensitive matching, and _register_drop_handler
graceful degradation when set_drop_fn is absent.
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeEvent:
    """Minimal drop event with a mime_data attribute."""

    def __init__(self, path: str) -> None:
        self.mime_data = path


# ---------------------------------------------------------------------------
# _on_drop — extension dispatch
# ---------------------------------------------------------------------------

class TestOnDropValidExtensions:
    """Valid USD extensions must call open_file."""

    @pytest.mark.parametrize("ext", [".usd", ".usda", ".usdc", ".usdz"])
    def test_lowercase_extension_calls_open_file(self, headless_app, ext):
        path = f"/tmp/model{ext}"
        headless_app.open_file = MagicMock()
        headless_app._on_drop(_FakeEvent(path))
        headless_app.open_file.assert_called_once_with(path)

    @pytest.mark.parametrize("ext", [".USD", ".USDA", ".USDC", ".USDZ"])
    def test_uppercase_extension_calls_open_file(self, headless_app, ext):
        path = f"/tmp/model{ext}"
        headless_app.open_file = MagicMock()
        headless_app._on_drop(_FakeEvent(path))
        headless_app.open_file.assert_called_once_with(path)

    @pytest.mark.parametrize("ext", [".Usd", ".Usda", ".Usdc", ".Usdz"])
    def test_mixed_case_extension_calls_open_file(self, headless_app, ext):
        path = f"/tmp/model{ext}"
        headless_app.open_file = MagicMock()
        headless_app._on_drop(_FakeEvent(path))
        headless_app.open_file.assert_called_once_with(path)

    def test_path_with_directory_components(self, headless_app):
        path = "/home/user/assets/scene.usda"
        headless_app.open_file = MagicMock()
        headless_app._on_drop(_FakeEvent(path))
        headless_app.open_file.assert_called_once_with(path)

    def test_open_file_not_called_twice(self, headless_app):
        path = "/tmp/model.usd"
        headless_app.open_file = MagicMock()
        headless_app._on_drop(_FakeEvent(path))
        assert headless_app.open_file.call_count == 1


class TestOnDropInvalidExtensions:
    """Non-USD extensions must show a warning and NOT call open_file."""

    @pytest.mark.parametrize("ext", [".png", ".jpg", ".obj", ".fbx", ".abc", ".mp4", ".txt"])
    def test_invalid_extension_shows_warning(self, headless_app, ext):
        path = f"/tmp/file{ext}"
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeEvent(path))
        headless_app.open_file.assert_not_called()
        mock_show.assert_called_once()

    def test_warning_message_contains_extension(self, headless_app):
        path = "/tmp/image.png"
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeEvent(path))
        msg = mock_show.call_args[0][0]
        assert ".png" in msg

    def test_warning_uses_warning_level(self, headless_app):
        path = "/tmp/image.png"
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeEvent(path))
        kwargs = mock_show.call_args[1]
        assert kwargs.get("level") == "warning"

    def test_no_extension_shows_warning(self, headless_app):
        path = "/tmp/noextension"
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeEvent(path))
        headless_app.open_file.assert_not_called()
        mock_show.assert_called_once()


class TestOnDropEdgeCases:
    """Edge cases: empty path, None, missing attribute."""

    def test_empty_mime_data_is_noop(self, headless_app):
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeEvent(""))
        headless_app.open_file.assert_not_called()
        mock_show.assert_not_called()

    def test_none_mime_data_is_noop(self, headless_app):
        headless_app.open_file = MagicMock()
        event = MagicMock()
        event.mime_data = None
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(event)
        headless_app.open_file.assert_not_called()
        mock_show.assert_not_called()

    def test_event_without_mime_data_is_noop(self, headless_app):
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(object())
        headless_app.open_file.assert_not_called()
        mock_show.assert_not_called()

    def test_usd_like_but_wrong_suffix(self, headless_app):
        """'.usdx' is not a valid USD extension."""
        path = "/tmp/model.usdx"
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeEvent(path))
        headless_app.open_file.assert_not_called()
        mock_show.assert_called_once()


# ---------------------------------------------------------------------------
# _register_drop_handler — graceful degradation
# ---------------------------------------------------------------------------

class TestRegisterDropHandler:
    def test_no_crash_when_set_drop_fn_absent(self, headless_app):
        """Main window without set_drop_fn — _register_drop_handler must not raise."""
        win = MagicMock(spec=[])  # spec=[] means no attributes
        headless_app._main_win = win
        headless_app._register_drop_handler()  # must not raise

    def test_set_drop_fn_called_when_present(self, headless_app):
        win = MagicMock()
        headless_app._main_win = win
        headless_app._register_drop_handler()
        win.set_drop_fn.assert_called_once_with(headless_app._on_drop)

    def test_no_crash_when_main_win_is_none(self, headless_app):
        headless_app._main_win = None
        headless_app._register_drop_handler()  # must not raise

    def test_usd_extensions_constant_has_all_four(self):
        from ovwidgets.app.application import Application
        for ext in (".usd", ".usda", ".usdc", ".usdz"):
            assert ext in Application._USD_EXTENSIONS

    def test_usd_extensions_are_lowercase(self):
        from ovwidgets.app.application import Application
        for ext in Application._USD_EXTENSIONS:
            assert ext == ext.lower()
