# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Group-header right-click context menu — Copy / Paste / Reset All.

Step 5.3 of the property inspector implementation (group context-menu behavior, the property inspector behavior). Right-clicking the header of an attribute-group
:class:`ui.CollapsableFrame` pops a three-item menu:

* **Copy All** — snapshots ``adapter.get_value(name)`` for every prop
  in this group *and all nested sub-groups* into a module-level
  clipboard dict keyed by ``clipboard_id``.
* **Paste All** — iterates the clipboard dict and, for each
  ``attr_name`` that exists in the group's recursive prop set, wraps
  ``adapter.set_value`` in the adapter's ``begin_edit`` / ``end_edit``
  pair so the write flows through the same code path as an inline
  edit (models subscribed via ``subscribe_changes`` repaint on the
  subsequent ``fire_change`` / USD notice).
* **Reset All** — calls ``adapter.clear_value(attr_name)`` on every
  attr in the group. Adapters whose ``clear_value`` is the ABC default
  (raises :class:`NotImplementedError`) are filtered out by
  :func:`can_reset` — the menu item disables rather than appearing to
  work and silently failing.

The clipboard dict is module-level rather than owned by the widget so
it survives panel rebuilds: selecting a different prim tears down the
:class:`ovwidgets.property.window.PropertyWindow` contents and re-builds
them, and users copying
before selecting would otherwise lose their clipboard. Keying by
``clipboard_id`` (default ``"ovgear_group"``) prevents cross-widget
paste contamination — the property inspector behavior notes
Kit's ``usd_general`` namespace serves the same purpose.

Recursion walks the :class:`UiDisplayGroup` tree via
:meth:`UiDisplayGroup.get_children`, so a Copy on the top-level
``Transform`` group captures every leaf under
``Transform / Translate``, ``Transform / Rotate``, … without the
caller having to flatten the tree first. This matches the upstream
Kit behaviour: "Copy All Property Values in Transform" reaches every
nested prop under that group.

This module is intentionally split into two layers:

* Pure helpers (:func:`iter_group_props`, :func:`copy_group`,
  :func:`paste_group`, :func:`reset_group`, :func:`can_paste`,
  :func:`can_reset`) — no ``omni.ui`` imports; unit-testable without
  a live UI context.
* Driver (:func:`show_group_context_menu`) — builds and shows the
  ``ui.Menu``. Only this function imports ``omni.ui``.

The split lets the tests in ``tests/test_group_context_menu.py``
exercise the copy/paste/reset behaviour against a
:class:`~ovwidgets.common.testing.mock_property.MockPropertyAdapter` without
spinning up a UI root.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional

from ovui_data_adapters.common import PropertyAdapter

from ovwidgets.property.parts.display_group import UiDisplayGroup

DEFAULT_CLIPBOARD_ID = "ovgear_group"

# Module-level clipboard. Maps ``clipboard_id`` → ``{attr_name: value}``.
# Structured as a nested dict rather than a single flat dict so multiple
# widgets with different ``clipboard_id``s can share the process-wide
# namespace without stomping on one another (the property inspector behavior). The outer key is the namespace; the inner dict is what a
# single Copy operation wrote.
_CLIPBOARD: Dict[str, Dict[str, Any]] = {}


def iter_group_props(group: UiDisplayGroup) -> Iterator[Any]:
    """Yield every ``AttributeMetadata`` in ``group`` and its sub-groups.

    Depth-first traversal; ordering within a level matches
    :meth:`UiDisplayGroup.get_children` (sub-groups yielded before
    props). Callers that want a deterministic attr-name list can
    ``sorted([p.name for p in iter_group_props(g)])`` — but for Copy
    / Paste / Reset the ordering only matters for error reporting,
    which this module doesn't do.

    Pure generator; no adapter touched, no UI imports.
    """
    for child in group.get_children():
        if isinstance(child, UiDisplayGroup):
            yield from iter_group_props(child)
        else:
            yield child


