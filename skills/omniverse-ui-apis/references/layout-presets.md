# Layout Presets For Standard Ovui Components

Use these presets when you build UI from standard ovui components: windows, sections, form rows, fields, sliders, drags, combo boxes, check boxes, buttons and toolbars. Each preset gives the spacing, the alignment and the options that you must set.

Why: the default options of the standard components are for compact docked panels. A stack has no spacing, a window has a 4 px gutter, and most widgets fill all the space that they get. UI that keeps these defaults is dense and has little visual separation. Agents often forget the spacing, the alignment and the options. Copy the presets. Do not invent other numbers.

Use the presets together with the global style of ovui-widgets (`apply_global_styles()`, see the `omniverse-ui-styling` skill). The global style gives the colors, the borders and the fonts. The presets give the layout.

## What the defaults give you

| Component | Default | What to set |
|---|---|---|
| `ui.Window` | `padding_x=4`, `padding_y=4`: the content is 4 px from the border | `padding_x=LAYOUT_WINDOW_PADDING`, `padding_y=LAYOUT_WINDOW_PADDING` |
| `ui.VStack`, `ui.HStack` | `spacing=0`, `width` and `height` are `ui.Fraction(1)` | Always set `spacing`. Set `height=0` (fit the content) on a stack that must not stretch. |
| `ui.Label` | fills its space, `alignment=ui.Alignment.LEFT_CENTER`, no wrap, no elision | In a form: a fixed width, `elided_text=True` and a tooltip with the full text. For a paragraph: `word_wrap=True`, `height=0`. |
| `ui.CollapsableFrame` | `height` is `ui.Fraction(1)`; the global style gives a visible title and arrow, `margin_height` 8 and `padding` 0 | `height=0`. Put a spacer of `LAYOUT_HEADER_GAP` at the top of the body. |
| `ui.StringField`, `ui.IntField`, `ui.FloatField` | fill their space; style type `"Field"` | Put them in a form row, or set `height=LAYOUT_ROW_HEIGHT`. |
| `ui.FloatSlider`, `ui.IntSlider` | range 0..1 (float) and 0..100 (int); style type `"Slider"` | Always set `min` and `max`. |
| `ui.FloatDrag` | no range, `step` 0.01; style type `"Slider"` | Set `step`. Set `min` and `max` when the value has a range. |
| `ui.IntDrag` | no range, `step` 0.1; style type `"Slider"` | Set `step`. Set `min` and `max` when the value has a range. |
| `ui.ComboBox` | `ui.ComboBox(selected_index, *items)`; fills its space | Put it in a form row. |
| `ui.CheckBox` | width and height are `ui.Fraction(1)`, so the click area fills the row | `width` and `height` of `LAYOUT_CHECK_BOX_SIZE`, centered in the row, then `ui.Spacer()`. |
| `ui.Button` | fills its space; the global style gives padding 4 and margin 2 | A fixed `width` and `height`. |

Notes:

- ovui gives every field the style type `"Field"`, and every slider and drag the style type `"Slider"`. The keys `"StringField"`, `"FloatDrag"` and similar do not style a default widget. See the `omniverse-ui-styling` skill.
- The stacks have no cross-axis alignment. To center a small widget in a row, put it in a `ui.VStack` with a `ui.Spacer()` above and below it.

## Spacing constants

Copy these constants into your module. They are layout constants of your surface, so they have the domain prefix `LAYOUT_`. A stack `spacing`, a `width` and a `height` take a number in pixels, so they cannot use the `fl.*` names of the style module.

