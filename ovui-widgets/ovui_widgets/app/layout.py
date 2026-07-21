# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Window layout management for OvGear.

Application layout helpers serialize and restore the default dock layout.
"""

import json
import os

# Reference layout in logical (DPI-unaware) pixels. The real values are
# computed at call time so the window ends up at the same visual size on
# high-DPI displays. Anything written into imgui.ini is in physical
# pixels because the GLFW backend creates the window pre-scaled to the
# monitor's content scale, and ImGui positions dock nodes in the
# framebuffer's coordinate system.
_REF_WIDTH = 1280
_REF_HEIGHT = 720
_REF_MENU_BAR_HEIGHT = 20
# Reference design (OvuiSampleApp.png, 1920x1080) shows a slightly wider
# right inspector than left Stage column, with the upper-left Stage stack
# dominating the lower-left tab stack. Keep the current panel inventory but
# tune the dock geometry toward those proportions at the 1280x720 baseline.
_REF_LEFT_PANEL = 240
_REF_RIGHT_PANEL = 300
_REF_VIEWPORT_WIDTH = _REF_WIDTH - _REF_LEFT_PANEL - _REF_RIGHT_PANEL  # 740
_REF_VIEWPORT_HEIGHT_RATIO = 0.62
_REF_CONTENT_HEIGHT_RATIO = 1.0 - _REF_VIEWPORT_HEIGHT_RATIO
_VISIBLE_DOCK_TAB_FLAGS = " NoWindowMenuButton=1 NoCloseButton=1"
_PANEL_DOCK_TITLES = (
    "Stage Browser",
    "Property Inspector",
    "Viewport",
    "Content",
    "Layers",
)


def _get_dpi_scale() -> float:
    """Return the current UI DPI scale as seen by omni.ui.

    omni.ui is the single source of truth for DPI — it owns the GLFW
    window, handles per-monitor DPI awareness, and may also apply
    programmatic overrides (e.g. for tests). Before ``ui.init()`` this
    returns 1.0, so ``write_split_ini`` must run AFTER ``ui.init()``
    for the dock tree to scale with the monitor's content scale.
    ImGui only loads ``imgui.ini`` on its first ``NewFrame``, not at
    context creation, so the window between ``ui.init()`` and the
    first frame is the correct point to write the file.
    """
    try:
        import omni.ui as ui
        scale = float(ui.Workspace.get_dpi_scale())
        return scale if scale > 0.0 else 1.0
    except (ImportError, AttributeError, RuntimeError):
        return 1.0


def _scaled(ref: int, scale: float) -> int:
    return int(round(ref * scale))


# These values are in *logical* pixels and consumed by ovui APIs
# (ui.Window.width/height, style constants) that apply the DPI multiplier
# themselves. On a 1.0x display they are identical to the original
# hardcoded numbers, preserving Linux/stock-DPI behavior.
MENU_BAR_HEIGHT = _REF_MENU_BAR_HEIGHT
# Public alias for the reference side-panel width so callers outside this
# module (e.g. application._on_remote_mouse_pressed for filter-bar hit
# testing) share one source of truth with the imgui.ini split layout.
SIDE_PANEL_WIDTH = _REF_LEFT_PANEL
# DockSpace.cpp adds ImGuiStyle.DockingSeparatorSize above the dock area.
# Step 20 pins that separator to 1 px, so padding preserves y=MENU_BAR_HEIGHT.
DOCKSPACE_TOP_PADDING = MENU_BAR_HEIGHT - 1


def _build_split_ini() -> str:
    """Return the canonical split-layout imgui.ini, DPI-scaled.

    All pixel values in imgui.ini are in physical pixels. The GLFW backend
    creates the window pre-scaled by the monitor's content scale, so the
    dock tree must match that scaled framebuffer size.

    IDs derived from the actual runtime values of ui.MainWindow():
      DockSpace root = 0x0FCAA000, "DockSpace" window = 0x3DA2F1DE
      Window CRC32 IDs: Stage Browser=0x5959BE22, Property Inspector=0xDBC7B7B0,
                        Viewport=0x995B0CF8, Content=0x31780935

    Layout tree (left→right columns, viewport column split top/bottom):

      DockSpace (Split=X)
        ├─ 0x00000003  Stage Browser (left, 240px)
        └─ 0x00000002  middle+right (Split=X)
            ├─ 0x00000005  middle column (Split=Y)
            │   ├─ 0x00000006  Viewport (top, CentralNode)
            │   └─ 0x00000007  Content (bottom)
            └─ 0x00000004  Property Inspector (right, 300px)

    Layers is NOT pre-docked through this ini: the startup split ini
    describes the four base panels only. :func:`apply_default_layout`
    splits the Stage node at runtime and lands Layers in the lower half
    via ``window.dock_in(stage_handle, ui.DockPosition.BOTTOM)`` so the
    stage hierarchy sits above its layer stack on the left column.
    """
    scale = _get_dpi_scale()
    width = _scaled(_REF_WIDTH, scale)
    height = _scaled(_REF_HEIGHT, scale)
    menu = _scaled(_REF_MENU_BAR_HEIGHT, scale)
    left = _scaled(_REF_LEFT_PANEL, scale)
    right = _scaled(_REF_RIGHT_PANEL, scale)
    vp_w = width - left - right
    middle_right_w = width - left
    content_h = height - menu
    vp_h = int(content_h * _REF_VIEWPORT_HEIGHT_RATIO)
    content_panel_h = content_h - vp_h
    right_col_x = left + vp_w
    content_panel_top = menu + vp_h
    return f"""\
