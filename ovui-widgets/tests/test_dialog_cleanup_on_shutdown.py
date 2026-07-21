# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unit tests for the dialog-list ``_clear_open_dialogs`` helpers.

Issue #35, Step 4 + Step 4b.

These tests hand-wire fake dialogs into the module-scope
``_OPEN_DIALOGS`` lists and invoke the registered ``clear_all()`` —
they do NOT exercise the real ``Application.shutdown()`` path. The
end-to-end coverage lives in
:mod:`tests.test_application_shutdown_integration`.

Round 8 F1 — collection-time dialog imports
-------------------------------------------
These three top-level imports run during pytest collection, BEFORE
the autouse ``_isolated_registry`` fixture below activates. The dialog
modules' top-level ``register(_clear_open_dialogs)`` calls therefore
land on the *real* :data:`icon_caches._callbacks` list, not on a
temporary monkeypatched ``[]``. After collection, the modules are in
:data:`sys.modules` and re-importing them inside test bodies is a
no-op — the registrations stay on the real list and survive the
autouse fixture's save/restore. Without these top-level imports, an
integration test scheduled after this file would see an empty
registry and fail with ``_OPEN_DIALOGS`` not getting cleared. (See
also :mod:`tests.test_application_shutdown_integration` for the same
defensive pattern.)
"""
from __future__ import annotations

import pytest

import ovui_widgets.app
import ovui_widgets.common.dialogs  # noqa: F401
import ovui_widgets.common.file_dialogs  # noqa: F401
import ovui_widgets.content
import ovui_widgets.content.widget.confirm_overwrite_dialog  # noqa: F401


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """Per-test isolated registry. Round 8 F1: this ONLY affects unit
    tests in this file — the collection-time imports above already
    seeded the real ``_callbacks`` list with the dialog clear callbacks,
    so the integration tests (in another file) see them regardless of
    test execution order.
    """
    from ovui_widgets.common import icon_caches
    monkeypatch.setattr(icon_caches, "_callbacks", [])


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


# ----------------------------------------------------------------------
# Round 2 F7 / Round 6 F2: per-module clear semantics.
# Each test pushes a fake dialog into the corresponding _OPEN_DIALOGS,
# manually invokes the module's _clear_open_dialogs (registered with
# icon_caches), and asserts both the destroyed flag AND
# ``dlg._window is None`` (the Round 6 F2 invariant).
# ----------------------------------------------------------------------


def test_open_save_dialog_torn_down_by_clear_all() -> None:
    """A live entry in ``file_dialogs._OPEN_DIALOGS`` must not survive
    its ``_clear_open_dialogs``."""
    import ovui_widgets.common.file_dialogs as fd
    d = _make_fake_dialog()
    captured_window = d._window
    fd._OPEN_DIALOGS.append(d)
    from ovui_widgets.common import icon_caches
    icon_caches.register(fd._clear_open_dialogs)
    icon_caches.clear_all()
    assert fd._OPEN_DIALOGS == []
    assert captured_window.destroyed is True
    # Round 6 F2: the dialog's _window attribute MUST be None now.
    assert d._window is None, "dlg._window not nulled — wrapper still referenced"


def test_open_confirm_dialog_torn_down_by_clear_all() -> None:
    """Round 2 F7 + Round 6 F2 — same coverage for
    :data:`ovui_widgets.common.dialogs._OPEN_DIALOGS`."""
    import ovui_widgets.common.dialogs as dlgs
    d = _make_fake_dialog()
    captured_window = d._window
    dlgs._OPEN_DIALOGS.append(d)
    from ovui_widgets.common import icon_caches
    icon_caches.register(dlgs._clear_open_dialogs)
    icon_caches.clear_all()
    assert dlgs._OPEN_DIALOGS == []
    assert captured_window.destroyed is True
    assert d._window is None


def test_open_overwrite_dialog_torn_down_by_clear_all() -> None:
    """Round 3 F2 + Round 6 F2 — same coverage for
    :data:`confirm_overwrite_dialog._OPEN_DIALOGS`."""
    import ovui_widgets.content.widget.confirm_overwrite_dialog as cod
    d = _make_fake_dialog()
    captured_window = d._window
    cod._OPEN_DIALOGS.append(d)
    from ovui_widgets.common import icon_caches
    icon_caches.register(cod._clear_open_dialogs)
    icon_caches.clear_all()
    assert cod._OPEN_DIALOGS == []
    assert captured_window.destroyed is True
    assert d._window is None


def test_clear_open_dialogs_handles_already_destroyed_dialog() -> None:
    """If a dialog's ``_window`` raises during destroy(), the helper
    must not propagate the exception AND must still clear the list and
    null the wrapper. Best-effort, per :mod:`icon_caches`."""
    import ovui_widgets.common.dialogs as dlgs

    class _W:
        destroyed = False

        def destroy(self) -> None:
            self.destroyed = True
            raise RuntimeError("simulated post-destroy raise")

    class _D:
        _window = _W()

    d = _D()
    captured_window = d._window
    dlgs._OPEN_DIALOGS.append(d)
    from ovui_widgets.common import icon_caches
    icon_caches.register(dlgs._clear_open_dialogs)
    icon_caches.clear_all()  # MUST NOT raise
    assert dlgs._OPEN_DIALOGS == []
    assert captured_window.destroyed is True  # destroy() did fire
    assert d._window is None  # finally: dlg._window = None


def test_clear_open_dialogs_skips_dialog_with_None_window() -> None:
    """A dialog whose ``_window`` was already nulled (e.g., by an
    earlier ``_dismiss()``) is left alone — the helper just skips."""
    import ovui_widgets.common.file_dialogs as fd

    class _D:
        _window = None

    d = _D()
    fd._OPEN_DIALOGS.append(d)
    from ovui_widgets.common import icon_caches
    icon_caches.register(fd._clear_open_dialogs)
    icon_caches.clear_all()
    # The list is still emptied (we don't keep stale entries around).
    assert fd._OPEN_DIALOGS == []
    assert d._window is None