def copy_group(
    adapter: PropertyAdapter,
    group: UiDisplayGroup,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
) -> Dict[str, Any]:
    """Snapshot values for every prop in ``group`` to the clipboard.

    Walks the group tree with :func:`iter_group_props` and stores
    ``{attr_name: adapter.get_value(attr_name)}`` under
    ``_CLIPBOARD[clipboard_id]``. Overwrites any previous snapshot in
    the same namespace — a fresh Copy wins over stale data so
    "copy → click elsewhere → copy again → paste" pastes the second
    snapshot's values.

    Ambiguous attributes (``adapter.is_ambiguous`` True → ``get_value``
    returns ``None``) are stored as ``None`` so a subsequent Paste
    into a non-ambiguous selection can decide to skip them — see
    :func:`paste_group`. Kit's Step 4.3 analogue does the same: the
    clipboard records what Copy saw, Paste type-checks on the way back.

    Returns the new clipboard dict for the test suite (so tests don't
    need to reach into ``_CLIPBOARD`` private state).
    """
    snapshot: Dict[str, Any] = {}
    for prop in iter_group_props(group):
        snapshot[prop.name] = adapter.get_value(prop.name)
    _CLIPBOARD[clipboard_id] = snapshot
    return snapshot


def paste_group(
    adapter: PropertyAdapter,
    group: UiDisplayGroup,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
) -> int:
    """Apply clipboard values to matching attrs in ``group``.

    Reads ``_CLIPBOARD[clipboard_id]``; for each ``attr_name`` in the
    group (recursively) that also appears in the clipboard, wraps
    ``adapter.set_value`` in a ``begin_edit`` / ``end_edit`` pair.
    Attrs whose metadata marks them :attr:`is_locked` are skipped —
    the Paste silently leaves locked rows alone rather than raising,
    matching the ``NotDefault`` click handler's "swallow the failure
    mode" convention.

    Attrs with a ``None`` clipboard value (the original selection was
    ambiguous — see :func:`copy_group`) are also skipped so a Paste
    doesn't clobber a concrete value with "mixed".

    Returns the count of attrs actually written so tests and callers
    can detect the "no matches" branch without diffing adapter state.
    """
    clipboard = _CLIPBOARD.get(clipboard_id, {})
    if not clipboard:
        return 0
    written = 0
    for prop in iter_group_props(group):
        if prop.name not in clipboard:
            continue
        value = clipboard[prop.name]
        if value is None:
            continue
        if prop.is_locked:
            continue
        adapter.begin_edit(prop.name)
        try:
            adapter.set_value(prop.name, value)
        finally:
            adapter.end_edit(prop.name)
        written += 1
    return written


def reset_group(
    adapter: PropertyAdapter,
    group: UiDisplayGroup,
) -> int:
    """Call ``adapter.clear_value`` on every (unlocked) attr in ``group``.

    Locked attrs (``metadata.is_locked`` True) are skipped for the
    same reason as :func:`paste_group` — the indicator column already
    signals "locked" and the USD layer would reject the clear anyway.

    Adapters whose ``clear_value`` is the ABC default raise
    :class:`NotImplementedError`; those adapters should be detected
    up-front via :func:`can_reset` so the menu item disables. The
    driver still catches ``NotImplementedError`` inline in case a
    third-party adapter's ``clear_value`` silently raises on one
    specific attr (e.g. relationship types in the USD adapter, which
    the property inspector behavior notes are skipped today).

    Returns the count of attrs successfully reset.
    """
    reset = 0
    for prop in iter_group_props(group):
        if prop.is_locked:
            continue
        try:
            adapter.clear_value(prop.name)
        except NotImplementedError:
            continue
        reset += 1
    return reset