```python
import omni.ui as ui

LAYOUT_WINDOW_PADDING = 12   # between the window border and the content
LAYOUT_SPACING = 8           # between the blocks of a window, and between the rows of a form
LAYOUT_TIGHT_SPACING = 4     # between the parts of one control (x, y, z) and the buttons of a toolbar
LAYOUT_HEADER_GAP = 4        # between a section header and its first row
LAYOUT_ROW_HEIGHT = 24       # one form row: a label and one control
LAYOUT_LABEL_WIDTH = 120     # the label column of a form (wide panels: 160, as the Property Inspector)
LAYOUT_LABEL_GAP = 8         # between the label column and the control
LAYOUT_CHECK_BOX_SIZE = 18
LAYOUT_BUTTON_HEIGHT = 28
LAYOUT_BUTTON_WIDTH = 96
LAYOUT_BUTTON_SPACING = 8
LAYOUT_TOOLBAR_HEIGHT = 28
LAYOUT_ICON_BUTTON_SIZE = 24
```

Rules:

- Every size and every gap in a layout comes from one of these constants.
- Two sections are 24 px apart: `LAYOUT_SPACING` of the stack, and the margin of 8 px above and below each section that the global style gives.
- In a long list of rows (more than about 15), you can use `LAYOUT_TIGHT_SPACING` between the rows. The Property Inspector uses 5 px.

## Preset: tool window

A floating or docked tool window with a padded body. The body is a scrolling frame, so long content does not push the footer out of the window.

```python
class ExportToolWindow:
    def __init__(self):
        self.window = ui.Window(
            "Export Tool",
            width=440,
            height=560,
            padding_x=LAYOUT_WINDOW_PADDING,
            padding_y=LAYOUT_WINDOW_PADDING,
        )
        self.window.frame.set_build_fn(self._build)

    def _build(self):
        with ui.VStack(spacing=LAYOUT_SPACING):
            ui.Label("Export the selected prims to a file.", word_wrap=True, height=0)
            with ui.ScrollingFrame(
                horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
            ):
                with ui.VStack(spacing=LAYOUT_SPACING, height=0):
                    self._build_sections()
            button_row([("Cancel", self._cancel, False), ("Export", self._export, True)])

    def _build_sections(self):
        section("Output", self._build_output_rows)
        section("Quality", self._build_quality_rows)
        section("Advanced", self._build_advanced_rows, collapsed=True)

    # _build_output_rows() and the other row builders call form_row() (see below).
    # _cancel() and _export() are the actions of the buttons.
```

- Keep a reference to the window object for as long as the window must stay open.
- Docked panels of the app (Stage Browser, Property Inspector) keep the 4 px window padding and draw their own gutters. Do not change them.

## Preset: section

A titled section that the user can collapse. Use it to group related rows.

```python
def section(title, build_rows, collapsed=False):
    frame = ui.CollapsableFrame(title, collapsed=collapsed, height=0)
    with frame:
        with ui.VStack(spacing=0, height=0):
            ui.Spacer(height=LAYOUT_HEADER_GAP)
            with ui.VStack(spacing=LAYOUT_SPACING, height=0):
                build_rows()
    return frame
```

- Keep the default header (the title and the arrow). The global style shows it in the panel color, with no box, as in the Property Inspector.
- Use `collapsed=True` only for advanced options. The user must still see the header.
- Do not set `padding` on the `"CollapsableFrame"` style key. The inner header and body frames of every collapsable frame read it, also the frames that have their own `style_type_name_override`.

## Preset: form row

One label and one control in a row. The label column has a fixed width, so the controls of all rows start at the same x.

```python
def form_row(label, build_control, tooltip=""):
    with ui.HStack(height=LAYOUT_ROW_HEIGHT, spacing=LAYOUT_LABEL_GAP):
        ui.Label(
            label,
            width=LAYOUT_LABEL_WIDTH,
            alignment=ui.Alignment.LEFT_CENTER,
            elided_text=True,
            tooltip=tooltip or label,
        )
        build_control()
```

The control fills the rest of the row. Use these controls with these options:

