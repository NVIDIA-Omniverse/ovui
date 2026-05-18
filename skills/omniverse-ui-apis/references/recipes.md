# Atomic Ovui Recipes

These recipes are implementation sketches, not drop-in applications. Adapt names, adapters, styles, and lifecycle to the target repo. They deliberately avoid high-level composite widgets.

## Recipe: Docked Tool Window With Nested Layout

Goal: create a production-style docked panel from atomic widgets.

Key points:

- Create `ui.DockSpace(None)` before dockable windows.
- Use `dockPreference=ui.DockPreference.MAIN` for windows that should honor saved dock state.
- Wait one frame before `dock_in()`.
- Reserve fixed-height top/bottom chrome and put the flexible body in the middle.
- Use a `ZStack` background rectangle inside the frame so you do not paint over the dock tab strip.

```python
import omni.ui as ui
from omni.ui import color as cl

class AtomicPanel:
    def __init__(self, title="Atomic Tool"):
        self.window = ui.Window(
            title,
            dockPreference=ui.DockPreference.MAIN,
            width=360,
            height=540,
            raster_policy=ui.RasterPolicy.NEVER,
        )
        self.window.frame.set_build_fn(self._build)

    def _build(self):
        with ui.VStack(spacing=0):
            # Leave a small transparent gap so the dock tab title remains legible.
            ui.Spacer(height=ui.Pixel(8))
            with ui.ZStack():
                ui.Rectangle(style={"background_color": cl.background_primary, "border_width": 0})
                with ui.VStack(spacing=0):
                    self._build_filter_bar()
                    ui.Rectangle(height=ui.Pixel(1), style_type_name_override="Panel.Separator")
                    self._build_body()
                    ui.Rectangle(height=ui.Pixel(1), style_type_name_override="Panel.Separator")
                    self._build_footer()

    def _build_filter_bar(self):
        with ui.ZStack(height=ui.Pixel(30)):
            ui.Rectangle(style_type_name_override="Panel.FilterBar")
            with ui.HStack(spacing=0):
                ui.Spacer(width=ui.Pixel(8))
                field = ui.StringField(height=ui.Pixel(20), style_type_name_override="Panel.FilterField")
                field.model.add_value_changed_fn(lambda model: self._on_filter(model.as_string))
                ui.Spacer(width=ui.Pixel(8))

    def _build_body(self):
        with ui.ScrollingFrame(
            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
        ):
            with ui.VStack(spacing=2):
                for i in range(20):
                    with ui.HStack(height=ui.Pixel(22), spacing=4):
                        ui.Label(f"Row {i}", alignment=ui.Alignment.LEFT_CENTER)
                        ui.Spacer()
                        ui.Button("...", width=ui.Pixel(28))

    def _build_footer(self):
        with ui.HStack(height=ui.Pixel(22)):
            ui.Spacer(width=ui.Pixel(8))
            self.count_label = ui.Label("20 items", alignment=ui.Alignment.LEFT_CENTER)
            ui.Spacer()
            ui.Button("Refresh", width=ui.Pixel(72), clicked_fn=self._refresh)
            ui.Spacer(width=ui.Pixel(8))

    def _on_filter(self, text):
        pass

    def _refresh(self):
        self.window.frame.rebuild()

    def destroy(self):
        self.window.destroy()
        self.window = None

async def build_workspace():
    dockspace = ui.DockSpace(None)
    viewport = ui.Window("Viewport", dockPreference=ui.DockPreference.MAIN, width=800, height=600)
    tool = AtomicPanel("Atomic Tool")

    await ui.next_frame()
    vp_handle = ui.Workspace.get_window("Viewport")
    if vp_handle is not None:
        tool.window.dock_in(vp_handle, ui.DockPosition.LEFT, ratio=0.30)
    return {"dockspace": dockspace, "viewport": viewport, "tool": tool}
```

Standalone entrypoint pattern:

```python
import omni.ui as ui

_LIFETIME_REFS = {}

async def main_coroutine():
    _LIFETIME_REFS["workspace"] = await build_workspace()
    while True:
        await ui.next_frame()

if __name__ == "__main__":
    ui.run(main_coroutine())  # blocking standalone launch
```

Use `ui.run_async(main_coroutine())` only when embedding in an already-running compatible event loop. Keep window, model, delegate, provider, renderer, and subscription references alive for the process lifetime.

## Recipe: Stage Hierarchy Tree From Atomic TreeView

Goal: render a stage hierarchy without importing `StageWidget` or `StageWindow`.

