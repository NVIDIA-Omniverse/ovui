# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileExporterHelper — typed ``Save File As`` dialog wrapper.

See the content browser behavior and the content browser implementation step 55.
Sibling to :class:`FileImporterHelper` (Step 53): a thin wrapper over
:class:`FilePickerDialog` that collapses the dialog's two-arg
``(filename, dirname)`` Apply callback into the Kit-standard four-arg
``export_handler(filename, dirname, extension, selections)`` contract.
The wrapper's job is to:

1. Pick a sensible starting directory for the dialog:
   the ``filename_url`` argument's parent if given, else the Settings-
   persisted ``ui.content.last_save_dir`` key, else the user's home.
2. Construct (or reuse) a :class:`FilePickerDialog` configured for save
   semantics: ``should_validate=True``, ``validation_mode="save"``,
   ``apply_button_label=export_button_label``.
3. On Apply — resolve the extension from the bar's selected combo
   entry, fire the caller's ``export_handler`` with the typed four-arg
   payload, persist the dirname into ``ui.content.last_save_dir``, and
   hide the dialog.
4. On Cancel / ESC — hide the dialog and no-op.

A singleton is exposed through :meth:`instance` so the one-line use
site in :mod:`ovui_widgets.app.menu_bar` (File > Save As) does not allocate a
fresh helper every time the menu is triggered. Reset via
:meth:`reset_singleton` in test fixtures.

