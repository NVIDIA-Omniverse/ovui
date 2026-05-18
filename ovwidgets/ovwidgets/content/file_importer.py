# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileImporterHelper — typed ``Open File`` dialog wrapper.

See the content browser behavior and the content browser implementation step 53. This is a
thin wrapper over :class:`FilePickerDialog` that collapses the dialog's
two-arg ``(filename, dirname)`` callback into the Kit-standard
``import_handler(filename, dirname, selections)`` contract. The wrapper's
job is to:

1. Pick a sensible starting directory for the dialog:
   the ``filename_url`` argument's parent if given, else the Settings-
   persisted ``ui.content.last_open_dir`` key, else the user's home.
2. Construct (or reuse) a :class:`FilePickerDialog` configured for open
   semantics: ``should_validate=True``, ``validation_mode="open"``,
   ``apply_button_label=import_button_label``.
3. On Apply — fire the caller's ``import_handler`` with the typed
   payload, persist the dirname back into Settings, and hide the dialog.
4. On Cancel / ESC — hide the dialog and no-op.

A singleton is exposed through :meth:`instance` so the one-line use site
in :mod:`ovwidgets.app.menu_bar` does not allocate a fresh helper every time
the File > Open menu is triggered. The singleton is reset via
:meth:`reset_singleton` in test fixtures.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional, Tuple

from ovwidgets.content.backends.backend_adapter import BackendAdapter
from ovwidgets.content.backends.local_fs_backend import LocalFSBackend
from ovwidgets.content.file_picker_dialog import FilePickerDialog

# Persistent Settings key for the last-used "Open" directory. Matches the
# architecture §36.3 layout: ``/persistent/app/file_importer/directory``
# collapses under ovgear's flat ``ui.*`` namespace to
# ``ui.content.last_open_dir``. A companion ``last_save_dir`` will land
# alongside at Step 55's :class:`FileExporterHelper`.
LAST_OPEN_DIR_SETTING = "ui.content.last_open_dir"

# Default file-extension combo entries. Matches architecture §22.1
# verbatim — USD files first, then catch-all. A future enhancement
# (mirrors Kit's dynamic ``pxr.Sdf.FileFormat.FindAllFileFormatExtensions``
# appendage) can extend this without touching the constructor surface.
DEFAULT_FILE_EXTENSION_TYPES: List[Tuple[str, str]] = [
    ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
    ("*.*", "All files"),
]


