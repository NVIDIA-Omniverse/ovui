# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Warning-path tests for ``Application._preconstruct_ovrtx_renderer``.

When ``ovrtx`` is unavailable (``renderer_adapter.AVAILABLE is False``) and
fallback is explicitly enabled, ``_preconstruct_ovrtx_renderer`` must:

  - Call ``ErrorReporter.show_warning`` with a message that mentions
    BOTH the import error type name (``ImportError``) AND the import
    error's message text (``synthetic``).
  - Return ``None``.

These tests patch the concrete OpenUSD renderer module that the selected
common provider session reads, while also proving the production app path
goes through ``Application.get_adapter_session()`` instead of importing a
concrete provider.
"""

import inspect
from unittest.mock import patch

import pytest

from ovui_widgets.app.application import Application
from ovui_widgets.common.selection import SelectionBus


@pytest.fixture(autouse=True)
def _reset_application_singleton():
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    application = Application()
    yield application
    application.shutdown()


def _stub_provider_renderer_unavailable(monkeypatch, error: BaseException) -> None:
    """Replace the renderer_adapter module's ``AVAILABLE`` flag and
    ``_OVRTX_IMPORT_ERROR`` so the warning path is exercised.

    Mutates the actual module so the selected common provider session sees
    the synthetic unavailable state. ``monkeypatch`` reverts both setattr
    calls when the test finishes.
    """
    from ovui_data_adapters.openusd import renderer_adapter
    monkeypatch.setattr(renderer_adapter, "AVAILABLE", False)
    monkeypatch.setattr(renderer_adapter, "_OVRTX_IMPORT_ERROR", error)


class TestPreconstructWarningPath:
    """ovrtx-unavailable warning path through the selected provider session."""

    def test_unavailable_emits_warning_with_error_type_and_message(self, app, monkeypatch):
        synthetic = ImportError("synthetic")
        _stub_provider_renderer_unavailable(monkeypatch, synthetic)
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

        with patch(
            "ovui_widgets.common.error_reporter.ErrorReporter.show_warning"
        ) as mock_warn:
            result = app._preconstruct_ovrtx_renderer()

        assert result is None
        mock_warn.assert_called_once()
        msg = mock_warn.call_args.args[0]
        assert "ImportError" in msg, (
            f"warning message must include the error type name; got: {msg!r}"
        )
        assert "synthetic" in msg, (
            f"warning message must include the error message text; got: {msg!r}"
        )

    def test_unavailable_with_no_error_falls_back_to_default_reason(self, app, monkeypatch):
        # When AVAILABLE is False but _OVRTX_IMPORT_ERROR is None, the
        # warning still fires with the documented fallback text.
        from ovui_data_adapters.openusd import renderer_adapter
        monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")
        monkeypatch.setattr(renderer_adapter, "AVAILABLE", False)
        monkeypatch.setattr(renderer_adapter, "_OVRTX_IMPORT_ERROR", None)

        with patch(
            "ovui_widgets.common.error_reporter.ErrorReporter.show_warning"
        ) as mock_warn:
            result = app._preconstruct_ovrtx_renderer()

        assert result is None
        mock_warn.assert_called_once()
        msg = mock_warn.call_args.args[0]
        assert "ovrtx not available" in msg, (
            f"fallback warning text expected; got: {msg!r}"
        )

    def test_preconstruct_uses_common_provider_session(self, app):
        import ovui_widgets.app.application as app_mod

        class FakeSession:
            def __init__(self) -> None:
                self.calls: list[str] = []
                self.renderer = object()

            def renderer_available(self) -> bool:
                self.calls.append("renderer_available")
                return True

            def renderer_unavailable_reason(self) -> str:
                self.calls.append("renderer_unavailable_reason")
                return "should not be used"

            def create_renderer(self):
                self.calls.append("create_renderer")
                return self.renderer

        session = FakeSession()
        app._adapter_session = session

        result = app._preconstruct_ovrtx_renderer()

        assert result is session.renderer
        assert session.calls == ["renderer_available", "create_renderer"]

        module_src = inspect.getsource(app_mod)
        preconstruct_src = inspect.getsource(Application._preconstruct_ovrtx_renderer)

        assert "ovui_data_adapters.openusd" not in module_src
        assert "from pxr" not in module_src
        assert "import pxr" not in module_src
        assert "session = self.get_adapter_session()" in preconstruct_src
        assert "session.renderer_available()" in preconstruct_src
        assert "session.renderer_unavailable_reason()" in preconstruct_src
        assert "session.create_renderer()" in preconstruct_src
