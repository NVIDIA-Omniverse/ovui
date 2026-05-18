# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Modal file-picker dialogs for OvGear (LAYERS-PLAN Step 36).

ovui v3 does not ship a ``ui.FileDialog`` or ``ui.FilePickerDialog`` —
the C++ bindings that would expose one are absent from this build (see
:mod:`omni.ui`'s public ``__init__``). Kit-style ``omni.kit.window.file``
is off-limits too (constraint G2 — the Layers window must stay
Kit-free). Step 36's plan text anticipates this exact situation and
prescribes the fallback: a modal :class:`ui.Window` with a
:class:`ui.StringField` for the path plus **Save** / **Cancel** buttons.

:func:`save_file_dialog` is the single entry point. It opens the modal,
wires Save to ``on_selected(path)`` and Cancel (or window-close) to
``on_cancelled()``, and hides the window when either fires. The window
is kept on a module-level registry so garbage collection can't reap it
mid-interaction — ovui's :class:`Window` owns the heavy paint tree but
the Python wrapper must stay referenced for the duration of the
dialog's life.

Headless / test fallback
------------------------

``save_file_dialog`` is safe to call even when ``omni.ui`` cannot build
a window (e.g. a pure-unit-test context that did not initialise the ovui
event loop): the function catches any exception from the ``ui.Window``
constructor, calls ``on_cancelled()`` so the caller can recover, and
returns ``None``. Tests that want to simulate a path-selected flow
bypass the dialog entirely and drive the command directly — see
``tests/test_layers_step36_save_as.py``.
"""

from __future__ import annotations

import os
from typing import Any, Callable, List, Optional

import omni.ui as ui

# Module-level registry so dialogs stay alive for the duration of the
# interaction. ovui's ``ui.Window`` survives on the Python side only
# while a reference exists — a locally-scoped window gets collected as
# soon as ``save_file_dialog`` returns, which closes the dialog on the
# next GC pass. Keeping a module-level list lets the dialog's own
# ``_close`` remove itself once the user picks Save or Cancel.
_OPEN_DIALOGS: List["_SaveFileDialog"] = []


def save_file_dialog(
    title: str,
    default_name: str,
    on_selected: Callable[[str], None],
    on_cancelled: Optional[Callable[[], None]] = None,
    filter_ext: str = ".usda",
    default_dir: Optional[str] = None,
) -> Optional["_SaveFileDialog"]:
    """Open a modal Save-As dialog and return it for reference-keeping.

    Parameters
    ----------
    title:
        Window title — typically "Save '<identifier>' as…".
    default_name:
        Pre-filled filename (with extension). The user can edit the
        path freely — the extension is enforced only on Save so a
        caller can still save as ``.usd`` / ``.usdc`` if they type it.
    on_selected:
        Invoked with the absolute path string when the user clicks
        **Save**. The dialog closes before the callback fires so a
        long-running save does not block the window tear-down.
    on_cancelled:
        Invoked with no arguments when the user clicks **Cancel** or
        closes the window via its title-bar close button. Optional;
        a no-op default is used when ``None``.
    filter_ext:
        Extension appended to the path on Save if the user's input
        does not already end in a recognised USD extension. Used for
        the "append .usda" ergonomics — users don't have to type the
        extension but we still end up with a valid layer file.
    default_dir:
        Directory the path input starts in. Defaults to the current
        working directory so the relative-path guess lands somewhere
        reasonable on every platform.

    Returns
    -------
    The dialog object on success, ``None`` if ovui refused to build
    the window (headless / event-loop-not-initialised contexts). On
    ``None`` the ``on_cancelled`` callback has already fired so callers
    can treat ``None`` as "user dismissed".
    """
    on_cancelled_effective = on_cancelled or (lambda: None)
    try:
        dialog = _SaveFileDialog(
            title=title,
            default_name=default_name,
            on_selected=on_selected,
            on_cancelled=on_cancelled_effective,
            filter_ext=filter_ext,
            default_dir=default_dir or os.getcwd(),
        )
    except Exception:
        # ovui window construction can fail in a headless / uninit
        # event-loop context. Surface as "cancelled" so the caller's
        # error path runs instead of raising into the click handler.
        on_cancelled_effective()
        return None
    _OPEN_DIALOGS.append(dialog)
    return dialog


class _SaveFileDialog:
    """Private helper — the :class:`ui.Window`-backed Save-As modal.

    Isolated in a class so the Save / Cancel click handlers can capture
    the window handle and the StringField model without long lambda
    chains. The module-level :data:`_OPEN_DIALOGS` list retains the
    instance so ovui's Python window wrapper cannot be GC'd mid-
    interaction; :meth:`_close` removes it from the list on dismissal.
    """

    def __init__(
        self,
        title: str,
        default_name: str,
        on_selected: Callable[[str], None],
        on_cancelled: Callable[[], None],
        filter_ext: str,
        default_dir: str,
    ) -> None:
        self._on_selected = on_selected
        self._on_cancelled = on_cancelled
        self._filter_ext = filter_ext
        self._closed = False

        initial_path = os.path.join(default_dir, default_name)

        self._window = ui.Window(
            title,
            width=520,
            height=180,
            flags=ui.WINDOW_FLAGS_MODAL,
            style_type_name_override="Dialog",
        )
        self._field: Optional[Any] = None
        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=4)
                with ui.HStack(height=20):
                    ui.Spacer(width=8)
                    ui.Label(
                        "Save As",
                        style_type_name_override="Dialog.SectionTitle",
                    )
                    ui.Spacer(width=8)
                with ui.HStack(height=24):
                    ui.Spacer(width=8)
                    ui.Label("Path", width=48)
                    self._field = ui.StringField(height=24)
                    self._field.model.set_value(initial_path)
                    ui.Spacer(width=8)
                ui.Spacer()
                with ui.HStack(height=28):
                    ui.Spacer()
                    ui.Button(
                        "Save",
                        width=96,
                        clicked_fn=self._on_save_clicked,
                        style_type_name_override="OKButton",
                    )
                    ui.Spacer(width=6)
                    ui.Button(
                        "Cancel",
                        width=96,
                        clicked_fn=self._on_cancel_clicked,
                        style_type_name_override="CancelButton",
                    )
                    ui.Spacer(width=8)
                ui.Spacer(height=8)

        # ovui's Window ``set_visibility_changed_fn`` lets us trap the
        # title-bar close button. Treat ``visible = False`` as cancel.
        self._visibility_sub = None
        if hasattr(self._window, "set_visibility_changed_fn"):
            self._window.set_visibility_changed_fn(self._on_visibility_changed)

    @property
    def path(self) -> str:
        """Current value in the path field (test helper)."""
        if self._field is None:
            return ""
        return self._field.model.get_value_as_string()

    def set_path(self, value: str) -> None:
        """Write ``value`` into the path field (test helper)."""
        if self._field is None:
            return
        self._field.model.set_value(value)

    def confirm(self) -> None:
        """Simulate a Save click (test helper)."""
        self._on_save_clicked()

    def cancel(self) -> None:
        """Simulate a Cancel click (test helper)."""
        self._on_cancel_clicked()

    def _on_save_clicked(self) -> None:
        if self._closed:
            return
        raw = self.path.strip()
        if not raw:
            # Empty path is ambiguous — treat as cancel so the caller
            # does not get handed an invalid identifier. Matches the
            # adapter's ``save_layer_as`` contract (``new_path=""`` is
            # a failure).
            self._on_cancel_clicked()
            return
        if not _has_usd_extension(raw):
            raw = raw + self._filter_ext
        path = os.path.abspath(raw)
        self._close()
        # Invoke the caller's handler *after* closing so the modal
        # disappears before any long-running save / parent-rewrite
        # work starts. Keeps the UI responsive.
        self._on_selected(path)

    def _on_cancel_clicked(self) -> None:
        if self._closed:
            return
        self._close()
        self._on_cancelled()

    def _on_visibility_changed(self, visible: bool) -> None:
        # Title-bar close = Cancel. Guard against the visibility flip
        # that :meth:`_close` itself triggers (it sets ``visible =
        # False`` which re-enters this callback) via the ``_closed``
        # flag — the on-cancel callback then runs exactly once.
        if visible:
            return
        if self._closed:
            return
        self._close()
        self._on_cancelled()

    def _close(self) -> None:
        self._closed = True
        try:
            self._window.visible = False
        except Exception:
            # Window may already be torn down (e.g. ovui shut the
            # event loop) — swallow so the on-select/on-cancel
            # callback still fires on the caller's side.
            pass
        if self in _OPEN_DIALOGS:
            _OPEN_DIALOGS.remove(self)


_USD_EXTENSIONS = (".usd", ".usda", ".usdc", ".usdz")


def _has_usd_extension(path: str) -> bool:
    """Return ``True`` iff ``path`` already ends with a USD file extension.

    Case-insensitive so the user can type ``.USDA`` without the
    dialog appending a duplicate suffix.
    """
    lower = path.lower()
    return any(lower.endswith(ext) for ext in _USD_EXTENSIONS)


# ── Issue #35 Step 4: registry-driven shutdown cleanup ────────────────
# Same pattern as ovwidgets.app/dialogs.py.
def _clear_open_dialogs() -> None:
    """Destroy every dialog in _OPEN_DIALOGS and empty the list.

    Called by ovwidgets.common.icon_caches.clear_all() from
    Application.shutdown(). Round 6 F2: also nulls dlg._window so the
    destroyed wrapper isn't kept alive through the dialog instance's
    attribute.
    """
    for dlg in list(_OPEN_DIALOGS):
        w = getattr(dlg, "_window", None)
        if w is None:
            continue
        try:
            w.destroy()
        except Exception:
            pass
        finally:
            try:
                dlg._window = None
            except Exception:
                pass
    _OPEN_DIALOGS.clear()


from ovwidgets.common.icon_caches import register as _register_for_shutdown

_register_for_shutdown(_clear_open_dialogs)