class FileImporterHelper:
    """Typed wrapper around :class:`FilePickerDialog` for Open dialogs.

    The helper owns at most one live dialog at a time; calling
    :meth:`show` with an already-live dialog tears it down and rebuilds
    so each :meth:`show` lands with the caller's exact configuration.
    The singleton returned by :meth:`instance` is the entry point used
    by :func:`ovwidgets.app.menu_bar._on_open_clicked`; tests construct
    bare instances with injected ``backend`` / ``settings`` dependencies.

    ``import_handler`` signature::

        import_handler(filename: str, dirname: str, selections: List[str])

    ``filename`` is the basename typed in the :class:`FileBar`, ``dirname``
    is the detail pane's current root URL, and ``selections`` is the list
    of full URLs from the detail pane's current selection (empty when the
    user types a filename and hits Open without clicking a row).
    """

    _singleton: Optional["FileImporterHelper"] = None

    # ── Construction / singleton ─────────────────────────────────────────

    def __init__(
        self,
        backend: Optional[BackendAdapter] = None,
        settings: Optional[object] = None,
    ) -> None:
        """Construct a helper with optional ``backend`` / ``settings`` overrides.

        ``backend`` defaults to a fresh :class:`LocalFSBackend` — the
        helper is OS-file-system-only at Step 53. ``settings`` defaults
        to ``None``; the helper then resolves the live
        :class:`ovwidgets.common.settings.Settings` lazily through
        :meth:`Application.instance`. Tests bypass the application
        singleton by passing a pre-built :class:`Settings` instance.
        """
        self._backend: BackendAdapter = (
            backend if backend is not None else LocalFSBackend()
        )
        self._settings_override: Optional[object] = settings
        self._dialog: Optional[FilePickerDialog] = None

    @classmethod
    def instance(cls) -> "FileImporterHelper":
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
        title: str = "Open File",
        import_button_label: str = "Open",
        file_extension_types: Optional[List[Tuple[str, str]]] = None,
        import_handler: Optional[
            Callable[[str, str, List[str]], None]
        ] = None,
        filename_url: Optional[str] = None,
        allow_multi_files_selection: bool = False,
        should_validate: bool = True,
    ) -> None:
        """Materialise a configured :class:`FilePickerDialog` and reveal it.

        If a dialog from a previous :meth:`show` is still live it is
        destroyed first — each call lands with the caller's exact
        configuration rather than reusing a stale one. The dialog's
        ``on_apply`` wraps ``import_handler`` with the Kit-standard
        three-arg contract, persists the Apply-time dirname to
        Settings, and hides the dialog. The dialog's ``on_cancel`` is a
        bare ``None``; the dialog's built-in hide-on-cancel path handles
        dismissal without fan-out.
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
            if self._dialog is not None:
                try:
                    selections = self._dialog.get_selection()
                except Exception:  # noqa: BLE001
                    selections = []
            self._persist_last_open_dir(dirname)
            if import_handler is not None:
                try:
                    import_handler(filename, dirname, selections)
                except Exception:  # noqa: BLE001
                    # Isolate the caller's handler so a raise does not
                    # leave the dialog stuck on screen. The reporter
                    # would be the right sink for the diagnostic, but a
                    # hard dependency on it from a wrapper that may run
                    # before Application is up would complicate the
                    # init path. Silent-swallow matches the rest of the
                    # dialog's defensive surface.
                    pass
            if self._dialog is not None:
                self._dialog.hide()

        self._dialog = FilePickerDialog(
            title=title,
            backend=self._backend,
            start_url=start_url,
            apply_button_label=import_button_label,
            cancel_button_label="Cancel",
            on_apply=_on_apply_wrapper,
            on_cancel=None,
            allow_multi_selection=allow_multi_files_selection,
            file_extension_types=extensions,
            folder_only=False,
            initial_filename=initial_filename,
            should_validate=should_validate,
            validation_mode="open",
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
        """Pick the dialog's starting directory per the content browser implementation step 53.

        Precedence: (1) ``filename_url``'s parent directory; (2) the
        Settings-persisted ``ui.content.last_open_dir``; (3) the user's
        home directory. Each step falls through on an empty / missing /
        malformed value so the helper always returns a usable URL.
        """
        if filename_url:
            parent = self._parent_url(filename_url)
            if parent:
                return parent
        settings = self._get_settings()
        if settings is not None:
            saved = settings.get(LAST_OPEN_DIR_SETTING, None)
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
        ``FileImporterExtension.show_window`` behaviour: a caller that
        wants the dialog to reopen on a specific file gets its basename
        pre-populated in the :class:`FileBar` filename field.
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

    def _persist_last_open_dir(self, dirname: str) -> None:
        """Write ``dirname`` to Settings — silent no-op if Settings unreachable."""
        if not dirname:
            return
        settings = self._get_settings()
        if settings is None:
            return
        try:
            settings.set(LAST_OPEN_DIR_SETTING, dirname)
        except Exception:  # noqa: BLE001
            pass

    def _get_settings(self) -> Optional[object]:
        """Resolve the live :class:`Settings`, honouring the test override.

        The constructor ``settings`` kwarg wins; otherwise the helper
        reaches through :meth:`Application.instance` — which raises when
        no app is up, so wrap in a try/except and return ``None`` so the
        helper can still resolve a start URL from the home fallback.
        """
        if self._settings_override is not None:
            return self._settings_override
        try:
            from ovwidgets.common.settings import Settings
            return Settings.instance()
        except Exception:  # noqa: BLE001
            return None


# ── Issue #35 Step 3: register the helper's reset_singleton classmethod
# so Application.shutdown() drops the live FilePickerDialog (and its
# ui.Window) before omni.ui.shutdown() runs. register_classmethod uses
# a stable string key `f"clsmethod:{module}.{qualname}.reset_singleton"`
# (Round 3 F3) — bound-method identity is unstable across re-imports,
# so we cannot pass FileImporterHelper.reset_singleton through register()
# directly.
from ovwidgets.common.icon_caches import register_classmethod as _register_clsmethod_for_shutdown

_register_clsmethod_for_shutdown(FileImporterHelper, "reset_singleton")