def can_paste(
    adapter: PropertyAdapter,
    group: UiDisplayGroup,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
) -> bool:
    """True when a Paste on this group would write at least one attr.

    Folds three disable cases into one check: empty clipboard, no
    overlap between clipboard keys and group attrs, or every matching
    attr is locked. The menu item wires its ``enabled`` flag to this
    so the user sees a disabled row rather than an item that claims
    to work and silently doesn't.
    """
    clipboard = _CLIPBOARD.get(clipboard_id, {})
    if not clipboard:
        return False
    for prop in iter_group_props(group):
        if prop.name not in clipboard:
            continue
        if clipboard[prop.name] is None:
            continue
        if prop.is_locked:
            continue
        return True
    return False


def can_reset(
    adapter: PropertyAdapter,
    group: UiDisplayGroup,
) -> bool:
    """True when a Reset on this group would clear at least one attr.

    Disabled when the adapter has no ``clear_value`` override (the
    ABC default raises) or when every attr in the group is locked or
    unauthored. Mirrors the NotDefault predicate in
    :mod:`ovwidgets.property.parts.control_state`: "authored + adapter can
    clear" is what the row-level indicator fires on, and the
    group-level menu uses the same gate so the two stay consistent.
    """
    if type(adapter).clear_value is PropertyAdapter.clear_value:
        return False
    for prop in iter_group_props(group):
        if prop.is_locked:
            continue
        if not prop.is_authored:
            continue
        return True
    return False


def get_clipboard(clipboard_id: str = DEFAULT_CLIPBOARD_ID) -> Dict[str, Any]:
    """Return a copy of the clipboard dict for ``clipboard_id``.

    Defensive copy so callers (tests, future UI tooltip) cannot mutate
    the module-level store directly. Returns ``{}`` for an unknown
    ``clipboard_id``; that's also what :func:`can_paste` treats as
    "empty".
    """
    return dict(_CLIPBOARD.get(clipboard_id, {}))


def clear_clipboard(clipboard_id: Optional[str] = None) -> None:
    """Forget the clipboard for one namespace, or all namespaces.

    Used by tests to isolate fixtures; not wired to any UI today.
    Passing ``None`` drops every namespace — useful for the suite's
    session-level teardown if one ever lands.
    """
    if clipboard_id is None:
        _CLIPBOARD.clear()
    else:
        _CLIPBOARD.pop(clipboard_id, None)


def show_group_context_menu(
    adapter: PropertyAdapter,
    group: UiDisplayGroup,
    x: float,
    y: float,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
) -> Any:
    """Build and show the three-item context menu at ``(x, y)``.

    Lazy ``omni.ui`` import keeps :mod:`group_context_menu` headlessly
    importable from unit tests that only exercise the pure helpers.
    The built :class:`ui.Menu` is returned so callers (the
    ``AttributeGroupWidget`` wiring and the UI tests) can hold on to
    it for the duration of the show; ``omni.ui`` destroys menus whose
    Python references are dropped, which would close the popup
    immediately.

    Item disabled/enabled wiring reads :func:`can_paste` and
    :func:`can_reset` at build time. A Copy immediately followed by a
    menu-rebuild (the next right-click) re-evaluates both predicates
    against the fresh clipboard state — no manual refresh needed.
    """
    import omni.ui as ui

    from ovwidgets.common.menu import create_flat_menu

    group_label = group.name or "Group"
    paste_enabled = can_paste(adapter, group, clipboard_id)
    reset_enabled = can_reset(adapter, group)

    menu = create_flat_menu()
    with menu:
        ui.MenuItem(
            f"Copy All Property Values in {group_label}",
            triggered_fn=lambda: copy_group(adapter, group, clipboard_id),
        )
        ui.MenuItem(
            f"Paste All Property Values in {group_label}",
            enabled=paste_enabled,
            triggered_fn=lambda: paste_group(adapter, group, clipboard_id),
        )
        ui.MenuItem(
            f"Reset All Property Values in {group_label}",
            enabled=reset_enabled,
            triggered_fn=lambda: reset_group(adapter, group),
        )
    menu.show_at(float(x), float(y))
    return menu
