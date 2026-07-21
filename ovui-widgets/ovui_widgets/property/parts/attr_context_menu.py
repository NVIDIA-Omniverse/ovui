# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Attribute-row right-click context menu — Copy / Paste / Reset / Copy Path.

Right-clicking the label + value
area of a single attribute row pops a four-item menu:

* **Copy Value** — snapshots ``adapter.get_value(attr_name)`` together
  with ``metadata.type_name`` into the module-level clipboard under
  ``clipboard_id="ovgear_attr"``. Storing the type lets the subsequent
  Paste gate on type-compatibility rather than blindly overwriting.
* **Paste Value** — reads the value clipboard; writes via
  ``adapter.set_value`` wrapped in ``begin_edit`` / ``end_edit`` only
  when the stored ``type_name`` matches the target attr's
  ``metadata.type_name`` and the target is neither locked nor ambiguous
  in the clipboard snapshot (``value is None`` from an ambiguous Copy
  is intentionally skipped — pasting "mixed" over a concrete value
  would be worse than the no-op).
* **Reset to Default** — calls ``adapter.clear_value(attr_name)``.
  Adapters that do not explicitly advertise the ``clear_values`` property
  capability are detected via :func:`can_reset` so the menu item disables
  instead of appearing to work and silently failing.
* **Copy Attribute Path** — writes the composed full path string (e.g.
  ``"/World/Cube.radius"``) into the separate path clipboard under
  ``clipboard_id="ovgear_attr_path"``. Kept in its own namespace so a
  Copy Path doesn't clobber a prior Copy Value.

The clipboard dict is module-level rather than owned by the widget so
it survives panel rebuilds: selecting a different prim tears down the
:class:`ovui_widgets.property.window.PropertyWindow` contents and re-builds
them, and users copying before selecting would otherwise lose their
clipboard. Keying by ``clipboard_id`` mirrors the Step-5.3 group
namespace (``"ovgear_group"``); separating the attribute-level
namespace (``"ovgear_attr"``) from the group one means a Copy on a
single attr does not overwrite a Copy All on the surrounding group.

This module is intentionally split into two layers:

* Pure helpers (:func:`compose_attribute_path`, :func:`copy_value`,
  :func:`paste_value`, :func:`reset_value`, :func:`copy_attribute_path`,
  :func:`can_paste`, :func:`can_reset`) — no ``omni.ui`` imports;
  unit-testable without a live UI context.
* Driver (:func:`show_attr_context_menu`) — builds and shows the
  ``ui.Menu``. Only this function imports ``omni.ui``.

The split lets the tests in ``tests/test_attr_context_menu.py``
exercise the copy/paste/reset/copy-path behaviour against a
:class:`~ovui_widgets.common.testing.mock_property.MockPropertyAdapter` without
spinning up a UI root.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.parts.property_capabilities import (
    adapter_supports_clear_values,
)

# Namespace for the Copy Value / Paste Value clipboard. Paired with
# ``PATH_CLIPBOARD_ID`` below so the two actions never share storage —
# Copy Path doesn't clobber Copy Value and vice-versa.
DEFAULT_CLIPBOARD_ID = "ovgear_attr"

# Namespace for the Copy Attribute Path clipboard. Distinct from the
# value clipboard so a user who copies a path, then copies a value on a
# different attr, does not lose the path string.
PATH_CLIPBOARD_ID = "ovgear_attr_path"

# Native ``omni.ui.Menu`` instances do not accept arbitrary Python
# attributes. Keep read-only geometry handles for only the latest popup in a
# side table so Inspector state can describe the same menu a user sees.
_INSPECTOR_MENU_ITEMS: Dict[int, tuple[tuple[str, str, bool, Any], ...]] = {}


def inspector_menu_items(menu: Any) -> tuple[tuple[str, str, bool, Any], ...]:
    return _INSPECTOR_MENU_ITEMS.get(id(menu), ())

# Module-level clipboard keyed by ``clipboard_id``. Each namespace
# holds a single copied item (value record dict or path string) —
# attribute-level Copy is always single-attribute, so the inner shape
# is flat (compare :mod:`group_context_menu._CLIPBOARD`, which keys
# ``{attr_name: value}`` inside the namespace because Copy All writes
# many entries at once).
_CLIPBOARD: Dict[str, Any] = {}


def compose_attribute_path(
    adapter: PropertyAdapter, attr_name: str
) -> str:
    """Return the full attribute path string for ``attr_name``.

    Concatenates the first selected prim path and the attribute name
    with a ``.`` separator, matching USD's convention for attribute
    paths (e.g. ``"/World/Cube.radius"``). Multi-selection collapses to
    the first path — a Copy Attribute Path on a multi-selection picks
    one representative path rather than emitting a list, because the
    clipboard slot holds a single string and downstream consumers
    (future OS-clipboard integration, manual paste into another tool)
    expect a single path.

    An empty path list (disconnected adapter, or a payload that
    surfaces no prims) renders as ``".attr_name"`` — the ``.``
    separator is preserved so the caller can detect the "no prim"
    degenerate case by string.startswith('.'). Pure function; no
    mutation, no UI imports.
    """
    paths = adapter.get_paths()
    if not paths:
        return f".{attr_name}"
    return f"{paths[0]}.{attr_name}"


