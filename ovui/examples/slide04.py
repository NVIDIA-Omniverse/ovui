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
Slide 04 - The Goal
Visual diagram: BEFORE/AFTER of extracting omni.ui from Kit monorepo.

Run:
    python slide04.py
    python slide04.py --screenshot
"""
import omni.ui as ui
import sys

_SCREENSHOT = "--screenshot" in sys.argv
WIDTH  = 1280
HEIGHT = 720

ui.init("Slide 04 - The Goal", width=WIDTH, height=HEIGHT)

# ---------------------------------------------------------------------------
# Colour palette  (format: 0xAABBGGRR)
# ---------------------------------------------------------------------------
def rgb(r, g, b, a=255):
    return (a << 24) | (b << 16) | (g << 8) | r

BG           = rgb(255, 255, 255)
HEADER_BG    = rgb( 15,  23,  42)   # #0F172A
HEADER_TEXT  = rgb(255, 255, 255)
NVIDIA_GREEN = rgb(118, 185,   0)   # #76B900
TEXT_DARK    = rgb( 31,  41,  55)   # #1F2937
TEXT_DIM     = rgb(100, 116, 139)   # #64748B

# Diagram box styles -- light backgrounds, coloured borders
BOX_BDR_DEF  = rgb(118, 185,   0)   # green border
BOX_BDR_RED  = rgb(220,  38,  38)   # red border (BEFORE)
BOX_BG_LIGHT = rgb(240, 253, 244)   # very light green fill (AFTER boxes)
BOX_BG_RED   = rgb(254, 242, 242)   # very light red fill   (BEFORE box)

# Side badges — keep coloured fills, white text
CARB_BG      = rgb(127,  29,  29)   # dark red
CARB_TXT     = rgb(255, 255, 255)
ADAPT_BG     = rgb(180,  90,   0)   # amber
ADAPT_TXT    = rgb(255, 255, 255)
BYTE_BG      = NVIDIA_GREEN
BYTE_TXT     = rgb(255, 255, 255)
GLFW_BG      = NVIDIA_GREEN
GLFW_TXT     = rgb(255, 255, 255)
PIP_BG       = rgb( 29,  78, 216)   # blue
PIP_TXT      = rgb(255, 255, 255)

# Arrows
ARROW_RED    = rgb(220,  38,  38)
ARROW_GRN    = rgb( 22, 163,  74)   # green
ARROW_NEU    = rgb( 55,  65,  81)   # dark grey

SEP          = rgb(226, 232, 240)
FOOTER_BG    = rgb(248, 250, 252)

M0 = {"margin": 0, "padding": 0}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def lbl(text, *, color=TEXT_DARK, size=16, align=ui.Alignment.LEFT, h=None, **kw):
    s = {"Label": {"color": color, "font_size": size}}
    if h is not None:
        return ui.Label(text, alignment=align, style=s, height=h, **kw)
    return ui.Label(text, alignment=align, style=s, **kw)


def box(lines, *, bg=BOX_BG_LIGHT, txt=TEXT_DARK, bdr=BOX_BDR_DEF,
        w=180, h=96, fs=15, r=7):
    with ui.ZStack(width=w, height=h, style=M0):
        ui.Rectangle(style={"Rectangle": {
            "background_color": bg,
            "border_color": bdr,
            "border_width": 2.5,
            "border_radius": r,
        }})
        with ui.VStack(style=M0):
            ui.Spacer()
            for ln in lines:
                lbl(ln, color=txt, size=fs, align=ui.Alignment.CENTER,
                    h=fs + 6)
            ui.Spacer()


def badge(text, *, bg, txt=rgb(255,255,255), w=140, h=28, fs=13, r=5):
    with ui.ZStack(width=w, height=h, style=M0):
        ui.Rectangle(style={"Rectangle": {
            "background_color": bg, "border_radius": r}})
        lbl(text, color=txt, size=fs, align=ui.Alignment.CENTER, h=h)


# Horizontal arrow → (alignment=V_CENTER draws a horizontal line)
def h_arr(w=44, color=ARROW_NEU):
    ui.Line(width=w, height=20,
            alignment=ui.Alignment.V_CENTER,
            end_arrow_type=ui.ArrowType.ARROW,
            style={"Line": {"color": color, "border_width": 3}})


# Vertical arrow ↓ (alignment=H_CENTER draws a vertical line)
def v_arr(h=32, color=ARROW_GRN):
    ui.Line(width=20, height=h,
            alignment=ui.Alignment.H_CENTER,
            end_arrow_type=ui.ArrowType.ARROW,
            style={"Line": {"color": color, "border_width": 3}})


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
win = ui.Window(
    "Slide 04 - The Goal", width=WIDTH, height=HEIGHT,
    flags=(ui.WINDOW_FLAGS_NO_TITLE_BAR | ui.WINDOW_FLAGS_NO_RESIZE
           | ui.WINDOW_FLAGS_NO_MOVE | ui.WINDOW_FLAGS_NO_SCROLLBAR),
    position_x=0, position_y=0,
)
win.frame.set_style({"Window": {
    "background_color": BG, "border_color": 0, "border_radius": 0, "padding": 0,
}})

with win.frame:
    with ui.VStack(style=M0):

        # ── Header ───────────────────────────────────────────────────────────
        with ui.ZStack(height=116, style=M0):
            ui.Rectangle(style={"Rectangle": {"background_color": HEADER_BG}})
            ui.Rectangle(width=6, style={"Rectangle": {"background_color": NVIDIA_GREEN}})

            with ui.VStack(style=M0):
                ui.Spacer(height=10)
                with ui.HStack(height=70, style=M0):
                    ui.Spacer(width=20)
                    with ui.ZStack(width=96, height=70):
                        lbl("Slide 04", color=NVIDIA_GREEN, size=16,
                            align=ui.Alignment.LEFT, h=70)
                    lbl("|", color=rgb(55, 65, 81), size=28,
                        align=ui.Alignment.CENTER, h=70)
                    ui.Spacer(width=10)
                    lbl("The Goal", color=HEADER_TEXT, size=60,
                        align=ui.Alignment.LEFT, h=70)
                    ui.Spacer()
                ui.Spacer(height=6)
                with ui.HStack(height=18, style=M0):
                    ui.Spacer(width=20)
                    lbl("Extract omni.ui into a standalone pip wheel"
                        " -- open-source, self-contained, no Carbonite",
                        color=rgb(148, 163, 184), size=14, h=18)
                ui.Spacer(height=12)

        # ── Main content ─────────────────────────────────────────────────────
        with ui.HStack(style=M0):

            # ── Left: bullet text (half the page) ────────────────────────────
            with ui.VStack(width=600, style=M0):
                ui.Spacer(height=24)
                with ui.HStack(height=38, style=M0):
                    ui.Spacer(width=28)
                    lbl("Extract omni.ui into a", color=TEXT_DARK, size=30, h=38)
                with ui.HStack(height=38, style=M0):
                    ui.Spacer(width=28)
                    lbl("standalone pip wheel:", color=TEXT_DARK, size=30, h=38)
                ui.Spacer(height=20)

                BULLETS = [
                    "Open-source, self-contained, no Carbonite",
                    "Still works identically inside Kit",
                    "Same extension name, version, and API",
                    "100+ dependent extensions require zero changes",
                    "Core source files byte-identical between repos",
                ]
                for text in BULLETS:
                    with ui.HStack(height=34, style=M0):
                        ui.Spacer(width=28)
                        with ui.VStack(width=11, style=M0):
                            ui.Spacer()
                            ui.Circle(width=11, height=11,
                                      style={"Circle": {"background_color": NVIDIA_GREEN}})
                            ui.Spacer()
                        ui.Spacer(width=10)
                        lbl(text, color=TEXT_DARK, size=27, h=34)
                    ui.Spacer(height=6)

                ui.Spacer()

            # Separator
            with ui.VStack(width=1, style=M0):
                ui.Spacer(height=10)
                ui.Rectangle(style={"Rectangle": {"background_color": SEP}})
                ui.Spacer(height=10)

            # ── Right: diagram ────────────────────────────────────────────────
            with ui.VStack(style=M0):
                ui.Spacer(height=24)

                # BEFORE / AFTER label row
                # BEFORE box: w=168, column starts at x=20 → box center at x=104
                # AFTER box:  w=180, column starts at x=20+272+1+10=303 → box center at x=393
                # Badge centers must match box centers.
                with ui.HStack(height=28, style=M0):
                    ui.Spacer(width=60)   # 104 - 44 (half of badge w=88)

                    with ui.ZStack(width=88, height=28):
                        ui.Rectangle(style={"Rectangle": {
                            "background_color": NVIDIA_GREEN, "border_radius": 5}})
                        lbl("BEFORE", color=rgb(255,255,255), size=13,
                            align=ui.Alignment.CENTER, h=28)

                    ui.Spacer(width=206)  # 393 - 39 - (60+88) = 206

                    with ui.ZStack(width=78, height=28):
                        ui.Rectangle(style={"Rectangle": {
                            "background_color": NVIDIA_GREEN, "border_radius": 5}})
                        lbl("AFTER", color=rgb(255,255,255), size=13,
                            align=ui.Alignment.CENTER, h=28)

                    ui.Spacer()

                ui.Spacer(height=14)

                # Diagram row
                with ui.HStack(style=M0):
                    ui.Spacer(width=20)

                    # BEFORE column — needs 168(box)+28(arr)+4(spc)+56(badge)=256 min
                    with ui.VStack(width=272, style=M0):
                        with ui.HStack(height=104, style=M0):
                            box(["Kit mono", "repo", "omni.ui", "+ carb"],
                                w=168, h=104)
                            with ui.VStack(style=M0):
                                ui.Spacer()
                                with ui.HStack(height=24, style=M0):
                                    h_arr(w=28, color=ARROW_GRN)
                                    ui.Spacer(width=4)
                                    badge("carb", bg=NVIDIA_GREEN, w=56, h=24, fs=13)
                                ui.Spacer()
                        ui.Spacer()

                    # Thin divider
                    with ui.VStack(width=1, style=M0):
                        ui.Spacer(height=2)
                        ui.Rectangle(style={"Rectangle": {"background_color": SEP}})
                        ui.Spacer(height=2)

                    ui.Spacer(width=10)

                    # AFTER column
                    with ui.VStack(style=M0):

                        # Kit repo --> adapter (carb)
                        with ui.HStack(height=96, style=M0):
                            box(["Kit repo", "omni.ui", "core"],
                                w=180, h=96)
                            with ui.VStack(style=M0):
                                ui.Spacer()
                                with ui.HStack(height=26, style=M0):
                                    h_arr(w=44, color=ARROW_GRN)
                                    ui.Spacer(width=8)
                                    lbl("adapter (carb)", color=NVIDIA_GREEN, size=14, h=26)
                                ui.Spacer()

                        # Down arrow — centered under the 180px box (center=90, arrow w=20 → offset=80)
                        with ui.HStack(height=36, style=M0):
                            ui.Spacer(width=80)
                            with ui.VStack(width=20, style=M0):
                                ui.Spacer()
                                v_arr(h=34, color=ARROW_GRN)
                                ui.Spacer()
                            ui.Spacer()

                        # byte-identical label — centered under the 180px box
                        with ui.HStack(height=24, style=M0):
                            lbl("byte-identical", color=NVIDIA_GREEN,
                                size=15, h=24, align=ui.Alignment.CENTER,
                                width=180)
                            ui.Spacer()

                        # Down arrow — centered under the 180px box (center=90, arrow w=20 → offset=80)
                        with ui.HStack(height=36, style=M0):
                            ui.Spacer(width=80)
                            with ui.VStack(width=20, style=M0):
                                ui.Spacer()
                                v_arr(h=34, color=ARROW_GRN)
                                ui.Spacer()
                            ui.Spacer()

                        # standalone --> backend (GLFW)
                        with ui.HStack(height=96, style=M0):
                            box(["standalone", "omni.ui", "core"],
                                w=180, h=96)
                            with ui.VStack(style=M0):
                                ui.Spacer()
                                with ui.HStack(height=26, style=M0):
                                    h_arr(w=44, color=ARROW_GRN)
                                    ui.Spacer(width=8)
                                    lbl("backend (GLFW)", color=NVIDIA_GREEN, size=14, h=26)
                                ui.Spacer()

                        # Down arrow — centered under the 180px box (center=90, arrow w=20 → offset=80)
                        with ui.HStack(height=36, style=M0):
                            ui.Spacer(width=80)
                            with ui.VStack(width=20, style=M0):
                                ui.Spacer()
                                v_arr(h=34, color=ARROW_GRN)
                                ui.Spacer()
                            ui.Spacer()

                        # pip wheel label — centered under the 180px box
                        with ui.HStack(height=28, style=M0):
                            lbl("pip wheel", color=NVIDIA_GREEN,
                                size=16, h=28, align=ui.Alignment.CENTER,
                                width=180)
                            ui.Spacer()

                        ui.Spacer()

                    ui.Spacer(width=12)

                ui.Spacer()

        # ── Footer ────────────────────────────────────────────────────────────
        with ui.ZStack(height=28, style=M0):
            ui.Rectangle(style={"Rectangle": {"background_color": FOOTER_BG}})
            with ui.HStack(style=M0):
                ui.Spacer(width=8)
                lbl("NVIDIA Omniverse  |  ovui",
                    color=rgb(148, 163, 184), size=12, h=28)
                ui.Spacer()
                ui.Rectangle(width=6,
                             style={"Rectangle": {"background_color": NVIDIA_GREEN}})


# ---------------------------------------------------------------------------
async def _capture():
    from omni.ui import testing
    await testing.wait_frames(6)
    testing.capture_screenshot("slide04.png")
    print("Screenshot saved: slide04.png")

if __name__ == "__main__":
    if _SCREENSHOT:
        ui.run(_capture())
    else:
        ui.run()
