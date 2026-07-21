# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FilePickerDialog — window wrapping :class:`FileBrowserWidget`.

See the content browser behavior (FilePicker Engine), §12.2
(:class:`FilePickerDialog` key kwargs + chrome), and the content browser
implementation step 47. The dialog is the regular floating
window ``File > Open`` / ``Save As`` drives. It wraps a full
:class:`FileBrowserWidget` inside a :class:`ui.Window` carrying
``NO_DOCKING`` / ``NO_SCROLLBAR`` so the picker keeps native title chrome,
cannot dock, and defers every scrolling surface to the inner widget.

Step 47 shipped the window shell with an inline filename row; Step 48
replaces that inline row with a proper :class:`FileBar` — a combo-box
extension filter, apply-disabled-until-typed affordance, and
identifier-based Apply / Cancel buttons. The dialog's
:meth:`get_filename` / :meth:`set_filename` / :meth:`get_directory` /
:meth:`get_selection` / :meth:`navigate_to` public surface is unchanged
across the swap; all callers route through the same methods.

**Result contract (§12.7).** Callback-based, not Future/awaitable.
``on_apply(filename, dirname)`` fires on Apply;
``on_cancel(filename, dirname)`` fires on Cancel or ESC. Signatures are
identical — the caller interprets what "filename + dirname" means for
open vs. save. The dialog itself performs no validation; wrappers
(``file_importer`` / ``file_exporter``, Step 61+) optionally run a
post-Apply ``backend.stat`` check.

**Lifecycle.** Constructor is cheap (no ovui side effects).
:meth:`show` lazy-builds the window on first call and sets
``visible=True``; subsequent :meth:`show` / :meth:`hide` toggle the
visibility flag without rebuilding. :meth:`destroy` tears down the
widget and window; a subsequent :meth:`show` rebuilds from scratch.
This matches the pattern the Kit filepicker uses so callers can hold
a single instance as a field and drive open / save cycles through
visibility toggles.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import omni.ui as ui

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.content.backends.backend_adapter import BackendAdapter, BackendResult
from ovui_widgets.content.backends.local_fs_backend import LocalFSBackend
from ovui_widgets.content.widget.file_bar import FileBar
from ovui_widgets.content.widget.file_browser_widget import (
    FileBrowserWidget,
)
from ovui_widgets.content.widget.file_item import FileItem

# Popup window title prefix. ovui uses the window title as its registry
# key — suffixing ``id(self)`` at construction time keeps back-to-back
# dialogs (e.g. an Open dialog rebuilt after a Cancel) from colliding
# in that registry. Same pattern as :class:`SimpleInputDialog` /
# :class:`ConfirmDeleteDialog`.
_WINDOW_TITLE_PREFIX = "OvGear_FilePickerDialog_"

# File Open is a regular floating window with native title chrome.
# ``NO_DOCKING`` keeps the dialog out of the workspace dock tree;
# ``NO_SCROLLBAR`` defers every scrolling surface to the inner
# :class:`FileBrowserWidget`'s own scrolling frames.
_WINDOW_FLAGS = (
    ui.WINDOW_FLAGS_NO_DOCKING
    | ui.WINDOW_FLAGS_NO_SCROLLBAR
)

# Default dialog size. the content browser behavior specifies
# 1000×600 — the user can resize (no ``NO_RESIZE`` flag). The size is
# a constructor-default ``width`` / ``height`` on :class:`ui.Window`
# so a future persistent setting (``persistent.exts.<...>.window_size``
# in §12.1's Kit parity) can override without touching this module.
_DEFAULT_WIDTH = 1000
_DEFAULT_HEIGHT = 600

# Height of the :class:`FileBar` row. 32 px matches the Step 47 inline
# filename row the :class:`FileBar` replaces so the dialog's overall
# layout reads the same post-swap; the bar internally centers 24 px
# fields, combo, and buttons inside that row.
_FILENAME_ROW_HEIGHT = 32

# Key codes — ImGui-native values passed through by
# :meth:`omni.ui.Window.set_key_pressed_fn`. ESC only is bound at the
# window level; Enter is intentionally NOT bound. Enter auto-apply was
# reverted because it conflicted with tree-view keyboard focus).
_KEY_ESCAPE = 256

