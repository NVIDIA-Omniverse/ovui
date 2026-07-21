# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Integration tests that exercise the REAL ``Application.shutdown()``
path against the dialog-list cleanup machinery.

Issue #35, Step 4 + Step 4b. End-to-end coverage for the dialog
teardown chain:

    Application.shutdown()
        → icon_caches.clear_all()
            → ovui_widgets.common.dialogs._clear_open_dialogs() / file_dialogs / confirm_overwrite_dialog

Distinct from :mod:`tests.test_dialog_cleanup_on_shutdown` which
hand-wires the registration and calls ``clear_all()`` directly. This
file proves the actual shutdown path (the only path the user's normal
window-close exercises) drives the cleanup correctly.

Round 4 F1 — NO autouse ``_isolated_registry`` fixture
------------------------------------------------------
Tests in this file deliberately do NOT define an autouse
``_isolated_registry`` fixture. The integration tests below call the
REAL :meth:`Application.shutdown`, which routes through
:func:`icon_caches.clear_all` — that needs the real, import-time
registrations to be live. Using ``monkeypatch.setattr(icon_caches,
"_callbacks", [])`` here would empty the registry before the test, and
re-importing already-imported modules wouldn't re-fire their top-level
``register()`` calls (Python caches imports in :data:`sys.modules`).

Round 8 F1 — TEST-ORDER INDEPENDENCE
------------------------------------
The three dialog modules are imported at MODULE TOP-LEVEL here (not
inside test bodies). Pytest collects every test file BEFORE running
any test, and these top-level imports run during collection. That
means the dialog modules' top-level ``register(_clear_open_dialogs)``
calls fire BEFORE any autouse ``_isolated_registry`` fixture in another
test file activates — so the registrations land on the *real*
:data:`icon_caches._callbacks` list, not on a temporary monkeypatched
``[]``. Once the modules are in :data:`sys.modules`, no re-import can
trigger duplicate registration.

Without this top-level-import discipline, the following test-order
bug would reproduce:

1. Pytest collects ``test_dialog_cleanup_on_shutdown.py`` first; that
   file's autouse fixture is set up but does not yet run.
2. ``test_dialog_cleanup_on_shutdown`` runs first — its autouse fixture
   monkeypatches ``icon_caches._callbacks`` to ``[]`` for each test.
3. Inside a unit-test body, ``import ovui_widgets.common.dialogs`` fires for the
   first time. The module's top-level ``register(_clear_open_dialogs)``
   runs while the monkeypatch is active. The registration goes into
   the temporary ``[]`` (NOT the real list).
4. Fixture teardown: ``monkeypatch`` restores the real ``_callbacks``
   list (which never received the dialog registration).
5. Integration tests in this file run. Modules are now in
   :data:`sys.modules` (no re-import). Real ``_callbacks`` lacks the
   dialog clears. ``Application.shutdown()`` doesn't clear the dialog
   lists. Tests fail mysteriously.