[Window][Stage Browser]
Pos=0,{menu}
Size={left},{content_h}
Collapsed=0
DockId=0x00000003,0

[Window][Property Inspector]
Pos={right_col_x},{menu}
Size={right},{content_h}
Collapsed=0
DockId=0x00000004,0

[Window][Viewport]
Pos={left},{menu}
Size={vp_w},{vp_h}
Collapsed=0
DockId=0x00000006,0

[Window][Content]
Pos={left},{content_panel_top}
Size={vp_w},{content_panel_h}
Collapsed=0
DockId=0x00000007,0

[Window][DockSpace]
Pos=0,0
Size={width},{height}
Collapsed=0

[Docking][Data]
DockSpace         ID=0x0FCAA000 Window=0x3DA2F1DE Pos=0,{menu} Size={width},{content_h} Split=X
  DockNode        ID=0x00000003 Parent=0x0FCAA000 SizeRef={left},{content_h} Selected=0x5959BE22{_VISIBLE_DOCK_TAB_FLAGS}
  DockNode        ID=0x00000002 Parent=0x0FCAA000 SizeRef={middle_right_w},{content_h} Split=X
    DockNode      ID=0x00000005 Parent=0x00000002 SizeRef={vp_w},{content_h} Split=Y
      DockNode    ID=0x00000006 Parent=0x00000005 SizeRef={vp_w},{vp_h} CentralNode=1 Selected=0x995B0CF8{_VISIBLE_DOCK_TAB_FLAGS}
      DockNode    ID=0x00000007 Parent=0x00000005 SizeRef={vp_w},{content_panel_h} Selected=0x31780935{_VISIBLE_DOCK_TAB_FLAGS}
    DockNode      ID=0x00000004 Parent=0x00000002 SizeRef={right},{content_h} Selected=0xDBC7B7B0{_VISIBLE_DOCK_TAB_FLAGS}