# Step 50 — validation-mode strings. "open" runs a backend.stat(full_url)
# check + surfaces "File not found" when the file is missing; "save"
# runs an empty-filename check + surfaces "Filename is empty". Kit's
# filepicker splits the two checks across file_importer / file_exporter
# wrappers (architecture §12.7); ovgear collapses them into a single
# ``validation_mode`` kwarg so the dialog owns the whole Apply-time
# contract and the wrappers (Steps 53 / 56) just pass "open" / "save".
_VALIDATION_MODE_OPEN = "open"
_VALIDATION_MODE_SAVE = "save"

# Step 50 — user-facing validation messages. Kept as module-level
# constants so the test module can import and assert them verbatim
# (same pattern as :data:`_FOLDER_NOT_FOUND_MESSAGE` in the widget).
_VALIDATION_FILE_NOT_FOUND = "File not found"
_VALIDATION_EMPTY_FILENAME = "Filename is empty"


class FilePickerDialog:
    """Modal file picker wrapping a :class:`FileBrowserWidget`.

    Construction is cheap — no ovui side effects. :meth:`show`
    materialises the :class:`ui.Window` on first call, and subsequent
    :meth:`show` / :meth:`hide` toggle ``visible``. :meth:`destroy`
    fully tears down the widget + window; a post-destroy :meth:`show`
    rebuilds from scratch. The public accessors
    (:meth:`get_filename` / :meth:`get_directory` / :meth:`get_selection`
    / :meth:`set_filename` / :meth:`navigate_to`) are safe to call in
    any lifecycle state — they read from the field / widget when live
    and from the cached constructor state when not.

    The ``on_apply`` / ``on_cancel`` callbacks share the
    ``(filename: str, dirname: str)`` signature. The dialog itself does not validate; the
    caller interprets what the two strings mean and decides whether
    to read, write, overwrite, etc.
    """

    def __init__(
        self,
        title: str,
        backend: Optional[BackendAdapter] = None,
        start_url: Optional[str] = None,
        apply_button_label: str = "Open",
        cancel_button_label: str = "Cancel",
        on_apply: Optional[Callable[[str, str], None]] = None,
        on_cancel: Optional[Callable[[str, str], None]] = None,
        allow_multi_selection: bool = False,
        file_extension_types: Optional[List[Tuple[str, str]]] = None,
        folder_only: bool = False,
        initial_filename: str = "",
        should_validate: bool = False,
        validation_mode: str = _VALIDATION_MODE_OPEN,
    ) -> None:
        self._title: str = title
        self._backend: BackendAdapter = (
            backend if backend is not None else LocalFSBackend()
        )
        # ``start_url`` defaults to the backend's normalised home
        # directory — same fallback :class:`ContentBrowserWindow`
        # applies so a constructor that omits ``start_url`` does not
        # crash on a backend whose root enumeration happens to be
        # empty. The widget layer normalises on ``set_root_url`` too,
        # but seeding here keeps :meth:`get_directory` honest before
        # the first show.
        if start_url is None:
            import os
            default_start = os.path.expanduser("~")
            start_url = self._backend.normalize_url(f"file://{default_start}")
        self._start_url: str = start_url
        self._apply_label: str = apply_button_label
        self._cancel_label: str = cancel_button_label
        self._on_apply: Optional[Callable[[str, str], None]] = on_apply
        self._on_cancel: Optional[Callable[[str, str], None]] = on_cancel
        # ``allow_multi_selection`` is consumed by Step 51 (detail-
        # selection → filename autofill). ``file_extension_types`` is
        # wired into the :class:`FileBar` combo at Step 48;
        # ``folder_only`` switches the label to "Folder name:" in the
        # bar. Keeping them as attributes lets Step 49's glob-filter
        # wiring pull from ``self._file_extension_types`` without
        # re-plumbing the constructor signature.
        self._allow_multi_selection: bool = bool(allow_multi_selection)
        self._file_extension_types: List[Tuple[str, str]] = list(
            file_extension_types or [],
        )
        self._folder_only: bool = bool(folder_only)
        # Step 50 — validation kwargs. ``should_validate`` gates whether
        # any validation runs at all; ``validation_mode`` picks the
        # check (stat for open, non-empty for save). Invalid mode strings
        # fall back to "open" so a typo does not silently disable
        # validation.
        self._should_validate: bool = bool(should_validate)
        self._validation_mode: str = (
            validation_mode if validation_mode in (
                _VALIDATION_MODE_OPEN, _VALIDATION_MODE_SAVE,
            ) else _VALIDATION_MODE_OPEN
        )
        # Cached filename — held as a plain string so :meth:`get_filename`
        # / :meth:`set_filename` work before the first :meth:`show` (the
        # field does not exist yet) and after :meth:`destroy` (the field
        # is gone). The first build pushes the cached value into the
        # live field; every subsequent read pulls from the field so
        # user-typed input wins.
        self._filename: str = initial_filename or ""

        # Live ovui references — populated by :meth:`_build_window`,
        # nulled by :meth:`destroy`. ``None`` before the first show and
        # after destroy so every method that touches the live surface
        # short-circuits cleanly.
        self._window: Optional[ui.Window] = None
        self._widget: Optional[FileBrowserWidget] = None
        # Step 48 — the Step-47 inline filename row is replaced by a
        # :class:`FileBar`. ``_filename_field`` is kept as an alias to
        # the bar's internal field so the pre-Step-48 test surface
        # (``dlg._filename_field.model.get_value_as_string()`` etc.)
        # keeps working across the swap. ``_apply_button`` /
        # ``_cancel_button`` are dropped — the bar owns them now.
        self._file_bar: Optional[FileBar] = None
        self._filename_field: Optional[ui.StringField] = None

    # ── Public surface ───────────────────────────────────────────────────

    def show(self, path: Optional[str] = None) -> None:
        """Materialise (first call) or reveal (subsequent) the dialog.

        Lazy-builds the window + widget on first invocation so the
        constructor stays side-effect-free. Subsequent calls set the
        existing window's ``visible`` flag to ``True`` — this keeps the
        widget's internal state (selection, expanded folders, scroll
        position) intact across open / save cycles.

        When ``path`` is non-``None``, routes through :meth:`navigate_to`
        after the window is live so the caller can specify a starting
        folder at show-time (e.g. "open the folder containing the
        currently-open USD stage"). Passing ``None`` (the default)
        leaves the widget on whatever folder it previously showed —
        either the constructor ``start_url`` on first show or the last
        browsed folder on re-show.
        """
        if self._window is None:
            self._build_window()
        else:
            self._window.visible = True
        if path is not None:
            self.navigate_to(path)

    def hide(self) -> None:
        """Set ``visible=False`` without tearing the dialog down.

        Preserves the widget + field state so a subsequent :meth:`show`
        re-reveals the same browser state. No-op when the window has
        not been built yet or has already been destroyed.
        """
        if self._window is not None:
            self._window.visible = False

    def destroy(self) -> None:
        """Tear down widget, window, and every ovui reference.

        Idempotent — safe to call from a caller-side teardown path
        even when the dialog was never shown. Leaves the instance in
        a consumed-but-restorable state: a subsequent :meth:`show`
        rebuilds the window from scratch. The ``on_apply`` / ``on_cancel``
        callbacks are NOT cleared by :meth:`destroy` — a caller who
        wants to drop them should do so explicitly (matches
        :class:`ConfirmDeleteDialog.destroy` which clears ``on_yes``).
        Here the dialog is designed for multi-shot reuse so the
        callbacks live across the teardown.
        """
        # Cache the current filename before the field goes away so
        # :meth:`get_filename` keeps returning the last typed value
        # post-destroy. Reads through the :class:`FileBar` when built
        # (its own :meth:`destroy` also snapshots the value) and falls
        # back to the field alias when the bar reference is missing.
        if self._file_bar is not None:
            try:
                self._filename = self._file_bar.filename
            except Exception:  # noqa: BLE001
                pass
        elif self._filename_field is not None:
            try:
                self._filename = (
                    self._filename_field.model.get_value_as_string()
                )
            except Exception:  # noqa: BLE001
                # Defensive: ovui may raise if the field was torn down
                # under us between the read and this call.
                pass
        window = self._window
        widget = self._widget
        file_bar = self._file_bar
        self._window = None
        self._widget = None
        self._file_bar = None
        self._filename_field = None
        if file_bar is not None:
            try:
                file_bar.destroy()
            except Exception:  # noqa: BLE001
                # FileBar destroy should not raise; if it does, swallow
                # so the widget / window destroy below still run.
                pass
        if widget is not None:
            try:
                widget.destroy()
            except Exception:  # noqa: BLE001
                # Widget destroy should not raise; if it does (e.g.
                # already torn-down state), swallow so the window
                # destroy below still runs.
                pass
        if window is not None:
            try:
                window.set_key_pressed_fn(None)
            except Exception:  # noqa: BLE001
                # Older ovui versions may not expose the setter; the
                # destroy() below still runs.
                pass
            try:
                window.visible = False
            except Exception:  # noqa: BLE001
                pass
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass

    # ── Accessors ────────────────────────────────────────────────────────

    def get_filename(self) -> str:
        """Return the current filename from the :class:`FileBar` (or cache).

        Reads through :attr:`FileBar.filename` when built (which in
        turn reads from the live :class:`ui.StringField`), falling back
        to the cached ``_filename`` attribute when not. The cache is
        seeded by ``initial_filename`` at construction time, kept in
        sync by :meth:`set_filename`, and refreshed from the bar on
        :meth:`destroy` so the last typed value survives a teardown.
        """
        if self._file_bar is not None:
            try:
                return self._file_bar.filename
            except Exception:  # noqa: BLE001
                return self._filename
        return self._filename

    def set_filename(self, name: str) -> None:
        """Write ``name`` to the :class:`FileBar` and the cache.

        When the bar is live, delegates to :attr:`FileBar.filename`
        setter (which pushes through the field model and refreshes the
        Apply button's enabled gate). When not, caches the value so the
        next :meth:`show` seeds the bar with it on first build.
        """
        self._filename = name or ""
        if self._file_bar is not None:
            try:
                self._file_bar.filename = self._filename
            except Exception:  # noqa: BLE001
                # Defensive: ovui may raise if the bar was torn down
                # between the caller's check and this call.
                pass

    def get_directory(self) -> str:
        """Return the detail pane's current root URL.

        Reads from the widget's detail model when built, falling back
        to the constructor ``start_url`` when not. The detail model's
        ``root_url`` tracks every navigation (nav-pane click, browser
        bar apply, double-click drill-in) so callers always see the
        folder the user is currently browsing.
        """
        if self._widget is not None:
            detail_model = getattr(self._widget, "_detail_model", None)
            if detail_model is not None:
                root_url = getattr(detail_model, "root_url", None)
                if root_url is not None:
                    return root_url
        return self._start_url

    def get_selection(self) -> List[str]:
        """Return URLs for every selected :class:`FileItem` in the detail pane.

        Mirrors :meth:`FileBrowserWidget._resolve_multi_selection` —
        grid-view selection wins when the widget is in grid mode, else
        the detail :class:`ui.TreeView` selection. Nav-pane selections
        are intentionally NOT surfaced: they are navigation targets,
        not picker results. Returns a fresh list so callers can mutate.
        """
        if self._widget is None:
            return []
        urls: List[str] = []
        # Grid-view selection first — matches the widget's own
        # resolution order for drag / delete / copy.
        is_grid = getattr(self._widget, "_is_grid_view", False)
        grid = getattr(self._widget, "_detail_grid_view", None)
        if is_grid and grid is not None:
            try:
                for sel in grid.get_selection():
                    if isinstance(sel, FileItem):
                        urls.append(sel.url)
            except Exception:  # noqa: BLE001
                pass
        if not urls:
            tree = getattr(self._widget, "_detail_tree_view", None)
            if tree is not None:
                try:
                    for sel in tree.selection:
                        if isinstance(sel, FileItem):
                            urls.append(sel.url)
                except Exception:  # noqa: BLE001
                    pass
        return urls

    def navigate_to(self, url: str) -> None:
        """Re-root the widget's detail pane to ``url``.

        No-op when the widget has not been built yet or has been
        destroyed — matches :class:`ContentBrowserWindow.navigate_to`.
        """
        if self._widget is not None:
            self._widget.navigate_to(url)

    # ── Build ────────────────────────────────────────────────────────────

    def _build_window(self) -> None:
        """Build the window with embedded widget + filename row.

        Layout (vertical stack)::

            ui.Window(flags=NO_DOCKING | NO_SCROLLBAR):
                VStack:
                    Frame (flex) -> FileBrowserWidget
                    HStack (fixed height):
                        Label "File name:"
                        StringField  <- initial_filename seed
                        Spacer
                        Button(apply_label)
                        Button(cancel_label)

        The filename row is an inline placeholder for Step 47's
        acceptance criteria (filename input + Apply / Cancel + ESC →
        cancel); Step 48 replaces the row with a proper
        :class:`FileBar` whose combo-box extension filter + apply-
        disabled-until-typed affordances land at that step.
        """
        registry_title = f"{_WINDOW_TITLE_PREFIX}{id(self)}"
        self._window = ui.Window(
            registry_title,
            width=_DEFAULT_WIDTH,
            height=_DEFAULT_HEIGHT,
            flags=_WINDOW_FLAGS,
        )
        # Override the registry-unique title with the user-facing one
        # so the dialog's title bar shows e.g. ``"Open File"`` rather
        # than the ``_WINDOW_TITLE_PREFIX + id`` key. Older ovui builds
        # may not expose the setter; fall through silently — the user
        # still sees a labelled dialog with the registry suffix.
        try:
            self._window.title = self._title
        except Exception:  # noqa: BLE001
            pass
        # Bind ESC at the window level so the cancel affordance works
        # regardless of which child widget holds ImGui focus. The
        # :class:`FileBrowserWidget`'s :class:`BrowserBar` path field,
        # :class:`SearchField`, and detail :class:`ui.TreeView` each
        # have their own focus handlers; binding at the window level
        # catches ESC before it reaches any of them.
        try:
            self._window.set_key_pressed_fn(self._on_window_key_pressed)
        except Exception:  # noqa: BLE001
            # Older ovui versions may not expose the setter; the Cancel
            # button still fires correctly.
            pass
        with self._window.frame:
            self._build_content()

    def _build_content(self) -> None:
        """Populate the window frame with widget + :class:`FileBar`."""
        with ui.ZStack():
            ui.Rectangle(
                style_type_name_override="Content.FilePickerDialog",
            )
            with ui.VStack(spacing=0):
                # Embedded browser. The wrapping frame takes the flex
                # share of the VStack; the FileBar below pins its height
                # explicitly so the VStack does not distribute the vertical
                # space evenly between the two.
                with ui.Frame():
                    # Step 51 — wire the widget's detail-selection and
                    # file-double-click callbacks to the dialog's handlers
                    # so a single-click on a file populates the FileBar and
                    # a double-click applies the dialog (standard "open"
                    # dialog UX).
                    self._widget = FileBrowserWidget(
                        backend=self._backend,
                        root_url=self._start_url,
                        on_selection_changed=(
                            self._on_widget_selection_changed
                        ),
                        on_file_double_clicked=(
                            self._on_widget_file_double_clicked
                        ),
                    )

                # FileBar — owns the filename field, extension combo, and
                # Apply / Cancel button pair. The bar's callbacks route
                # back through this dialog's :meth:`_on_apply_clicked` /
                # :meth:`_on_cancel_clicked` so the architecture §12.7
                # ``(filename, dirname)`` payload is assembled here where
                # ``dirname`` is accessible via :meth:`get_directory`.
                with ui.Frame(height=ui.Pixel(_FILENAME_ROW_HEIGHT)):
                    self._file_bar = FileBar(
                        apply_label=self._apply_label,
                        cancel_label=self._cancel_label,
                        file_extension_types=self._file_extension_types,
                        initial_filename=self._filename,
                        on_apply=self._on_filebar_apply,
                        on_cancel=self._on_filebar_cancel,
                        on_extension_changed=self._on_filebar_extension_changed,
                        label_text=(
                            "Folder name:" if self._folder_only
                            else "File name:"
                        ),
                    )
                    self._file_bar.build()
            # Expose the bar's internal field as the pre-Step-48
            # ``_filename_field`` alias so the existing dialog tests
            # (which reach into that attribute) keep working. This is
            # strictly an internal-test bridge; new code should go
            # through :meth:`get_filename` / :meth:`set_filename`.
            self._filename_field = self._file_bar._field

            # Step 49 — seed the initial glob filter from the bar's
            # default-selected extension so the picker opens with the
            # right view (e.g. an "Open USD" picker lands on the file
            # browser already filtered to ``*.usd`` etc.). Applies only
            # when extensions are configured; a dialog with no
            # ``file_extension_types`` has no combo and no filter.
            if self._file_extension_types:
                self._apply_extension_glob(self._file_bar.selected_extension)

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_window_key_pressed(
        self, key: int, mod: int, pressed: bool,
    ) -> None:
        """Route ESC → cancel at the window level.

        Fires on the release edge (``pressed`` ``False``) so any in-
        flight ovui click dispatch from the buttons completes first.
        ``mod`` is ignored — ESC with any modifier dismisses, matching
        the other content-browser dialogs.
        """
        if pressed:
            return
        if key == _KEY_ESCAPE:
            self._on_cancel_clicked()

    def _on_apply_clicked(self) -> None:
        """Fire ``on_apply(filename, dirname)`` without dismissing.

        Leaving the dialog visible after Apply lets the caller decide
        whether to :meth:`hide` (typical open / save flow) or keep
        it open (e.g. a subsequent validation-error notification that
        wants the user to correct the input in place). The default
        callback contract from architecture §12.7 is "caller typically
        hides the dialog" — that's the caller's call to make.

        Step 50 — when ``should_validate`` is True, the Apply payload is
        validated before the callback fires. Open-mode runs
        ``backend.stat(full_url)`` and rejects on anything but
        :attr:`BackendResult.OK`; save-mode rejects an empty filename.
        A rejection surfaces the reason via
        :meth:`ErrorReporter.show_warning` and suppresses the
        ``on_apply`` dispatch so the dialog stays open for the user to
        correct their input.
        """
        filename = self.get_filename()
        dirname = self.get_directory()
        if self._should_validate and not self._validate_apply(
            filename, dirname,
        ):
            return
        if self._on_apply is not None:
            self._on_apply(filename, dirname)

    def _validate_apply(self, filename: str, dirname: str) -> bool:
        """Run the Apply-time validation check; surface a warning on failure.

        Step 50. Split out of :meth:`_on_apply_clicked` so both the
        button-click path and the double-click-file path
        (:meth:`_on_widget_file_double_clicked`) share one validation
        site. Returns ``True`` when the Apply should proceed, ``False``
        when the callback must be suppressed. The "File not found" /
        "Filename is empty" warnings route through
        :meth:`ErrorReporter.show_warning` so the message lands in the
        status bar — the dialog itself stays open and the user can
        retry from the same input state.
        """
        if self._validation_mode == _VALIDATION_MODE_SAVE:
            if not filename:
                ErrorReporter.show_warning(_VALIDATION_EMPTY_FILENAME)
                return False
            return True
        # Open-mode: concatenate dirname + filename into a full URL and
        # stat it. Trim a trailing slash on ``dirname`` so the join does
        # not produce a double-slash when the browser has just re-rooted
        # to a URL that ends in ``/``. Empty filename short-circuits as
        # a miss — stat-ing the dirname itself would erroneously pass
        # validation (the folder always exists when the browser is
        # sitting on it).
        if not filename:
            ErrorReporter.show_warning(_VALIDATION_FILE_NOT_FOUND)
            return False
        full_url = dirname.rstrip("/") + "/" + filename
        result, _entry = self._backend.stat(full_url)
        if result != BackendResult.OK:
            ErrorReporter.show_warning(_VALIDATION_FILE_NOT_FOUND)
            return False
        return True

    def _on_cancel_clicked(self) -> None:
        """Fire ``on_cancel(filename, dirname)`` and hide.

        Cancel autohides the dialog because that is the useful
        default — an Apply path may want the dialog to stay open for
        validation feedback, but a Cancel path unambiguously means
        "the user is done with this surface". Callers that want the
        dialog to stay visible after Cancel can set
        :attr:`_on_cancel` to ``None`` and manage dismissal themselves.
        """
        filename = self.get_filename()
        dirname = self.get_directory()
        if self._on_cancel is not None:
            self._on_cancel(filename, dirname)
        self.hide()

    def _on_filebar_apply(self, filename: str) -> None:
        """Bridge :class:`FileBar`'s Apply notification to the dialog.

        The bar's ``on_apply`` forwards the live field value; this
        bridge ignores the forwarded filename (the architecture §12.7
        payload is built from :meth:`get_filename` + :meth:`get_directory`
        so post-Apply mutations to the field do not desync the payload)
        and routes through :meth:`_on_apply_clicked`. The forwarded
        filename is kept in the signature so Step 50's apply-handler
        wiring / Step 51's detail-selection autofill can read it without
        re-plumbing the :class:`FileBar` surface.
        """
        self._on_apply_clicked()

    def _on_filebar_cancel(self) -> None:
        """Bridge :class:`FileBar`'s Cancel notification to the dialog."""
        self._on_cancel_clicked()

    def _on_widget_selection_changed(
        self, items: List[FileItem],
    ) -> None:
        """Populate the :class:`FileBar` filename field from the detail selection.

        the content browser implementation step 51. Single-file selection → write the item's
        name into the bar. Folder selection → clear the field (the user
        has to double-click to drill in, per architecture §12.6; a
        folder name in the filename slot would be misleading). Empty
        / multi-selection → clear the field. The enclosing
        :class:`FileBar` setter refreshes the Apply-enabled gate so the
        button tracks the field's new emptiness state.
        """
        if self._file_bar is None:
            return
        if len(items) == 1 and not items[0].is_folder:
            self._file_bar.filename = items[0].name
        else:
            self._file_bar.filename = ""

    def _on_widget_file_double_clicked(self, item: FileItem) -> None:
        """Apply the dialog on a file double-click.

        the content browser implementation step 51. Standard dialog UX — double-clicking a
        file is equivalent to selecting it and pressing Apply. Writes
        the file's name into the :class:`FileBar` first so the post-
        apply payload reflects the double-clicked file (the widget's
        own selection update happens before the double-click fires, but
        ``_on_widget_selection_changed`` may not have run yet if the
        double-click hit a card whose single-click selection had not
        landed). Then routes through :meth:`_on_apply_clicked` so the
        Step-50 validation runs on the double-click path too.
        """
        if self._file_bar is not None:
            self._file_bar.filename = item.name
        self._on_apply_clicked()

    def _on_filebar_extension_changed(
        self, extension: Tuple[str, str],
    ) -> None:
        """Apply the new extension's glob filter to the browser model.

        the content browser implementation step 49. The bar fires this whenever the user
        picks a different entry from the extension combo; ``extension``
        is the ``(pattern, description)`` tuple from
        :attr:`FileBar.selected_extension`. This handler parses the
        pattern string into a list of ``fnmatch`` globs and forwards
        it to :meth:`FileBrowserModel.set_glob_filter` so the detail
        pane re-filters to the picked type. The parser handles
        multi-glob strings (``"*.usd, *.usda"``) the same way FileBar stores them.
        """
        self._apply_extension_glob(extension)

    def _apply_extension_glob(self, extension: Tuple[str, str]) -> None:
        """Parse ``extension``'s glob string and push it to the model.

        Shared by :meth:`_on_filebar_extension_changed` (runtime combo
        changes) and :meth:`_build_content`'s initial seed. No-op when
        the widget has not been built yet or the detail model is
        missing — matches every other dialog accessor's pre-build /
        post-destroy behaviour.
        """
        if self._widget is None:
            return
        detail_model = self._widget.get_detail_model()
        if detail_model is None:
            return
        glob_str, _description = extension
        patterns = self._parse_glob_string(glob_str)
        detail_model.set_glob_filter(patterns)

    @staticmethod
    def _parse_glob_string(glob_str: str) -> List[str]:
        """Split ``"*.usd, *.usda"`` into ``["*.usd", "*.usda"]``.

        Comma-delimited list per the content browser implementation step 49. Empty entries
        (leading / trailing / double commas) are dropped. Empty input
        returns an empty list, which :meth:`FileBrowserModel.set_glob_filter`
        treats as "no filter".
        """
        if not glob_str:
            return []
        return [p.strip() for p in glob_str.split(",") if p.strip()]

    # ── Test hooks ───────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        """``True`` when the window exists and is visible, ``False`` otherwise."""
        if self._window is None:
            return False
        try:
            return bool(self._window.visible)
        except Exception:  # noqa: BLE001
            return False

    @property
    def window(self) -> Optional[ui.Window]:
        """The underlying :class:`ui.Window`, or ``None`` pre-build / post-destroy."""
        return self._window

    @property
    def widget(self) -> Optional[FileBrowserWidget]:
        """The embedded :class:`FileBrowserWidget`, or ``None`` when not built."""
        return self._widget

    def _fire_apply_for_test(self) -> None:
        """Invoke the Apply handler — test-only hook.

        Drives :meth:`_on_apply_clicked` directly so tests can bypass
        the :class:`ui.Button` click dispatch (opaque to a non-ovui
        test harness). Silent no-op pre-build / post-destroy.
        """
        if self._window is None:
            return
        self._on_apply_clicked()

    def _fire_cancel_for_test(self) -> None:
        """Invoke the Cancel handler — test-only hook."""
        if self._window is None:
            return
        self._on_cancel_clicked()

    def _fire_key_for_test(self, key: int) -> None:
        """Drive the window-level key handler — test-only hook."""
        if self._window is None:
            return
        self._on_window_key_pressed(key, 0, False)