```python
# Text
form_row("File name", lambda: ui.StringField(model=name_model))

# Integer or float that the user types
form_row("Threads", lambda: ui.IntField(model=threads_model))
form_row("Gamma", lambda: ui.FloatField(model=gamma_model))

# Number that the user drags: always give the step, and the range when there is one
form_row("Scale", lambda: ui.FloatDrag(model=scale_model, min=0.0, max=10.0, step=0.01))

# Number in a fixed range: always give min and max
form_row("Samples", lambda: ui.IntSlider(model=samples_model, min=1, max=64))

# One of a list
form_row("Format", lambda: ui.ComboBox(0, "USD", "USDA", "USDC"))

# Yes or no: a check box of fixed size, centered in the row, then a spacer
def check_box(model):
    with ui.HStack(spacing=0):
        with ui.VStack(width=LAYOUT_CHECK_BOX_SIZE, spacing=0):
            ui.Spacer()
            ui.CheckBox(model=model, width=LAYOUT_CHECK_BOX_SIZE, height=LAYOUT_CHECK_BOX_SIZE)
            ui.Spacer()
        ui.Spacer()

form_row("Overwrite", lambda: check_box(overwrite_model))

# Vector: one drag for each component, with the same width
def vector3(models):
    with ui.HStack(spacing=LAYOUT_TIGHT_SPACING):
        for model in models:
            ui.FloatDrag(model=model, step=0.01, width=ui.Fraction(1))

form_row("Translate", lambda: vector3(translate_models))
```

## Preset: button row

The footer of a dialog or a tool window. The buttons are right aligned. The main action is the last button, at the right.

```python
def button_row(buttons):
    """buttons: a list of (text, clicked_fn, is_main_action)."""
    with ui.HStack(height=LAYOUT_BUTTON_HEIGHT, spacing=LAYOUT_BUTTON_SPACING):
        ui.Spacer()
        for text, clicked_fn, is_main_action in buttons:
            ui.Button(
                text,
                width=LAYOUT_BUTTON_WIDTH,
                clicked_fn=clicked_fn,
                style_type_name_override="OKButton" if is_main_action else "CancelButton",
            )
```

- `"OKButton"` and `"CancelButton"` are the button types of the global style. The app dialogs use them.
- Put "Cancel" before the main action.

## Preset: toolbar

A row of square icon buttons at the top of a panel.

```python
def toolbar(actions):
    """actions: a list of (icon_style_name, tooltip, clicked_fn)."""
    with ui.HStack(height=LAYOUT_TOOLBAR_HEIGHT, spacing=LAYOUT_TIGHT_SPACING):
        for name, tooltip, clicked_fn in actions:
            with ui.VStack(width=LAYOUT_ICON_BUTTON_SIZE, spacing=0):
                ui.Spacer()
                ui.Button(
                    width=LAYOUT_ICON_BUTTON_SIZE,
                    height=LAYOUT_ICON_BUTTON_SIZE,
                    name=name,
                    tooltip=tooltip,
                    clicked_fn=clicked_fn,
                )
                ui.Spacer()
        ui.Spacer()
```

- Give each icon button a tooltip.
- Put the icon in the style of the button `name` (see the `omniverse-ui-styling` skill), not in a path literal.

## Preset: filter bar, list and tree

- Filter bar above a list: see "Recipe: Docked Tool Window With Nested Layout" in `references/recipes.md` (30 px high, an 8 px gutter at each side).
- Rows of a list or a tree: 18 to 22 px high, with a fixed icon slot. See `references/layout.md` and "Recipe: Stage Hierarchy Tree From Atomic TreeView" in `references/recipes.md`.

## Check before you finish

Take a screenshot of the window (see the `omniverse-ui-inspector` skill) and check:

1. The content is at least 12 px from the window border.
2. Each section has a visible title and arrow. A collapsed section is still visible.
3. The labels of a form start at the same x, and the controls start at the same x.
4. No label runs into its control. A long label is cut with "..." and has a tooltip.
5. No two controls touch. There is a gap of at least 4 px between controls, and 8 px between rows.
6. Each slider and drag has a frame, as the fields have.
7. Each slider has a range, and each drag has a step.
8. The buttons of the footer are right aligned, and the main action is the last one.
