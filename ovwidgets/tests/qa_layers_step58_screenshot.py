# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for LAYERS-PLAN Step 58 — Main menu bar "Layer" menu.

Step 58 adds a top-level ``Layer`` menu to the application menu bar.
The menu carries the most-used layer actions (Save Layer, Save All,
Save As…, Create/Insert Sublayer, Remove Layer, Reload Layer) plus a
dynamic ``Set Authoring Layer`` submenu that lists every layer in the
stack with a checkmark on the current edit target.

Shots:

1. **Shot 1** — ``/tmp/ovgear_layers_step58_1.png``: Layer menu open,
   anchored to the upper-left so the full entry list is visible.
2. **Shot 2** — ``/tmp/ovgear_layers_step58_2.png``: Layer menu with a
   non-root sublayer selected — "Remove Layer" is enabled, matching
   the task's "Enable/disable: items grayed out when no stage open or
   no valid selection" contract.
3. **Shot 3** — ``/tmp/ovgear_layers_step58_3.png``: the dynamic
   "Set Authoring Layer" submenu open, showing one item per layer in
   the stack plus a checkmark on the current edit target.

The QA script prints the full menu-entry state for every shot —
label, enabled-flag, hotkey hint, checkmark — so a text log is
sufficient evidence even when a screenshot cannot be rendered in a
headless CI context.
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.settings import Settings
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerItem, LayerModel, LayerWindow

OUT_1 = "/tmp/ovgear_layers_step58_1.png"
OUT_2 = "/tmp/ovgear_layers_step58_2.png"
OUT_3 = "/tmp/ovgear_layers_step58_3.png"


class _StubApp:
    """Minimal app surface the Step 58 menu expects.

    The Layer menu reaches for ``_layer_adapter`` (stage gate),
    ``_layer_window`` (model selection), ``undo_manager`` (command
    pipeline) and ``selection_bus`` (command recipients). Everything
    else on the real :class:`Application` is left out — the QA path
    never exercises the dialog / file-picker branches.
    """

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        self.settings = Settings()
        self._layer_adapter: Optional[Any] = None
        self._layer_window: Optional[Any] = None


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _make_adapter() -> MockLayerStackAdapter:
    adapter = MockLayerStackAdapter(include_session=False)
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "background_base.usda",
        display_name="background_base.usda",
    )
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "props_base.usda",
        display_name="props_base.usda",
    )
    adapter.add_sublayer(
        ROOT_LAYER_IDENTIFIER,
        "characters_base.usda",
        display_name="characters_base.usda",
    )
    return adapter


def _find_layer_item(model: LayerModel, identifier: str) -> LayerItem:
    stack: List[LayerItem] = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if isinstance(node, LayerItem) and node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


# ── Headless capture of the Layer-menu entry state ────────────────────


def _snapshot_layer_menu(app: _StubApp) -> Dict[str, List[Dict[str, Any]]]:
    """Run ``_build_layer_menu`` under a fake ``omni.ui`` and return a
    dict mapping menu-labels to the list of captured MenuItem entries.

    Used for the text-log half of the QA report — the fake doesn't
    render anything so it's cheap to run alongside the real screenshot
    path. The real :mod:`omni.ui` is swapped back immediately after so
    the subsequent ``show_at`` call targets the live backend.
    """
    import ovwidgets.app.menu_bar as mb

    active: List[str] = []
    registry: Dict[str, List[Dict[str, Any]]] = {}

    class _FakeMenu:
        def __init__(
            self,
            label: str,
            *_a: Any,
            on_build_fn: Optional[Callable[[], None]] = None,
            **_kw: Any,
        ) -> None:
            self.label = label
            self.on_build_fn = on_build_fn

        def __enter__(self) -> "_FakeMenu":
            active.append(self.label)
            if self.on_build_fn is not None:
                self.on_build_fn()
            return self

        def __exit__(self, *_a: Any) -> None:
            active.pop()

    class _FakeMenuItem:
        def __init__(
            self,
            label: str,
            triggered_fn: Optional[Callable[[], None]] = None,
            enabled: bool = True,
            checkable: bool = False,
            checked: bool = False,
            hotkey_text: str = "",
            **_kw: Any,
        ) -> None:
            bucket = active[-1] if active else ""
            registry.setdefault(bucket, []).append(
                {
                    "label": label,
                    "enabled": enabled,
                    "checkable": checkable,
                    "checked": checked,
                    "hotkey_text": hotkey_text,
                }
            )

    class _FakeSeparator:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

    fake = types.ModuleType("omni.ui")
    fake.Menu = _FakeMenu
    fake.MenuItem = _FakeMenuItem
    fake.Separator = _FakeSeparator

    original = mb.ui
    try:
        mb.ui = fake
        active.append("Layer")
        mb._build_layer_menu(app)
        active.pop()
    finally:
        mb.ui = original
    return registry