Model sketch:

```python
import omni.ui as ui

class PrimItem(ui.AbstractItem):
    def __init__(self, path, prim_handle, parent=None):
        super().__init__()
        self.path = path
        self.prim_handle = prim_handle
        self.parent = parent
        self.children = None
        self.name_model = None
        self.type_model = None
        self.visibility_model = None
        self.flags_dirty = True

class VisibilityModel(ui.AbstractValueModel):
    def __init__(self, adapter, item):
        super().__init__()
        self.adapter = adapter
        self.item = item

    def get_value_as_bool(self):
        # Example convention: True means hidden.
        return not self.adapter.is_visible(self.item.prim_handle)

    def get_value_as_float(self):
        return float(self.get_value_as_bool())

    def get_value_as_int(self):
        return int(self.get_value_as_bool())

    def get_value_as_string(self):
        return "hidden" if self.get_value_as_bool() else "visible"

    def set_value(self, value):
        self.adapter.set_visible(self.item.prim_handle, not bool(value))
        self._value_changed()

class StageTreeModel(ui.AbstractItemModel):
    NUM_COLUMNS = 3

    def __init__(self, adapter):
        super().__init__()
        self.adapter = adapter
        root_handle = adapter.get_root()
        root_path = adapter.get_item_path(root_handle)
        self.root = PrimItem(root_path, root_handle, None)
        self.path_cache = {root_path: self.root}
        self.expanded_paths = set()
        self.selected_items = []

    def get_item_children(self, item=None):
        if item is None:
            return [self.root]
        if item.children is None:
            item.children = []
            for child_handle in self.adapter.get_children(item.prim_handle):
                path = self.adapter.get_item_path(child_handle)
                child = self.path_cache.get(path)
                if child is None:
                    child = PrimItem(path, child_handle, parent=item)
                    self.path_cache[path] = child
                else:
                    child.prim_handle = child_handle
                    child.parent = item
                item.children.append(child)
        return item.children

    def can_item_have_children(self, item=None):
        if item is None:
            return True
        return bool(self.adapter.get_children(item.prim_handle))

    def get_item_value_model_count(self, item=None):
        return self.NUM_COLUMNS

    def get_item_value_model(self, item=None, column_id=0):
        if item is None:
            return None
        if column_id == 0:
            if item.name_model is None:
                item.name_model = ui.SimpleStringModel(self.adapter.get_display_name(item.prim_handle))
            return item.name_model
        if column_id == 1:
            if item.type_model is None:
                item.type_model = ui.SimpleStringModel(self.adapter.get_type_name(item.prim_handle))
            return item.type_model
        if column_id == 2:
            if item.visibility_model is None:
                item.visibility_model = VisibilityModel(self.adapter, item)
            return item.visibility_model
        return None

    def resolve_path(self, path):
        cached = self.path_cache.get(path)
        if cached is not None:
            return cached
        # Walk from root and call get_item_children at every ancestor.
        current = self.root
        current_path = self.root.path.rstrip("/")
        for segment in [s for s in path.split("/") if s][1:]:
            next_path = f"{current_path}/{segment}"
            found = None
            for child in self.get_item_children(current):
                if child.path == next_path:
                    found = child
                    break
            if found is None:
                return None
            current = found
            current_path = next_path
        return current

    def invalidate_subtree(self, item=None):
        if item is None:
            self.root.children = None
            self._item_changed(None)
        else:
            item.children = None
            item.type_model = None
            self._item_changed(item)
```

Delegate sketch:

```python
class StageTreeDelegate(ui.AbstractItemDelegate):
    ROW_H = 16
    INDENT = 14
    ICON = 10

    def __init__(self, icon_provider_fn):
        super().__init__()
        self.icon_provider_fn = icon_provider_fn
        self.rename_items = set()

    def build_branch(self, model, item, column_id, level, expanded):
        if column_id != 0:
            return
        width = self.INDENT * level + self.INDENT
        with ui.HStack(width=ui.Pixel(width), height=ui.Pixel(self.ROW_H), spacing=0):
            if level:
                ui.Spacer(width=ui.Pixel(self.INDENT * level))
            if model.can_item_have_children(item):
                text = "v" if expanded else ">"
                ui.Label(text, width=ui.Pixel(self.INDENT), alignment=ui.Alignment.CENTER)
            else:
                ui.Spacer(width=ui.Pixel(self.INDENT))

    def build_widget(self, model, item, column_id, level, expanded):
        if item is None:
            return
        if column_id == 0:
            self._build_name(model, item)
        elif column_id == 1:
            vm = model.get_item_value_model(item, 1)
            ui.Label(vm.as_string.lower() if vm else "", alignment=ui.Alignment.LEFT_CENTER)
        elif column_id == 2:
            self._build_visibility(model, item)

    def _build_name(self, model, item):
        vm = model.get_item_value_model(item, 0)
        with ui.HStack(height=ui.Pixel(self.ROW_H), spacing=4):
            ui.Spacer(width=ui.Pixel(2))
            ui.ImageWithProvider(
                self.icon_provider_fn(item),
                width=ui.Pixel(self.ICON),
                height=ui.Pixel(self.ICON),
                opaque_for_mouse_events=False,
            )
            if item in self.rename_items:
                field = ui.StringField(height=ui.Pixel(self.ROW_H))
                field.model.set_value(vm.as_string if vm else "")
                field.model.add_end_edit_fn(lambda m, i=item: self._commit_rename(model, i, m.as_string))
            else:
                ui.Label(vm.as_string if vm else "", alignment=ui.Alignment.LEFT_CENTER, width=0)
            ui.Spacer()

    def _build_visibility(self, model, item):
        vm = model.get_item_value_model(item, 2)
        with ui.HStack(height=ui.Pixel(self.ROW_H)):
            ui.Spacer()
            with ui.ZStack(width=ui.Pixel(18), height=ui.Pixel(16)):
                ui.Label("H" if vm and vm.as_bool else "V", alignment=ui.Alignment.CENTER)
                hit = ui.InvisibleButton(width=ui.Pixel(18), height=ui.Pixel(16))
                hit.set_clicked_fn(lambda v=vm: v.set_value(not v.as_bool))
            ui.Spacer(width=ui.Pixel(4))

    def _commit_rename(self, model, item, new_name):
        model.adapter.rename(item.prim_handle, new_name)
        self.rename_items.discard(item)
        item.name_model = None
        model._item_changed(item)
```

Assembly:

```python
model = StageTreeModel(adapter)
delegate = StageTreeDelegate(icon_provider_fn)
column_widths = [ui.Fraction(3), ui.Fraction(1), ui.Pixel(28)]

with ui.VStack(spacing=0):
    build_filter_bar()
    build_manual_header(column_widths)
    with ui.ScrollingFrame(
        horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
        vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
    ):
        tree = ui.TreeView(
            model,
            delegate=delegate,
            root_visible=True,
            header_visible=False,
            column_widths=column_widths,
            drop_between_items=True,
        )
    build_footer()

def on_tree_selection(items):
    model.selected_items = list(items)
    paths = [item.path for item in items]
    selection_bus.publish(paths, source="atomic-stage-tree")

tree.set_selection_changed_fn(on_tree_selection)
```

Add expansion persistence if external model rebuilds are possible. Snapshot `tree.is_expanded(item)` into `model.expanded_paths` before `_item_changed(None)`, then resolve and `tree.set_expanded(item, True, False)` after the next frame.

## Recipe: Viewport-Like Panel Shell With ovrtx

Goal: build enough of a viewport shell to validate layout, image embedding, toolbar, HUD, and renderer loop without importing `ViewportWidget`.

Atomic shell:

```python
import numpy as np
import omni.ui as ui
from omni.ui_scene import scene as sc

class ByteImageBridge:
    def __init__(self, width=1280, height=720):
        self.width = width
        self.height = height
        self.provider = ui.ByteImageProvider()
        blank = np.zeros((height, width, 4), dtype=np.uint8)
        blank[:, :, 3] = 255
        self.provider.set_data_array(blank, [width, height])

    def update(self, frame):
        h, w = frame.shape[:2]
        self.width = w
        self.height = h
        self.provider.set_data_array(frame, [w, h])

class AtomicViewportPanel:
    MIN_W = 64
    MIN_H = 64
    MAX_W = 3840
    MAX_H = 2160

    def __init__(self, renderer):
        self.renderer = renderer
        self.bridge = ByteImageBridge()
        self.window = ui.Window(
            "Viewport",
            dockPreference=ui.DockPreference.MAIN,
            width=800,
            height=600,
            raster_policy=ui.RasterPolicy.NEVER,
        )
        self.image = None
        self.scene_view = None
        self.fps_label = None
        self.window.frame.set_build_fn(self._build)

    def _build(self):
        with ui.VStack(spacing=0):
            self._build_toolbar()
            with ui.ZStack():
                self.image = ui.ImageWithProvider(
                    self.bridge.provider,
                    fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
                    style_type_name_override="Viewport.Image",
                )
                self.scene_view = sc.SceneView()
                with self.scene_view.scene:
                    sc.Screen(gestures=[])
                self._build_hud()

    def _build_toolbar(self):
        with ui.ZStack(height=ui.Pixel(32)):
            ui.Rectangle(style_type_name_override="Viewport.Toolbar")
            with ui.HStack(height=ui.Pixel(32), spacing=4):
                ui.Spacer(width=ui.Pixel(12))
                for label in ("Move", "Rotate", "Scale"):
                    ui.Button(label, width=ui.Pixel(70), height=ui.Pixel(24))
                ui.Spacer()

    def _build_hud(self):
        with ui.VStack(spacing=0):
            ui.Spacer(height=ui.Pixel(12))
            with ui.HStack(height=ui.Pixel(18)):
                ui.Spacer(width=ui.Pixel(12))
                self.fps_label = ui.Label("FPS", width=ui.Pixel(100), style_type_name_override="Viewport.HUD")
                ui.Spacer()
            ui.Spacer()

    def render_once(self, view_matrix, proj_matrix, dt):
        if self.image is None or not self.image.visible:
            return False
        w = int(self.image.computed_width or 0)
        h = int(self.image.computed_height or 0)
        if w <= 0 or h <= 0:
            return False
        w = max(self.MIN_W, min(self.MAX_W, w))
        h = max(self.MIN_H, min(self.MAX_H, h))
        frame = self.renderer.render_frame(w, h, view_matrix, proj_matrix)
        self.bridge.update(frame)
        if self.fps_label is not None and dt > 0:
            self.fps_label.text = f"{1.0 / dt:.0f} FPS"
        return True

    def destroy(self):
        try:
            self.renderer.shutdown()
        finally:
            self.window.destroy()
            self.window = None
```

ovrtx direct renderer path (sketch):

```python
import os
os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")  # required before import
# In local shells with user-site usd-core installed, launch with:
# PYTHONNOUSERSITE=1 PYTHONPATH="${OVRTX_ROOT}/python:${OVUI_REPO}/ovui/python:..."

import numpy as np
import ovrtx
from ovrtx import Device

_SESSION_ROOT = "/MyPrototypeSession"
_RENDER_PRODUCT_PATH = f"{_SESSION_ROOT}/Render/Viewport"

SESSION_USDA = """#usda 1.0
(
    defaultPrim = "MyPrototypeSession"
    upAxis = "Y"
)

def Scope "MyPrototypeSession"
{
    def Scope "Cameras"
    {
        def Camera "Main"
        {
            float focalLength = 18
            float horizontalAperture = 20.955
            float verticalAperture = 15.2908
            float2 clippingRange = (0.01, 10000)
            token projection = "perspective"
            matrix4d xformOp:transform = ( (1,0,0,0), (0,1,0,0), (0,0,1,0), (0,0,0,1) )
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }
    }
    def Scope "Render"
    {
        def RenderProduct "Viewport"
        {
            rel camera = </MyPrototypeSession/Cameras/Main>
            rel orderedVars = </MyPrototypeSession/Render/Vars/LdrColor>
            uniform int2 resolution = (1280, 720)
        }
        def Scope "Vars"
        {
            def RenderVar "LdrColor"
            {
                uniform string sourceName = "LdrColor"
            }
        }
    }
}
"""

renderer = ovrtx.Renderer()
renderer.add_usd("/path/to/scene.usda")
renderer.add_usd_layer(SESSION_USDA, path_prefix=_SESSION_ROOT)

dt = max(1.0 / 300.0, min(0.1, 1.0 / 60.0))
products = renderer.step({_RENDER_PRODUCT_PATH}, delta_time=dt)
product = products[_RENDER_PRODUCT_PATH]
rv = product.frames[0].render_vars["LdrColor"]
with rv.map(device=Device.CPU) as mapping:
    frame = np.array(mapping.tensor.numpy(), copy=True)  # copy before context exits
```

`frame` is `(H, W, 4)` uint8 RGBA — feed it straight into `ImageBridge.update(frame)`.

If the agent needs more than this — pick rays, selection highlight, GPU zero-copy, or session-layer reinjection on resize — stop and ask Victor to authorize the high-level adapter or extend this skill.

## Recipe: Property-Inspector Row Patterns From Atomic Widgets

Goal: build a Property Inspector-like panel from atomic widgets without importing any `PropertyWidget` subclass. Sections are collapsible groups; each row is a label-on-the-left + control-on-the-right pair.