**Extension contract** (architecture §22.4). The fourth arg to the
caller's ``export_handler`` is the ``.ext`` string derived from the
combo's currently-selected glob — e.g. ``"*.usd"`` → ``".usd"``. Kit's
exporter composes ``.postfix.ext``; ovgear v1 has no postfix surface,
so :meth:`_resolve_extension` strips the leading ``*`` from the first
pattern in the selected glob and returns that. The caller joins
``filename + extension`` before writing to disk (matches the Step-55
menu handler's ``on_export`` closure).

**Overwrite confirmation** lives outside this helper — architecture
§22.5 point 4 and Kit's ``_show_file_existed_prompt`` (§23.9) both put
overwrite-check / :class:`ConfirmOverwriteDialog` dispatch in the
caller's ``on_export`` path, not the helper. The helper surfaces the
typed payload; the caller checks ``os.path.exists`` and branches.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional, Tuple

from ovui_widgets.content.backends.backend_adapter import BackendAdapter
from ovui_widgets.content.backends.local_fs_backend import LocalFSBackend
from ovui_widgets.content.file_picker_dialog import FilePickerDialog

# Persistent Settings key for the last-used "Save" directory. Sibling to
# :data:`LAST_OPEN_DIR_SETTING` — Kit's architecture §36.3
# ``/persistent/app/file_exporter/directory`` collapses under ovgear's
# flat ``ui.*`` namespace to ``ui.content.last_save_dir``.
LAST_SAVE_DIR_SETTING = "ui.content.last_save_dir"

# Default file-extension combo entries for the exporter. Architecture
# §22.4 specifies this exact tuple (USD Binary/Ascii, USD Ascii, USD
# Crate) — tighter than the importer's list because the exporter only
# writes to formats the USD stage knows how to emit. ``.usdz`` is
# intentionally omitted: it is a package format Kit's exporter also
# drops.
DEFAULT_FILE_EXTENSION_TYPES: List[Tuple[str, str]] = [
    ("*.usd", "USD Binary or Ascii"),
    ("*.usda", "USD Ascii"),
    ("*.usdc", "USD Crate"),
]


class FileExporterHelper:
    """Typed wrapper around :class:`FilePickerDialog` for Save As dialogs.

    The helper owns at most one live dialog at a time; calling
    :meth:`show` with an already-live dialog tears it down and rebuilds
    so each :meth:`show` lands with the caller's exact configuration.
    The singleton returned by :meth:`instance` is the entry point used
    by :func:`ovui_widgets.app.menu_bar._on_save_as_clicked`; tests construct
    bare instances with injected ``backend`` / ``settings`` dependencies.

    ``export_handler`` signature::

        export_handler(
            filename: str,
            dirname: str,
            extension: str,
            selections: List[str],
        )

    ``filename`` is the basename typed in the :class:`FileBar` (no
    extension), ``dirname`` is the detail pane's current root URL,
    ``extension`` is the combo's currently-selected glob stripped to
    ``.ext`` (e.g. ``.usd``), and ``selections`` is the list of full
    URLs from the detail pane's current selection (typically empty for
    a Save As — the user is typing a new name, not picking an existing
    file to overwrite).
    """

    _singleton: Optional["FileExporterHelper"] = None

    # ── Construction / singleton ─────────────────────────────────────────

    def __init__(
        self,
        backend: Optional[BackendAdapter] = None,
        settings: Optional[object] = None,
    ) -> None:
        """Construct a helper with optional ``backend`` / ``settings`` overrides.

        ``backend`` defaults to a fresh :class:`LocalFSBackend` — the
        helper is OS-file-system-only at Step 55. ``settings`` defaults
        to ``None``; the helper then resolves the live
        :class:`ovui_widgets.common.settings.Settings` lazily through
        :meth:`Application.instance`. Tests bypass the application
        singleton by passing a pre-built :class:`Settings` instance.
        """
        self._backend: BackendAdapter = (
            backend if backend is not None else LocalFSBackend()
        )
        self._settings_override: Optional[object] = settings
        self._dialog: Optional[FilePickerDialog] = None

    @classmethod
    def instance(cls) -> "FileExporterHelper":
        """Return the process-wide singleton, constructing on first call."""
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    @classmethod
    def reset_singleton(cls) -> None:
        """Tear down and clear the cached singleton.

        Test fixtures call this between tests so a leftover helper from
        one test cannot leak its live dialog into the next. Destroys any
        live dialog via :meth:`destroy` before releasing the reference.
        """
        if cls._singleton is not None:
            try:
                cls._singleton.destroy()
            except Exception:  # noqa: BLE001
                pass
            cls._singleton = None

    # ── Public surface ───────────────────────────────────────────────────

    def show(
        self,
        title: str = "Save File As",
        export_button_label: str = "Save",
        file_extension_types: Optional[List[Tuple[str, str]]] = None,
        export_handler: Optional[
            Callable[[str, str, str, List[str]], None]
        ] = None,
        filename_url: Optional[str] = None,
        should_validate: bool = True,
    ) -> None:
        """Materialise a configured :class:`FilePickerDialog` and reveal it.

        If a dialog from a previous :meth:`show` is still live it is
        destroyed first — each call lands with the caller's exact
        configuration rather than reusing a stale one. The dialog's
        ``on_apply`` wraps ``export_handler`` with the four-arg
        contract, persists the Apply-time dirname to Settings, and
        hides the dialog. The dialog's ``on_cancel`` is a bare ``None``;
        the dialog's built-in hide-on-cancel path handles dismissal.

        ``should_validate`` defaults to ``True`` (matches Step 53's
        importer default; save-mode validation rejects an empty
        filename — architecture §22.5 point 4).
        """
        if self._dialog is not None:
            try:
                self._dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._dialog = None

        start_url = self._resolve_start_url(filename_url)
        initial_filename = self._resolve_initial_filename(filename_url)
        extensions = (
            file_extension_types
            if file_extension_types is not None
            else list(DEFAULT_FILE_EXTENSION_TYPES)
        )

        def _on_apply_wrapper(filename: str, dirname: str) -> None:
            """Run the typed Apply payload, persist the dir, hide the dialog."""
            selections: List[str] = []
            extension: str = ""
            if self._dialog is not None:
                try:
                    selections = self._dialog.get_selection()
                except Exception:  # noqa: BLE001
                    selections = []
                extension = self._resolve_extension()
            self._persist_last_save_dir(dirname)
            if export_handler is not None:
                try:
                    export_handler(filename, dirname, extension, selections)
                except Exception:  # noqa: BLE001
                    # Isolate the caller's handler so a raise does not
                    # leave the dialog stuck on screen. Mirrors Step 53's
                    # importer's BLE001 pattern; the reporter is the
                    # right sink for the diagnostic but a hard
                    # dependency on it from a wrapper that may run
                    # before :class:`Application` is up would complicate
                    # the init path.
                    pass
            if self._dialog is not None:
                self._dialog.hide()

        self._dialog = FilePickerDialog(
            title=title,
            backend=self._backend,
            start_url=start_url,
            apply_button_label=export_button_label,
            cancel_button_label="Cancel",
            on_apply=_on_apply_wrapper,
            on_cancel=None,
            allow_multi_selection=False,
            file_extension_types=extensions,
            folder_only=False,
            initial_filename=initial_filename,
            should_validate=should_validate,
            validation_mode="save",
        )
        self._dialog.show()

    def destroy(self) -> None:
        """Tear down the live dialog, if any.

        Idempotent — safe to call when :meth:`show` was never invoked.
        Leaves the helper reusable: a subsequent :meth:`show` builds a
        fresh dialog from scratch.
        """
        if self._dialog is not None:
            try:
                self._dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._dialog = None

    # ── Accessors ────────────────────────────────────────────────────────

    @property
    def dialog(self) -> Optional[FilePickerDialog]:
        """The currently-live :class:`FilePickerDialog`, or ``None``."""
        return self._dialog

    @property
    def backend(self) -> BackendAdapter:
        """The backend used for start-URL normalisation + dialog ops."""
        return self._backend

    # ── Internals ────────────────────────────────────────────────────────

    def _resolve_start_url(self, filename_url: Optional[str]) -> str:
        """Pick the dialog's starting directory per the content browser implementation step 55.

        Precedence: (1) ``filename_url``'s parent directory; (2) the
        Settings-persisted ``ui.content.last_save_dir``; (3) the user's
        home directory. Each step falls through on an empty / missing /
        malformed value so the helper always returns a usable URL.
        """
        if filename_url:
            parent = self._parent_url(filename_url)
            if parent:
                return parent
        settings = self._get_settings()
        if settings is not None:
            saved = settings.get(LAST_SAVE_DIR_SETTING, None)
            if saved:
                return saved
        return self._backend.normalize_url(
            "file://" + os.path.expanduser("~"),
        )

    def _resolve_initial_filename(
        self, filename_url: Optional[str],
    ) -> str:
        """Extract the basename from ``filename_url`` for pre-fill.

        Returns an empty string when no URL is given. Matches Kit's
        ``FileExporterExtension.show_window`` behaviour: a caller that
        wants the dialog to reopen on a specific file (e.g. a "Save a
        Copy" action) gets its basename pre-populated in the
        :class:`FileBar` filename field.
        """
        if not filename_url:
            return ""
        try:
            return self._backend.basename(filename_url) or ""
        except Exception:  # noqa: BLE001
            return ""

    def _parent_url(self, filename_url: str) -> Optional[str]:
        """Return the parent URL of a file URL; ``None`` at backend root."""
        try:
            return self._backend.parent_url(filename_url)
        except Exception:  # noqa: BLE001
            return None

    def _resolve_extension(self) -> str:
        """Return the current combo selection's ``.ext`` string.

        Pulls :attr:`FileBar.selected_extension` from the dialog's bar
        and maps the first pattern to a leading-dot extension — e.g.
        ``("*.usd", "USD Binary or Ascii")`` → ``".usd"``. Kit's
        exporter composes ``.postfix.ext`` (architecture §22.4); ovgear
        v1 has no postfix surface so the extension alone is the whole
        composition. Returns an empty string when the bar is missing /
        the selected glob is malformed / the combo resolution fails —
        the caller's ``on_export`` is expected to still receive a
        reasonable filename in that degenerate case.
        """
        if self._dialog is None or self._dialog._file_bar is None:
            return ""
        try:
            pattern, _desc = self._dialog._file_bar.selected_extension
        except Exception:  # noqa: BLE001
            return ""
        if not pattern:
            return ""
        # Split on comma so a multi-glob entry like ``"*.usd, *.usda"``
        # resolves to ``.usd`` (the first pattern). ovgear's importer
        # default uses multi-glob entries; the exporter default does not,
        # but the splitter keeps both surfaces consistent.
        first = pattern.split(",")[0].strip()
        if first.startswith("*"):
            first = first[1:]
        return first

    def _persist_last_save_dir(self, dirname: str) -> None:
        """Write ``dirname`` to Settings — silent no-op if Settings unreachable."""
        if not dirname:
            return
        settings = self._get_settings()
        if settings is None:
            return
        try:
            settings.set(LAST_SAVE_DIR_SETTING, dirname)
        except Exception:  # noqa: BLE001
            pass

    def _get_settings(self) -> Optional[object]:
        """Resolve the live :class:`Settings`, honouring the test override.

        The constructor ``settings`` kwarg wins; otherwise the helper
        reaches through :meth:`Application.instance` — which raises
        when no app is up, so wrap in a try/except and return ``None``
        so the helper can still resolve a start URL from the home
        fallback.
        """
        if self._settings_override is not None:
            return self._settings_override
        try:
            from ovui_widgets.common.settings import Settings
            return Settings.instance()
        except Exception:  # noqa: BLE001
            return None


# ── Issue #35 Step 3: register the helper's reset_singleton classmethod
# so Application.shutdown() drops the live FilePickerDialog (and its
# ui.Window) before omni.ui.shutdown() runs. register_classmethod uses
# a stable string key `f"clsmethod:{module}.{qualname}.reset_singleton"`
# (Round 3 F3) — bound-method identity is unstable across re-imports,
# so we cannot pass FileExporterHelper.reset_singleton through register()
# directly.
from ovui_widgets.common.icon_caches import register_classmethod as _register_clsmethod_for_shutdown

_register_clsmethod_for_shutdown(FileExporterHelper, "reset_singleton")