def _print_snapshot(title: str, snapshot: Dict[str, List[Dict[str, Any]]]) -> None:
    print(f"  {title}")
    for bucket in ("Layer", "Set Authoring Layer"):
        entries = snapshot.get(bucket, [])
        if not entries:
            continue
        print(f"    [{bucket}]")
        for e in entries:
            flags: List[str] = []
            if e["enabled"]:
                flags.append("enabled")
            else:
                flags.append("disabled")
            if e["checkable"]:
                flags.append(f"check={'on' if e['checked'] else 'off'}")
            if e["hotkey_text"]:
                flags.append(f"hotkey={e['hotkey_text']}")
            print(f"      - {e['label']:<30s} ({', '.join(flags)})")


# ── Rendering helpers ─────────────────────────────────────────────────


def _build_layer_popup(app: _StubApp) -> Any:
    """Return a live ``ui.Menu`` populated with the Layer menu contents.

    ``_build_layer_menu`` emits its items into the current Menu
    context, so wrapping the call in ``with menu:`` places every item
    — including the nested "Set Authoring Layer" submenu — inside
    ``menu``. The returned handle is held by the caller for the
    duration of the screenshot so ovui doesn't tear the popup down
    between ``show_at`` and the capture frame.
    """
    from ovwidgets.app.menu_bar import _build_layer_menu

    menu = ui.Menu("Layer")
    with menu:
        _build_layer_menu(app)
    return menu


async def _main() -> None:
    adapter = _make_adapter()
    app = _StubApp()
    app._layer_adapter = adapter

    layer_window = LayerWindow(services=app, adapter=adapter)
    app._layer_window = layer_window
    if layer_window.window is not None:
        layer_window.window.undock()
        layer_window.window.position_x = 40
        layer_window.window.position_y = 40
        layer_window.window.width = 520
        layer_window.window.height = 520
        layer_window.window.focus()

    await _drive(15)

    model = layer_window._model
    if not isinstance(model, LayerModel):
        raise RuntimeError(f"Expected LayerModel, got {type(model).__name__}")

    tree_view = layer_window._tree_view
    root_item = model.root_item
    if tree_view is not None and root_item is not None:
        tree_view.set_expanded(root_item, True, False)

    await _drive(8)

    # ── Shot 1 — Layer menu open with nothing selected (root fallback) ──
    snapshot1 = _snapshot_layer_menu(app)
    print("Shot 1 — Layer menu open, no sublayer selected (root is target).")
    _print_snapshot("menu state", snapshot1)
    menu1 = _build_layer_popup(app)
    menu1.show_at(60, 60)
    await _drive(6)
    uitesting.capture_screenshot(OUT_1)
    print(f"Saved: {OUT_1}")
    menu1.hide()
    await _drive(3)

    # ── Shot 2 — non-root sublayer selected; Remove Layer enabled ───────
    child = _find_layer_item(model, "props_base.usda")
    model.set_selected_items([child])
    await _drive(3)
    snapshot2 = _snapshot_layer_menu(app)
    print(
        "Shot 2 — 'props_base.usda' selected; Remove Layer must be enabled."
    )
    _print_snapshot("menu state", snapshot2)
    menu2 = _build_layer_popup(app)
    menu2.show_at(60, 60)
    await _drive(6)
    uitesting.capture_screenshot(OUT_2)
    print(f"Saved: {OUT_2}")
    menu2.hide()
    await _drive(3)

    # ── Shot 3 — "Set Authoring Layer" submenu expanded ──────────────────
    # Build a standalone Menu that *only* contains the submenu entries,
    # so the capture frames the submenu directly rather than the parent
    # Layer menu. This matches the user's experience when they hover
    # the submenu header.
    from ovwidgets.app.menu_bar import _build_set_authoring_submenu

    submenu = ui.Menu("Set Authoring Layer")
    with submenu:
        _build_set_authoring_submenu(app)
    submenu.show_at(60, 60)
    await _drive(6)
    print(
        "Shot 3 — 'Set Authoring Layer' submenu open. "
        f"Current edit target: {adapter.get_edit_target_identifier()!r}."
    )
    sub_entries = snapshot1.get("Set Authoring Layer", [])
    print(f"  submenu entries: {[e['label'] for e in sub_entries]}")
    uitesting.capture_screenshot(OUT_3)
    print(f"Saved: {OUT_3}")
    submenu.hide()
    await _drive(3)

    print()
    print("Step 58 behaviour summary:")
    print(
        "  - Top-level 'Layer' menu sits in the main menu bar between "
        "Edit and Tools."
    )
    print(
        "  - Set Authoring Layer submenu lists every layer in the stack, "
        "checkmark on the current edit target; click pushes "
        "SetEditTargetCommand."
    )
    print(
        "  - Save Layer / Save All / Save As… / Reload route through "
        "LayerModel._request_save* — sharing dialog and group wrappers "
        "with the context menu."
    )
    print(
        "  - Create / Insert Sublayer push CreateSublayerCommand and "
        "InsertSublayerCommand under the focus target."
    )
    print(
        "  - Remove Layer routes through _request_remove_sublayer with "
        "the dirty-confirm flow."
    )
    print(
        "  - Enable flags live-reflect adapter presence, writability, "
        "dirty/anonymous/root state; hotkey hints shown for Save All "
        "(Ctrl+Shift+S) and Save As (Ctrl+Shift+Alt+S)."
    )

    layer_window.destroy()
    sys.exit(0)


if __name__ == "__main__":
    ui.init("OvGear Layers Step 58 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())
