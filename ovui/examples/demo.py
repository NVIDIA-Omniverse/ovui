# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
ovui showcase demo -- displays a rich set of widgets in a single window.
Run:  python demo.py
      python demo.py --screenshot   # headless capture to demo_screenshot.png
"""
import omni.ui as ui
from omni.ui import color as cl

import sys as _sys
_SCREENSHOT = "--screenshot" in _sys.argv
WIDTH = 700
HEIGHT = 1000 if _SCREENSHOT else 900
ui.init("ovui Showcase", width=WIDTH, height=HEIGHT)


# ---------------------------------------------------------------------------
# TreeView model
# ---------------------------------------------------------------------------
class TreeItem(ui.AbstractItem):
    def __init__(self, text):
        super().__init__()
        self.name_model = ui.SimpleStringModel(text)
        self.children = []

class TreeModel(ui.AbstractItemModel):
    def __init__(self, items):
        super().__init__()
        self._root = items

    def get_item_children(self, item):
        return self._root if item is None else item.children

    def get_item_value_model_count(self, item):
        return 1

    def get_item_value_model(self, item, column_id):
        if item is None:
            return None
        return item.name_model


scene = TreeItem("Scene")
camera = TreeItem("Camera")
lights = TreeItem("Lights")
lights.children = [TreeItem("Sun"), TreeItem("Point Light"), TreeItem("Spot Light")]
meshes = TreeItem("Meshes")
meshes.children = [TreeItem("Cube"), TreeItem("Sphere"), TreeItem("Plane")]
materials = TreeItem("Materials")
materials.children = [TreeItem("PBR Metal"), TreeItem("Glass"), TreeItem("Emissive")]
scene.children = [camera, lights, meshes, materials]
tree_model = TreeModel([scene])


## TreeDelegate and color palette are defined further below


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
ORANGE    = ui.color("#BB6620")
ORANGE_HI = ui.color("#DD8833")
BLUE      = ui.color("#3366CC")
BLUE_HI   = ui.color("#4477DD")
GREEN     = ui.color("#22AA55")
GREEN_HI  = ui.color("#33BB66")
RED       = ui.color("#CC3333")
RED_HI    = ui.color("#DD4444")
TEAL      = ui.color("#33AAAA")
MAGENTA   = ui.color("#BB2266")
BG_DARK   = ui.color("#1A1A1A")
BG_MID    = ui.color("#222222")
BG_LIGHT  = ui.color("#2D2D2D")
TEXT      = ui.color("#D0D0D0")
TEXT_DIM  = ui.color("#808080")
BORDER    = ui.color("#383838")

# ---------------------------------------------------------------------------
# Reusable styles
# ---------------------------------------------------------------------------
SECTION = {
    "CollapsableFrame": {
        "background_color": BG_MID, "secondary_color": BG_MID,
        "color": TEXT, "border_radius": 5,
        "border_color": BORDER, "border_width": 1,
        "padding": 6, "margin_height": 1, "font_size": 14,
    },
    "CollapsableFrame:hovered": {"secondary_color": BG_LIGHT},
}

SL = {
    "Slider": {
        "background_color": ui.color("#111111"), "secondary_color": ORANGE,
        "color": TEXT, "border_radius": 3,
        "draw_mode": ui.SliderDrawMode.FILLED, "font_size": 13,
    },
}

SL_BLUE = {
    "Slider": {
        "background_color": ui.color("#111111"), "secondary_color": BLUE,
        "color": TEXT, "border_radius": 3,
        "draw_mode": ui.SliderDrawMode.FILLED, "font_size": 13,
    },
}

SL_TEAL = {
    "Slider": {
        "background_color": ui.color("#111111"), "secondary_color": TEAL,
        "color": TEXT, "border_radius": 3,
        "draw_mode": ui.SliderDrawMode.FILLED, "font_size": 13,
    },
}

FLD = {
    "Field": {
        "background_color": ui.color("#111111"), "color": TEXT,
        "border_radius": 3, "border_color": BORDER,
        "border_width": 1, "font_size": 13,
    },
}

CHK = {
    "CheckBox": {
        "background_color": ui.color("#111111"), "color": TEXT_DIM,
        "border_radius": 2, "border_color": BORDER, "border_width": 1,
    },
    "CheckBox:checked": {"color": ORANGE, "background_color": ui.color("#111111")},
}

PROG = {
    "ProgressBar": {
        "background_color": ui.color("#111111"), "color": ORANGE,
        "border_radius": 3, "font_size": 12,
    },
}


M0 = {"margin": 0}  # reusable zero-margin style to block cascading


class TreeDelegate(ui.AbstractItemDelegate):
    """Custom delegate with triangle expand/collapse icons."""

    INDENT = 14   # pixels per indent level
    ICON_W = 16   # icon clickable area width

    def build_branch(self, model, item, column_id, level, expanded):
        if column_id != 0:
            return
        has_children = model.can_item_have_children(item)
        # Always reserve ICON_W so siblings align regardless of leaf/branch
        total_w = self.INDENT * level + self.ICON_W
        with ui.HStack(width=total_w, height=0, style=M0):
            if level > 0:
                ui.Spacer(width=self.INDENT * level, style=M0)
            if has_children:
                with ui.ZStack(width=self.ICON_W, height=0, style=M0):
                    if expanded:
                        ui.Triangle(
                            alignment=ui.Alignment.CENTER_BOTTOM,
                            width=10, height=8,
                            style={"background_color": TEXT, "margin": 0},
                        )
                    else:
                        ui.Triangle(
                            alignment=ui.Alignment.RIGHT_CENTER,
                            width=8, height=10,
                            style={"background_color": TEXT_DIM, "margin": 0},
                        )
            else:
                # Leaf node: empty spacer to match icon width
                ui.Spacer(width=self.ICON_W, style=M0)

    def build_widget(self, model, item, column_id, level, expanded):
        if item is None:
            return
        value_model = model.get_item_value_model(item, column_id)
        if value_model:
            ui.Label(
                value_model.as_string,
                style_type_name_override="TreeView.Item",
                style=M0,
            )


tree_delegate = TreeDelegate()


def caption(text, w=80):
    ui.Label(text, width=w, style={"color": TEXT_DIM, "font_size": 13})


def make_btn(text, bg, bg_hover=None):
    ui.Button(text, height=24, style={
        "Button": {"background_color": bg, "color": ui.color("#FFFFFF"),
                   "border_radius": 4, "margin": 1, "padding": 3, "font_size": 13},
        "Button:hovered": {"background_color": bg_hover or bg},
    })


# ---------------------------------------------------------------------------
# Build the UI
# ---------------------------------------------------------------------------
win = ui.Window(
    "ovui Showcase", width=WIDTH, height=HEIGHT,
    flags=ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
        | ui.WINDOW_FLAGS_NO_MOVE,
    position_x=0, position_y=0,
    fill_app_window=not _SCREENSHOT,
)
win.frame.set_style({"Window": {"background_color": BG_DARK, "border_color": 0x0, "border_radius": 0}})

with win.frame:
    with ui.ScrollingFrame(
        horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
        style={"ScrollingFrame": {"background_color": BG_DARK}},
    ):
        with ui.VStack(spacing=2, style={"margin": 10}):

            # ======== HEADER ========
            ui.Spacer(height=4)
            ui.Label("ovui Widget Showcase", height=28,
                     alignment=ui.Alignment.CENTER,
                     style={"font_size": 20, "color": TEXT})
            ui.Label("GPU-accelerated Python UI toolkit  |  NVIDIA Omniverse",
                     height=16, alignment=ui.Alignment.CENTER,
                     style={"font_size": 12, "color": TEXT_DIM})
            ui.Spacer(height=4)

            # ======== BUTTONS ========
            with ui.CollapsableFrame("Buttons", style=SECTION, height=0):
                with ui.HStack(spacing=4, height=0):
                    make_btn("Primary", ORANGE, ORANGE_HI)
                    make_btn("Blue", BLUE, BLUE_HI)
                    make_btn("Success", GREEN, GREEN_HI)
                    make_btn("Danger", RED, RED_HI)
                    ui.Button("Outline", height=24, style={
                        "Button": {"background_color": 0x0, "color": TEXT,
                                   "border_radius": 4, "border_color": BORDER,
                                   "border_width": 1, "margin": 1, "padding": 3, "font_size": 13},
                        "Button:hovered": {"background_color": BG_LIGHT},
                    })

            # ======== SLIDERS ========
            with ui.CollapsableFrame("Sliders & Drags", style=SECTION, height=0):
                with ui.VStack(spacing=2):
                    for name, val, style_ in [
                        ("Exposure", 0.65, SL),
                        ("Roughness", 0.35, SL_BLUE),
                        ("Metallic", 0.80, SL_TEAL),
                    ]:
                        with ui.HStack(spacing=6, height=20):
                            caption(name)
                            s = ui.FloatSlider(min=0.0, max=1.0, style=style_)
                            s.model.set_value(val)
                    for name, val, mn, mx in [
                        ("Samples", 64, 1, 256),
                        ("Bounces", 8, 1, 32),
                    ]:
                        with ui.HStack(spacing=6, height=20):
                            caption(name)
                            s = ui.IntSlider(min=mn, max=mx, style=SL)
                            s.model.set_value(val)

            # ======== INPUT FIELDS ========
            with ui.CollapsableFrame("Input Fields", style=SECTION, height=0):
                with ui.VStack(spacing=2):
                    with ui.HStack(spacing=6, height=20):
                        caption("Name")
                        f = ui.StringField(style=FLD)
                        f.model.set_value("Untitled Scene")
                    with ui.HStack(spacing=6, height=20):
                        caption("Position")
                        for v in [12.5, -3.0, 42.0]:
                            f = ui.FloatField(style=FLD)
                            f.model.set_value(v)
                    with ui.HStack(spacing=6, height=20):
                        caption("Resolution")
                        for v in [1920, 1080]:
                            f = ui.IntField(style=FLD)
                            f.model.set_value(v)

            # ======== CHECKBOXES & PROGRESS ========
            with ui.CollapsableFrame("Checkboxes & Progress", style=SECTION, height=0):
                with ui.VStack(spacing=2):
                    for text, checked in [
                        ("Enable ray tracing", True),
                        ("Show wireframe overlay", False),
                        ("Auto-save on exit", True),
                        ("Denoise final output", True),
                    ]:
                        with ui.HStack(spacing=6, height=18):
                            cb = ui.CheckBox(width=18, style=CHK)
                            cb.model.set_value(checked)
                            ui.Label(text, style={"color": TEXT, "font_size": 13})

                    ui.Spacer(height=3)
                    ui.Label("Asset Loading -- 73%", height=14,
                             style={"color": TEXT_DIM, "font_size": 11})
                    pb1 = ui.ProgressBar(style=PROG, height=14)
                    pb1.model.set_value(0.73)
                    ui.Spacer(height=1)
                    ui.Label("Texture Compilation -- Complete", height=14,
                             style={"color": TEXT_DIM, "font_size": 11})
                    pb2 = ui.ProgressBar(style={
                        "ProgressBar": {**PROG["ProgressBar"], "color": GREEN},
                    }, height=14)
                    pb2.model.set_value(1.0)

            # ======== TREE VIEW ========
            with ui.CollapsableFrame("Scene Hierarchy", style=SECTION, height=0):
                with ui.ScrollingFrame(
                    height=220,
                    horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                    vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                    style={"ScrollingFrame": {
                        "background_color": BG_DARK,
                        "border_radius": 3,
                        "margin": 0,
                    }},
                ):
                    _tv = ui.TreeView(
                        tree_model, root_visible=False, height=0,
                        delegate=tree_delegate,
                        style={
                            "margin": 0,
                            "TreeView": {
                                "background_color": 0x0,
                                "color": TEXT,
                                "font_size": 14,
                                "border_radius": 3,
                                "margin": 0,
                            },
                            "TreeView:selected": {
                                "background_color": ORANGE,
                            },
                            "TreeView.Item": {
                                "color": TEXT,
                                "margin": 0,
                            },
                            "TreeView.Item:selected": {
                                "color": ui.color("#FFFFFF"),
                            },
                            # Reset margin on all internal widget types
                            # to block cascading from outer VStack
                            "VStack": {"margin": 0},
                            "HStack": {"margin": 0},
                            "ZStack": {"margin": 0},
                            "Spacer": {"margin": 0},
                            "Label":  {"margin": 0},
                            "Frame":  {"margin": 0},
                            "Triangle": {"margin": 0},
                        },
                    )

            # ======== SHAPES & COLORS ========
            with ui.CollapsableFrame("Shapes & Colors", style=SECTION, height=0):
                with ui.VStack(spacing=4):
                    # Shape showcase row
                    with ui.HStack(spacing=6, height=68):
                        for label_t, shape_cls, col in [
                            ("Rectangle", ui.Rectangle, ORANGE),
                            ("Circle", ui.Circle, BLUE),
                            ("Triangle", ui.Triangle, GREEN),
                            ("Ellipse", ui.Ellipse, MAGENTA),
                        ]:
                            with ui.VStack(width=0, spacing=3):
                                with ui.Frame(height=46):
                                    shape_cls(style={
                                        "background_color": col,
                                        "border_radius": 6 if shape_cls == ui.Rectangle else 0,
                                    })
                                ui.Label(label_t, height=16, alignment=ui.Alignment.CENTER,
                                         style={"color": TEXT, "font_size": 11})

                    # Gradient palette rows
                    palettes = [
                        [ui.color("#1122EE"), ui.color("#2244FF"), ui.color("#4466FF"), ui.color("#6688FF"), ui.color("#88AAFF"), ui.color("#AABBFF"),
                         ui.color("#BB6620"), ui.color("#CC7733"), ui.color("#DD9944"), ui.color("#EEBB66"), ui.color("#FFDD88"), ui.color("#FFEEAA")],
                        [ui.color("#11AA44"), ui.color("#33CC66"), ui.color("#55DD77"), ui.color("#77EE99"), ui.color("#99FFBB"), ui.color("#BBFFDD"),
                         ui.color("#AA1155"), ui.color("#CC3377"), ui.color("#DD5599"), ui.color("#EE77BB"), ui.color("#FF99DD"), ui.color("#FFBBEE")],
                    ]
                    for row in palettes:
                        with ui.HStack(spacing=2, height=18):
                            for c in row:
                                ui.Rectangle(style={"background_color": c, "border_radius": 3})

            # ======== FOOTER ========
            ui.Spacer(height=6)
            with ui.HStack(height=1):
                ui.Rectangle(style={"background_color": BORDER})
            ui.Spacer(height=4)
            ui.Label("Powered by Dear ImGui + OpenGL  |  NVIDIA ovui",
                     height=16, alignment=ui.Alignment.CENTER,
                     style={"font_size": 11, "color": TEXT_DIM})
            ui.Spacer(height=8)


# ---------------------------------------------------------------------------
# Screenshot flow (async, using public testing APIs)
# ---------------------------------------------------------------------------
async def capture(path):
    from omni.ui import testing

    await testing.wait_frames(8)  # settle layout

    # Expand tree nodes for the screenshot
    _tv.set_expanded(scene, True, False)
    await testing.wait_frames(3)
    _tv.set_expanded(lights, True, False)
    await testing.wait_frames(3)
    # Leave Meshes and Materials collapsed to show ">" icon
    await testing.wait_frames(3)

    # Scroll down to show TreeView and bottom sections
    await testing.mouse_scroll(WIDTH // 2, HEIGHT // 2, dy=-10)

    # Select "Sun" to show selection highlight
    _tv.selection = [lights.children[0]]
    await testing.wait_frames(6)

    testing.capture_screenshot(path)
    print(f"Screenshot saved: {path}")


if __name__ == "__main__":
    if _SCREENSHOT:
        ui.run(capture("demo_screenshot.png"))
    else:
        ui.run()