```python
import omni.ui as ui

FIT_CONTENT_HEIGHT = ui.Length.compute("0")  # or simply pass height=0 to fit content


class AtomicPropertySection:
    """One collapsible group with a stack of rows."""

    def __init__(self, title, rows):
        # rows: list of (label, control_builder_callable) tuples
        self._title = title
        self._rows = rows
        self._frame = None

    def build(self):
        self._frame = ui.CollapsableFrame(
            title=self._title,
            collapsed=False,
            height=0,  # FIT_CONTENT_HEIGHT
            style_type_name_override="Property.GroupFrame",
        )
        with self._frame:
            with ui.VStack(spacing=2):
                for label, build_control in self._rows:
                    self._build_row(label, build_control)

    def _build_row(self, label, build_control):
        with ui.HStack(height=ui.Pixel(20), spacing=6):
            ui.Spacer(width=ui.Pixel(8))
            ui.Label(label, width=ui.Pixel(120), alignment=ui.Alignment.LEFT_CENTER)
            with ui.HStack():
                build_control()
            ui.Spacer(width=ui.Pixel(8))


# Example controls — each one is a callable that builds a single control in place.

def string_row(model):
    def build():
        ui.StringField(model=model)
    return build


def float_row(model, min_value=None, max_value=None):
    def build():
        kwargs = {}
        if min_value is not None:
            kwargs["min"] = min_value
        if max_value is not None:
            kwargs["max"] = max_value
        ui.FloatDrag(model=model, **kwargs)
    return build


def vec3_row(x_model, y_model, z_model):
    def build():
        # Use MultiFloatDragField when the three values should share a single
        # AbstractItemModel. For independent value models, lay out three
        # FloatDrag widgets in an HStack with Fraction widths.
        with ui.HStack(spacing=4):
            ui.FloatDrag(model=x_model, width=ui.Fraction(1))
            ui.FloatDrag(model=y_model, width=ui.Fraction(1))
            ui.FloatDrag(model=z_model, width=ui.Fraction(1))
    return build


def bool_row(model):
    def build():
        with ui.HStack():
            ui.CheckBox(model=model, width=ui.Pixel(16))
            ui.Spacer()
    return build


def color_row(r_model, g_model, b_model, a_model=None):
    def build():
        # ui.ColorWidget reads from an AbstractItemModel with 3 or 4 child
        # value models. For a quick prototype, build a minimal item model
        # whose children are the value models you already have.
        ui.ColorWidget(width=ui.Pixel(60), height=ui.Pixel(20))
    return build


# Assembly inside a docked property window:

with ui.VStack(spacing=4):
    AtomicPropertySection("Transform", [
        ("Translate", vec3_row(tx, ty, tz)),
        ("Rotate",    vec3_row(rx, ry, rz)),
        ("Scale",     vec3_row(sx, sy, sz)),
    ]).build()
    AtomicPropertySection("Display", [
        ("Visible",   bool_row(vis_model)),
        ("Purpose",   string_row(purpose_model)),
    ]).build()
```

Selection-driven payload loading:

- Subscribe to the same selection bus the Stage TreeView publishes to.
- On selection change, build the per-property value models from the active adapter prim and call `frame.rebuild()` on the property panel's outer frame.
- Each value model that wraps an adapter attribute must call `_value_changed()` after writing back, and the property panel must subscribe to adapter notifications so external changes refresh the controls.

## Recipe: Manual Header Above TreeView

Use this when the built-in TreeView header creates unwanted top gaps or when you need exact header chrome.

```python
column_widths = [ui.Fraction(3), ui.Fraction(1), ui.Pixel(28)]

with ui.ZStack(height=ui.Pixel(22)):
    ui.Rectangle(style_type_name_override="Tree.HeaderBackground")
    with ui.HStack(spacing=0):
        with ui.HStack(width=column_widths[0]):
            ui.Spacer(width=ui.Pixel(8))
            ui.Label("NAME", alignment=ui.Alignment.LEFT_CENTER)
        with ui.HStack(width=column_widths[1]):
            ui.Label("TYPE", alignment=ui.Alignment.LEFT_CENTER)
        with ui.HStack(width=column_widths[2]):
            ui.Label("", alignment=ui.Alignment.CENTER)

with ui.ScrollingFrame(...):
    ui.TreeView(
        model,
        delegate=delegate,
        header_visible=False,
        column_widths=column_widths,
    )
```

Keep the same `column_widths` object/list for the manual header and TreeView so columns stay aligned.