"""


# Preserved for any import-time introspection (tests). Regenerated at
# each write_split_ini() call using the current DPI.
_SPLIT_INI = _build_split_ini()


def write_split_ini(path: str = "imgui.ini") -> None:
    """Write the canonical split-layout imgui.ini.

    Must be called AFTER ``ui.init()`` (so ``Workspace.get_dpi_scale``
    has been wired up by the platform) but BEFORE the first frame is
    rendered (ImGui loads the file lazily during its first NewFrame).
    Writing too early pins the dock tree at DPI 1.0, which produces
    half-width side panels on a 200% display.
    """
    with open(path, "w") as f:
        f.write(_build_split_ini())


def apply_default_layout() -> None:
    """Arrange windows into the default OvGear four-panel docked layout.

    Stage Browser docks to the left at 240 px in the 1280 px reference
    layout. Property Inspector docks to the right at 300 px. Content
    Browser docks below the Viewport (~38 % of the center column height).

    Must be called after at least one frame has been rendered so ImGui has
    assigned dock node IDs to the windows.  If imgui.ini already pre-docked
    the windows (normal case), this function is a no-op for those already
    docked and still anchors any window that came up floating.
    """
    try:
        import omni.ui as ui

        from ovui_widgets.app.application import Application
    except ImportError:
        return
    try:
        app = Application.instance()
    except RuntimeError:
        return

    stage_win = app._stage_window
    prop_win = app._property_window
    vp_win = app._viewport_window
    content_win = app._content_window
    layer_win = app._layer_window

    if not (stage_win and prop_win and vp_win):
        return

    # Get window handles via Workspace (works after at least one rendered frame).
    vp_handle = ui.Workspace.get_window("Viewport")
    stage_handle = ui.Workspace.get_window("Stage Browser")

    if not vp_handle or not stage_handle:
        return

    vp_dock_id = vp_handle.dock_id
    stage_dock_id = stage_handle.dock_id
    prop_handle = ui.Workspace.get_window("Property Inspector")
    content_handle = ui.Workspace.get_window("Content") if content_win else None
    prop_dock_id = prop_handle.dock_id if prop_handle else 0

    def _is_docked(handle: object | None) -> bool:
        return bool(
            handle
            and getattr(handle, "dock_id", 0) != 0
            and getattr(handle, "docked", False)
        )

    # If imgui.ini pre-docked stage + viewport into DIFFERENT nodes the
    # horizontal split is already correct — re-docking would destroy the
    # existing split nodes. Same non-zero dock_id means everything landed
    # in the DockSpace's single CentralNode and still needs to be split.
    primary_split_done = (
        _is_docked(vp_handle)
        and _is_docked(stage_handle)
        and _is_docked(prop_handle)
        and vp_dock_id != stage_dock_id
        and prop_dock_id != vp_dock_id
    )

    if not primary_split_done:
        # Fallback path: no ini, missing dock data, or all windows in the
        # same node. When Viewport is floating (dock_id=0), anchor it in the
        # root DockSpace first so dock_in() has a non-zero target to split
        # from.
        if vp_dock_id == 0:
            dockspace_win = ui.Workspace.get_window("DockSpace")
            if not dockspace_win:
                return
            # dock_in with SAME uses the "DockSpace" special-case to compute
            # the root node ID directly from
            # ImHashStr("MyDockspace", 0, DockSpace->ID).
            vp_win.window.dock_in(dockspace_win, ui.DockPosition.SAME)
            vp_handle = ui.Workspace.get_window("Viewport")
            if not vp_handle or vp_handle.dock_id == 0:
                return

        # Fallback ratios mirror the imgui.ini split: the Stage split is
        # the left panel's absolute share of the window, while Property's
        # split is its share of the remaining middle+right region.
        stage_ratio = _REF_LEFT_PANEL / _REF_WIDTH
        prop_ratio = _REF_RIGHT_PANEL / (_REF_WIDTH - _REF_LEFT_PANEL)
        stage_win.window.dock_in(vp_handle, ui.DockPosition.LEFT, ratio=stage_ratio)
        prop_win.window.dock_in(vp_handle, ui.DockPosition.RIGHT, ratio=prop_ratio)

    # Content Browser docks below Viewport. Handled independently of the
    # primary split so an old persisted layout (stage/viewport/property only)
    # still gets Content docked at first boot after this upgrade.
    if content_win and not _is_docked(content_handle):
        vp_handle = ui.Workspace.get_window("Viewport")
        if vp_handle and vp_handle.dock_id != 0:
            content_win.window.dock_in(
                vp_handle, ui.DockPosition.BOTTOM, ratio=_REF_CONTENT_HEIGHT_RATIO
            )

    # Dock Layers below Stage Browser so the stage hierarchy and its
    # layer stack read as one left-column column. DockPosition.BOTTOM
    # splits the Stage node vertically; Layers lands in the lower half
    # with Stage retained on top. Handled independently of the primary
    # split so a persisted layout missing/floating/tabbed Layers window
    # still gets it placed correctly on first boot after this upgrade.
    if layer_win is not None:
        layers_handle = ui.Workspace.get_window("Layers")
        stage_handle_now = ui.Workspace.get_window("Stage Browser")
        if stage_handle_now is not None and not _layers_docked_below_stage(
            ui, stage_handle_now, layers_handle
        ):
            layer_win.window.dock_in(
                stage_handle_now,
                ui.DockPosition.BOTTOM,
                ratio=0.30,
            )

    show_panel_dock_tab_bars()


def _layers_docked_below_stage(
    ui: object,
    stage_handle: object,
    layers_handle: object,
) -> bool:
    """Return True when Layers is a bottom sibling under Stage Browser."""
    if layers_handle is None:
        return False
    stage_dock_id = getattr(stage_handle, "dock_id", 0)
    layers_dock_id = getattr(layers_handle, "dock_id", 0)
    if not stage_dock_id or not layers_dock_id or stage_dock_id == layers_dock_id:
        return False
    if not getattr(stage_handle, "docked", False) or not getattr(
        layers_handle, "docked", False
    ):
        return False

    workspace = getattr(ui, "Workspace", None)
    dock_position = getattr(ui, "DockPosition", None)
    if workspace is None or dock_position is None:
        return False
    try:
        same_parent = (
            workspace.get_parent_dock_id(stage_dock_id)
            == workspace.get_parent_dock_id(layers_dock_id)
            != 0
        )
        return (
            same_parent
            and workspace.get_dock_position(stage_dock_id) == dock_position.TOP
            and workspace.get_dock_position(layers_dock_id) == dock_position.BOTTOM
        )
    except (AttributeError, RuntimeError):
        return False


def show_panel_dock_tab_bars() -> None:
    """Show dock-node tabs for OvGear's fixed panel inventory.

    The application keeps each panel as a real docked ``ui.Window`` so
    layout persistence, menu visibility toggles, focus, and docking state
    remain intact. PR62 made the dock tab strip part of the application
    styling, so repaired dock nodes explicitly keep their real ImGui tabs
    enabled and visible.
    """
    try:
        import omni.ui as ui
    except (RuntimeError, ImportError):
        return

    for title in _PANEL_DOCK_TITLES:
        handle = ui.Workspace.get_window(title)
        if handle is None or not getattr(handle, "docked", False):
            continue
        try:
            handle.dock_tab_bar_enabled = True
            handle.dock_tab_bar_visible = True
        except (AttributeError, RuntimeError):
            continue


def hide_panel_dock_tab_bars() -> None:
    """Compatibility wrapper for older call sites.

    Dock tabs are intentionally visible and functional; keep the historical
    function name as a non-breaking alias for tests or external scripts that
    still import it.
    """
    show_panel_dock_tab_bars()


def save_layout(path: str) -> None:
    """Save current window positions and sizes to a JSON file."""
    windows_data = _collect_layout()
    save_layout_data(path, windows_data)


def save_layout_data(path: str, windows_data: dict) -> None:
    """Write pre-collected window data to a JSON layout file."""
    expanded = os.path.expanduser(path)
    parent = os.path.dirname(os.path.abspath(expanded))
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(expanded, "w") as f:
        json.dump({"version": 1, "windows": windows_data}, f, indent=2)


def load_layout(path: str) -> None:
    """Restore window layout from a JSON file."""
    expanded = os.path.expanduser(path)
    with open(expanded) as f:
        data = json.load(f)

    _restore_layout(data.get("windows", {}))


def _collect_layout() -> dict:
    """Collect current window state from Application panel windows."""
    try:
        from ovui_widgets.app.application import Application
        app = Application.instance()
    except RuntimeError:
        return {}

    result: dict = {}
    panel_map = {
        "Stage Browser": app._stage_window,
        "Property Inspector": app._property_window,
        "Viewport": app._viewport_window,
        "Content": app._content_window,
        "Layers": app._layer_window,
    }
    for title, managed_win in panel_map.items():
        if managed_win and managed_win.window:
            w = managed_win.window
            result[title] = {
                "visible": managed_win.visible,
                "position_x": float(w.position_x),
                "position_y": float(w.position_y),
                "width": float(w.width),
                "height": float(w.height),
            }
    return result


def _restore_layout(windows: dict) -> None:
    """Restore fixed-panel visibility from saved data.

    ``layout.json`` stores only window geometry and visibility; it does
    not persist the ImGui dock tree. Applying saved position/size to one
    of OvGear's fixed dock panels can mark that window for undocking on
    the next frame, which reintroduces title bars and close glyphs. The
    dock tree is rebuilt by :func:`apply_default_layout`; this restore
    path therefore keeps only the user-visible visibility bit.
    """
    try:
        from ovui_widgets.app.application import Application
    except ImportError:
        return
    try:
        app = Application.instance()
    except RuntimeError:
        return

    panel_map = {
        "Stage Browser": app._stage_window,
        "Property Inspector": app._property_window,
        "Viewport": app._viewport_window,
        "Content": app._content_window,
        "Layers": app._layer_window,
    }
    for title, data in windows.items():
        managed_win = panel_map.get(title)
        if not managed_win or not managed_win.window:
            continue
        if "visible" in data:
            managed_win.visible = data["visible"]
        # Saved JSON has no dock-node state. For the fixed panel inventory,
        # applying stale geometry is worse than ignoring it: SetNextWindowPos
        # can make ImGui undock the panel on the next frame. The subsequent
        # default-layout pass owns docked geometry.