Hoisting the imports here closes that hole.
"""
from __future__ import annotations

import pytest

import ovui_widgets.app

# Round 8 F1: collection-time imports. See the comment block above.
import ovui_widgets.common.dialogs  # noqa: F401
import ovui_widgets.common.file_dialogs  # noqa: F401
import ovui_widgets.content
import ovui_widgets.content.widget.confirm_overwrite_dialog  # noqa: F401
from ovui_widgets.app.application import Application
from ovui_widgets.common.selection import SelectionBus


@pytest.fixture
def headless_app():
    """Headless Application instance with singleton cleanup, mirroring
    the project-wide pattern from :mod:`tests.conftest` but local so
    this file's order-independence guarantee survives any future
    project-wide fixture changes."""
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    yield app
    # The shutdown call below is the test subject; the fixture's
    # post-yield cleanup is just a safety net. Idempotency from Step 1
    # makes a second call a no-op.
    try:
        app.shutdown()
    except Exception:
        pass
    Application._instance = None
    SelectionBus._instance = None


def _make_fake_dialog():
    """Mimics _SaveFileDialog / _ConfirmDialogBase / ConfirmOverwriteDialog
    shape: has ``._window`` that has ``.destroy()`` flipping a flag."""

    class _W:
        destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    class _D:
        _window = _W()

    return _D()


# ── Round 3 F8 / Round 7 F1: integration tests that exercise
# Application.shutdown() → icon_caches.clear_all() → list-clear chain.
# Each test captures the window reference BEFORE shutdown (Round 7 F1:
# Round 6 F2 nulls dlg._window after destroy, so reading
# ``fake._window.destroyed`` after shutdown would AttributeError) and
# saves+restores the underlying _OPEN_DIALOGS list (Round 4 F1: be a
# good test-citizen).


def test_application_shutdown_destroys_open_confirm_dialog(headless_app):
    """Pushes a fake dialog into ``ovui_widgets.common.dialogs._OPEN_DIALOGS``,
    runs the REAL ``Application.shutdown()``, asserts the list was
    emptied AND the fake's ``_window.destroy()`` was called AND
    ``fake._window`` is now ``None``."""
    import ovui_widgets.common.dialogs as dlgs
    saved = list(dlgs._OPEN_DIALOGS)
    try:
        fake = _make_fake_dialog()
        captured_window = fake._window
        dlgs._OPEN_DIALOGS.append(fake)
        headless_app.shutdown()
        assert dlgs._OPEN_DIALOGS == [], "shutdown left dialogs list non-empty"
        assert captured_window.destroyed is True, (
            "shutdown did not destroy the dialog window"
        )
        assert fake._window is None, (
            "Round 6 F2: dlg._window must be nulled after destroy"
        )
    finally:
        dlgs._OPEN_DIALOGS[:] = saved


def test_application_shutdown_destroys_open_save_file_dialog(headless_app):
    """Same assertion shape against
    :data:`ovui_widgets.common.file_dialogs._OPEN_DIALOGS`."""
    import ovui_widgets.common.file_dialogs as fd
    saved = list(fd._OPEN_DIALOGS)
    try:
        fake = _make_fake_dialog()
        captured_window = fake._window
        fd._OPEN_DIALOGS.append(fake)
        headless_app.shutdown()
        assert fd._OPEN_DIALOGS == []
        assert captured_window.destroyed is True
        assert fake._window is None
    finally:
        fd._OPEN_DIALOGS[:] = saved


def test_application_shutdown_destroys_open_overwrite_dialog(headless_app):
    """``Application.shutdown()`` must drive the
    ``confirm_overwrite_dialog._OPEN_DIALOGS`` clear too — the third
    dialog list, added per Round 3 F2."""
    import ovui_widgets.content.widget.confirm_overwrite_dialog as cod
    saved = list(cod._OPEN_DIALOGS)
    try:
        fake = _make_fake_dialog()
        captured_window = fake._window
        cod._OPEN_DIALOGS.append(fake)
        headless_app.shutdown()
        assert cod._OPEN_DIALOGS == []
        assert captured_window.destroyed is True
        assert fake._window is None
    finally:
        cod._OPEN_DIALOGS[:] = saved


def test_application_shutdown_destroys_settings_dialog(headless_app):
    """``SettingsDialog.destroy()`` (Step 4b) must run via
    ``Application.shutdown()``. The settings dialog is held as
    ``Application._settings_dialog`` (instance attr); Step 1's body
    calls its ``destroy()`` if available, then nulls the attribute."""
    sd = headless_app._settings_dialog
    assert sd is not None

    class _W:
        destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    sd._window = _W()
    captured_window = sd._window
    headless_app.shutdown()
    assert captured_window.destroyed is True, (
        "SettingsDialog.destroy() did not tear down the window"
    )
    # SettingsDialog.destroy nulls self._window. The shutdown body
    # additionally nulls Application._settings_dialog, but the
    # SettingsDialog instance still exists in `sd` for our
    # post-shutdown read of `sd._window`.
    assert sd._window is None, "SettingsDialog._window not nulled"