def copy_value(
    adapter: PropertyAdapter,
    attr_name: str,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
) -> Dict[str, Any]:
    """Snapshot the attribute's current value into the clipboard.

    Stores a ``{"type_name": str, "value": Any}`` record under
    ``_CLIPBOARD[clipboard_id]``. Overwrites any previous snapshot in
    the same namespace — a fresh Copy wins over stale data so
    "copy A → copy B → paste" pastes B's value.

    Ambiguous attributes (``adapter.is_ambiguous`` True →
    ``adapter.get_value`` returns ``None``) store as ``{"type_name":
    ..., "value": None}``; :func:`can_paste` treats a ``None`` value
    as "don't paste" so a subsequent Paste into a concrete selection
    doesn't clobber the target with "mixed". Mirrors the group-level
    Copy semantics in :mod:`ovui_widgets.property.parts.group_context_menu`.

    Returns the newly-stored record so the test suite (and a future
    tooltip) can inspect it without reaching into module-private state.
    """
    meta = adapter.get_attribute_metadata(attr_name)
    record = {
        "type_name": meta.type_name,
        "value": adapter.get_value(attr_name),
    }
    _CLIPBOARD[clipboard_id] = record
    return record


def paste_value(
    adapter: PropertyAdapter,
    attr_name: str,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
) -> bool:
    """Apply the clipboard value to ``attr_name``.

    Reads ``_CLIPBOARD[clipboard_id]``; when the stored ``type_name``
    matches ``metadata.type_name`` and the target attr is neither
    locked nor clipboard-ambiguous (``value is None``), wraps
    ``adapter.set_value`` in a ``begin_edit`` / ``end_edit`` pair so
    the write flows through the same code path as an inline edit
    (undo group, model subscribers, adapter change notifications).

    Returns ``True`` when the paste actually wrote, ``False`` for
    every rejection case (empty clipboard, type mismatch, target
    locked, clipboard value ``None``). Disable-case bookkeeping lives
    in :func:`can_paste`, but the runtime path re-checks each
    predicate in case the target was picked before the disable check
    fired.
    """
    record = _CLIPBOARD.get(clipboard_id)
    if not record:
        return False
    meta = adapter.get_attribute_metadata(attr_name)
    if record.get("type_name") != meta.type_name:
        return False
    if meta.is_locked:
        return False
    value = record.get("value")
    if value is None:
        return False
    adapter.begin_edit(attr_name)
    try:
        adapter.set_value(attr_name, value)
    finally:
        adapter.end_edit(attr_name)
    return True


def reset_value(adapter: PropertyAdapter, attr_name: str) -> bool:
    """Call ``adapter.clear_value(attr_name)`` to revert to the default.

    :func:`can_reset` filters adapters without ``clear_values`` support,
    locked attrs, and already-unauthored attrs before this action runs.
    The driver catches ``NotImplementedError`` inline in case a concrete
    adapter's ``clear_value`` raises for one specific attr (e.g.
    relationship types in the USD adapter).

    Returns ``True`` when the clear actually ran, ``False`` otherwise.
    """
    if not can_reset(adapter, attr_name):
        return False
    try:
        adapter.clear_value(attr_name)
    except NotImplementedError:
        return False
    return True


def copy_attribute_path(
    adapter: PropertyAdapter,
    attr_name: str,
    clipboard_id: str = PATH_CLIPBOARD_ID,
) -> str:
    """Store the attribute's full path string in the path clipboard.

    Uses :func:`compose_attribute_path` to build the string and writes
    it under ``_CLIPBOARD[clipboard_id]``. Distinct namespace from the
    value clipboard (``DEFAULT_CLIPBOARD_ID``) so Copy Path and Copy
    Value do not overwrite each other. Returns the stored path so
    tests can assert the exact composed string without reaching into
    module-private state.
    """
    path = compose_attribute_path(adapter, attr_name)
    _CLIPBOARD[clipboard_id] = path
    return path


def can_paste(
    adapter: PropertyAdapter,
    attr_name: str,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
) -> bool:
    """True when a Paste on ``attr_name`` would write a value.

    Folds four disable cases into one predicate: empty clipboard,
    stored ``type_name`` differs from the target's type, clipboard
    value is ``None`` (ambiguous source), or the target is locked. The
    menu item wires its ``enabled`` flag to this so the user sees a
    disabled row rather than an item that claims to work and silently
    doesn't.
    """
    record = _CLIPBOARD.get(clipboard_id)
    if not record:
        return False
    meta = adapter.get_attribute_metadata(attr_name)
    if record.get("type_name") != meta.type_name:
        return False
    if meta.is_locked:
        return False
    if record.get("value") is None:
        return False
    return True


