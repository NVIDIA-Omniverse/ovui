# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 23 warning-path test for ``Application._preconstruct_ovrtx_renderer``.

When ``ovrtx`` is unavailable (``renderer_adapter.AVAILABLE is False``),
``_preconstruct_ovrtx_renderer`` must:

  - Call ``ErrorReporter.show_warning`` with a message that mentions
    BOTH the import error type name (``ImportError``) AND the import
    error's message text (``synthetic``).
  - Return ``None``.

This test exercises the module-alias idiom that the Step 23 plan
explicitly requires preservation of:

  from ovui_data_adapters.openusd import renderer_adapter as _ovrtx_mod

If the application were rewritten to ``from ovui_data_adapters.openusd
import OvRtxRendererAdapter`` directly, the lazy module-level
``AVAILABLE`` proxy and ``_OVRTX_IMPORT_ERROR`` warning-path reporting
would be lost. This test pins both behaviors.
"""

from unittest.mock import MagicMock, patch

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus


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


def _stub_module_alias_unavailable(monkeypatch, error: BaseException) -> None:
    """Replace the renderer_adapter module's ``AVAILABLE`` flag and
    ``_OVRTX_IMPORT_ERROR`` so the warning path is exercised.

    Mutates the actual module so the ``from … import renderer_adapter
    as _ovrtx_mod`` lazy import inside ``_preconstruct_ovrtx_renderer``
    sees the synthetic unavailable state. ``monkeypatch`` reverts both
    setattr calls when the test finishes.
    """
    from ovui_data_adapters.openusd import renderer_adapter
    monkeypatch.setattr(renderer_adapter, "AVAILABLE", False)
    monkeypatch.setattr(renderer_adapter, "_OVRTX_IMPORT_ERROR", error)


class TestPreconstructWarningPath:
    """Step 23: ovrtx-unavailable warning path through ``_ovrtx_mod`` alias."""

    def test_unavailable_emits_warning_with_error_type_and_message(self, app, monkeypatch):
        synthetic = ImportError("synthetic")
        _stub_module_alias_unavailable(monkeypatch, synthetic)

        with patch(
            "ovwidgets.common.error_reporter.ErrorReporter.show_warning"
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
        monkeypatch.setattr(renderer_adapter, "AVAILABLE", False)
        monkeypatch.setattr(renderer_adapter, "_OVRTX_IMPORT_ERROR", None)

        with patch(
            "ovwidgets.common.error_reporter.ErrorReporter.show_warning"
        ) as mock_warn:
            result = app._preconstruct_ovrtx_renderer()

        assert result is None
        mock_warn.assert_called_once()
        msg = mock_warn.call_args.args[0]
        assert "ovrtx not available" in msg, (
            f"fallback warning text expected; got: {msg!r}"
        )

    def test_module_alias_preserved(self):
        """Pin the module-alias idiom that the Step 23 plan requires.

        Application._preconstruct_ovrtx_renderer must access ovrtx state
        through the module alias (``_ovrtx_mod.AVAILABLE``,
        ``_ovrtx_mod._OVRTX_IMPORT_ERROR``, ``_ovrtx_mod.OvRtxRendererAdapter()``)
        rather than via ``from … import OvRtxRendererAdapter``. A direct
        ``import`` would freeze the symbol at import time and break the
        lazy-availability proxy + warning-path reporting.
        """
        import ovwidgets.app.application as app_mod
        with open(app_mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        assert "from ovui_data_adapters.openusd import renderer_adapter as _ovrtx_mod" in src
        assert "_ovrtx_mod.AVAILABLE" in src
        assert "_ovrtx_mod._OVRTX_IMPORT_ERROR" in src
        assert "_ovrtx_mod.OvRtxRendererAdapter()" in src