def can_reset(adapter: PropertyAdapter, attr_name: str) -> bool:
    """True when a Reset on ``attr_name`` would clear the authored opinion.

    Disabled when the adapter does not advertise ``clear_values`` support,
    when the target attr is locked, or when it is already unauthored
    (nothing to clear). Mirrors the ``NotDefault`` predicate in
    :mod:`ovui_widgets.property.parts.control_state`: the row-level indicator
    fires on "authored + adapter can clear", and the menu-item gate uses
    the same check so the two stay consistent.
    """
    if not adapter_supports_clear_values(adapter):
        return False
    meta = adapter.get_attribute_metadata(attr_name)
    if meta.is_locked:
        return False
    if not meta.is_authored:
        return False
    return True


def get_clipboard(clipboard_id: str = DEFAULT_CLIPBOARD_ID) -> Any:
    """Return a defensive copy of the clipboard entry for ``clipboard_id``.

    Dict entries (value records) are copied so callers can't mutate
    the module-level store; string entries (path clipboard) are
    returned verbatim since strings are immutable. Returns ``None``
    for an unknown ``clipboard_id`` — :func:`can_paste` treats ``None``
    and an empty dict identically.
    """
    entry = _CLIPBOARD.get(clipboard_id)
    if isinstance(entry, dict):
        return dict(entry)
    return entry


def clear_clipboard(clipboard_id: Optional[str] = None) -> None:
    """Forget one clipboard namespace, or all namespaces.

    Used by tests to isolate fixtures; not wired to any UI today.
    Passing ``None`` drops every namespace — useful for the suite's
    session-level teardown if one ever lands. Passing a specific id
    leaves the other namespace untouched (Copy Value followed by
    ``clear_clipboard("ovgear_attr_path")`` preserves the value
    clipboard).
    """
    if clipboard_id is None:
        _CLIPBOARD.clear()
    else:
        _CLIPBOARD.pop(clipboard_id, None)


def show_attr_context_menu(
    adapter: PropertyAdapter,
    prop: AttributeMetadata,
    x: float,
    y: float,
    clipboard_id: str = DEFAULT_CLIPBOARD_ID,
    path_clipboard_id: str = PATH_CLIPBOARD_ID,
) -> Any:
    """Build and show the four-item attribute-row context menu at ``(x, y)``.

    Lazy ``omni.ui`` import keeps :mod:`attr_context_menu` headlessly
    importable from unit tests that only exercise the pure helpers.
    The built :class:`ui.Menu` is returned so callers (the row wiring
    and the UI tests) can hold on to it for the duration of the show;
    ``omni.ui`` destroys menus whose Python references are dropped,
    which would close the popup immediately.

    Menu item ``enabled`` flags read :func:`can_paste` and
    :func:`can_reset` at build time, so a Copy immediately followed by
    a menu-rebuild (the next right-click) re-evaluates both predicates
    against the fresh clipboard and metadata state — no manual
    refresh needed. Copy Value and Copy Attribute Path are always
    enabled (an ambiguous value still round-trips through the
    clipboard; :func:`can_paste` vetoes the Paste on the other side).
    """
    import omni.ui as ui

    from ovui_widgets.common.menu import create_flat_menu

    paste_enabled = can_paste(adapter, prop.name, clipboard_id)
    reset_enabled = can_reset(adapter, prop.name)

    menu = create_flat_menu()
    with menu:
        copy_item = ui.MenuItem(
            "Copy Value",
            triggered_fn=lambda: copy_value(adapter, prop.name, clipboard_id),
        )
        paste_item = ui.MenuItem(
            "Paste Value",
            enabled=paste_enabled,
            triggered_fn=lambda: paste_value(adapter, prop.name, clipboard_id),
        )
        reset_item = ui.MenuItem(
            "Reset to Default",
            enabled=reset_enabled,
            triggered_fn=lambda: reset_value(adapter, prop.name),
        )
        copy_path_item = ui.MenuItem(
            "Copy Attribute Path",
            triggered_fn=lambda: copy_attribute_path(
                adapter, prop.name, path_clipboard_id
            ),
        )
    _INSPECTOR_MENU_ITEMS.clear()
    _INSPECTOR_MENU_ITEMS[id(menu)] = (
        ("copy_value", "Copy Value", True, copy_item),
        ("paste_value", "Paste Value", paste_enabled, paste_item),
        ("reset", "Reset to Default", reset_enabled, reset_item),
        ("copy_attribute_path", "Copy Attribute Path", True, copy_path_item),
    )
    menu.show_at(float(x), float(y))
    return menu
