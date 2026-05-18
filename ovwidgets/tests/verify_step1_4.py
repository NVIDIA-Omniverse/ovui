# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 1.4 visual QA: confirm the property panel still renders after the
row classes are migrated onto :class:`AttributeModelBase`.

The dispatch path (WidgetBuilderTable.build) and the rendered row layout
stay identical; the difference is that every row now owns an
``AttributeModelBase`` and routes its widget callbacks through that model
instead of the adapter directly. This script asserts four runtime
invariants the tests cannot cover because they need a real ``omni.ui``
widget tree:

* each row instance exposes ``row._model`` typed as :class:`AttributeModelBase`
* each row holds a ``subscribe_value_changed`` handle (``row._value_sub``)
  and an adapter-change subscription (``row._adapter_sub``)
* a mutation to the mock adapter's backing store followed by
  ``adapter.fire_change()`` refreshes every row's widget from the model
  (the ``_on_backing_changed`` → ``_on_model_value_changed`` chain)
* none of the rows still reference ``self._adapter.begin_edit`` or
  ``self._adapter.set_value`` directly — the adapter-call rewrites from
  Step 1.4 are complete.

Run:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \
    python3.12 tests/verify_step1_4.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.property.attribute_row import (
    BoolAttributeRow,
    FloatAttributeRow,
    IntAttributeRow,
    StringAttributeRow,
    Vec3FloatAttributeRow,
)
from ovwidgets.property.builders import WidgetBuilderTable
from ovwidgets.property.models import AttributeModelBase
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.stage_widget import StageWidget
from ovwidgets.viewport.viewport_widget import ViewportWidget

SelectionBus._instance = None
_bus = SelectionBus.instance()


class _FakeApp:
    class _UndoMgr:
        def can_undo(self) -> bool: return False
        def can_redo(self) -> bool: return False
        def undo(self) -> None: pass
        def redo(self) -> None: pass

    class _FakeSettings:
        def set(self, key: str, value: object) -> None: pass

    def __init__(self) -> None:
        self.undo_manager = self._UndoMgr()
        self.settings = self._FakeSettings()
        self.selection_bus = _bus
        self._recent_files = type("_RF", (), {"get_ordered": lambda self: []})()  # type: ignore[assignment]


def _make_adapter(paths):
    attrs = {
        "xformOp:translate": AttributeMetadata(
            "xformOp:translate", "Translate", "double3", float, "Transform"
        ),
        "xformOp:rotateXYZ": AttributeMetadata(
            "xformOp:rotateXYZ", "Rotate", "float3", float, "Transform"
        ),
        "xformOp:scale": AttributeMetadata(
            "xformOp:scale", "Scale", "float3", float, "Transform"
        ),
        "visibility": AttributeMetadata(
            "visibility", "Visibility", "token", str, "Display"
        ),
        "purpose": AttributeMetadata(
            "purpose", "Purpose", "token", str, "Display"
        ),
        "doubleSided": AttributeMetadata(
            "doubleSided", "Double Sided", "bool", bool, "Geometry"
        ),
        "radius": AttributeMetadata(
            "radius", "Radius", "float", float, "Geometry",
            soft_range_min=0.0, soft_range_max=100.0,
        ),
    }
    a = MockPropertyAdapter(paths=paths, attributes=attrs)
    a.set_value("xformOp:translate", (1.0, 0.0, 0.5))
    a.set_value("xformOp:rotateXYZ", (0.0, 45.0, 0.0))
    a.set_value("xformOp:scale", (1.0, 1.0, 1.0))
    a.set_value("visibility", "inherited")
    a.set_value("purpose", "default")
    a.set_value("doubleSided", False)
    a.set_value("radius", 1.0)
    return a


write_split_ini()
ui.init("OvGear Step 1.4 QA", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_app = _FakeApp()

main_win = ui.Window(
    "OvGear",
    flags=(
        ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
        | ui.WINDOW_FLAGS_NO_MOVE
        | ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_MENU_BAR
        | ui.WINDOW_FLAGS_NO_BACKGROUND
    ),
    fill_app_window=True,
)

with main_win.frame:
    with ui.VStack(spacing=0):
        with ui.MenuBar():
            build_menu_bar(_app)
        ui.Spacer()
        _sf = ui.Frame(height=24)
        _sb = StatusBar(_sf)

from omni.ui import color as cl_color

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({
    "padding": 18.0,
    "background_color": cl_color.background_primary,
})

_renderer = MockRendererAdapter()
_stage_window = StageWidget(adapter=MockStageAdapter())
_prop_window = PropertyWindow()
_vp_window = ViewportWidget(services=_app, renderer=_renderer, bus=_bus)

_SELECTED_PATH = "/World/Geometry/Sphere"


# Capture every row as it is built so the verifier can reach back into
# ``row._model`` / ``row._widget`` after the panel finishes rendering.
# The production ``_build_attribute_row`` discards the return value of
# ``WidgetBuilderTable.build``; the spy keeps a strong reference in
# ``_built_rows`` so the GC cannot collect the row before we inspect it.
_built_rows: list = []
_original_build_fn = WidgetBuilderTable.build.__func__


def _capturing_build(cls, attr_name, metadata, adapter, **kwargs):
    row = _original_build_fn(cls, attr_name, metadata, adapter, **kwargs)
    _built_rows.append(row)
    return row


WidgetBuilderTable.build = classmethod(_capturing_build)


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()

    from omni.ui import testing
    await testing.wait_frames(10)

    adapter = _make_adapter([_SELECTED_PATH])
    _prop_window.set_adapter(adapter)
    _prop_window.set_selection([_SELECTED_PATH])
    _bus.publish([_SELECTED_PATH], source="qa")
    _renderer.set_selection_highlight([_SELECTED_PATH])
    _vp_window._on_frame(0.1)
    await testing.wait_frames(8)

    testing.capture_screenshot("/tmp/ovgear_step1_4_1.png")
    print("Screenshot: /tmp/ovgear_step1_4_1.png")

    rows = list(_built_rows)
    print(f"Built {len(rows)} rows")

    expected_classes = (
        FloatAttributeRow,
        Vec3FloatAttributeRow,
        IntAttributeRow,
        StringAttributeRow,
        BoolAttributeRow,
    )

    # Invariant 1: every row carries an AttributeModelBase instance.
    missing_model = [r for r in rows
                     if isinstance(r, expected_classes)
                     and not isinstance(getattr(r, "_model", None), AttributeModelBase)]
    assert not missing_model, (
        f"Rows missing AttributeModelBase: "
        f"{[(type(r).__name__, r._prop.name) for r in missing_model]}"
    )
    print(f"OK: every row ({len(rows)}) owns an AttributeModelBase")

    # Invariant 2: every row holds the two subscription handles.
    missing_subs = [r for r in rows
                    if isinstance(r, expected_classes)
                    and (getattr(r, "_value_sub", None) is None
                         or getattr(r, "_adapter_sub", None) is None)]
    assert not missing_subs, (
        f"Rows missing subscription handles: "
        f"{[(type(r).__name__, r._prop.name) for r in missing_subs]}"
    )
    print("OK: every row subscribed to model value changes and adapter changes")

    # Invariant 3: external backing change updates the widget value.
    #
    # Mutate radius through ``set_path_value`` (per-path backing store)
    # — this is what a USD-side edit would update without firing a notice —
    # then ``fire_change()`` to drive the Tf.Notice fan-out simulation.
    # Every row's ``model._on_backing_changed`` should run, refresh
    # ``_value`` from the adapter, notify subscribers, and
    # ``_on_model_value_changed`` should copy the new value into the widget.
    radius_row = next(r for r in rows
                      if isinstance(r, FloatAttributeRow) and r._prop.name == "radius")
    assert radius_row._widget is not None
    adapter.set_path_value(_SELECTED_PATH, "radius", 42.0)
    adapter.fire_change()
    assert radius_row._model.get_value() == 42.0, (
        f"model did not pick up external change: {radius_row._model.get_value()}"
    )
    assert radius_row._widget.model.get_value_as_float() == 42.0, (
        f"widget did not refresh from model: "
        f"{radius_row._widget.model.get_value_as_float()}"
    )
    print("OK: external adapter.fire_change refreshed the radius widget via model")

    # Invariant 3b: same for a vec3 row — all three channel widgets update.
    translate_row = next(r for r in rows
                         if isinstance(r, Vec3FloatAttributeRow)
                         and r._prop.name == "xformOp:translate")
    adapter.set_path_value(_SELECTED_PATH, "xformOp:translate", (10.0, 20.0, 30.0))
    adapter.fire_change()
    got = tuple(w.model.get_value_as_float() for w in translate_row._widgets)
    assert got == (10.0, 20.0, 30.0), (
        f"vec3 channel widgets did not refresh from model: {got}"
    )
    print("OK: external adapter.fire_change refreshed all 3 translate channels")

    # Invariant 4: no row's _on_* callbacks contain a direct adapter call.
    # Spot-check by reading the source — a regression would reintroduce
    # ``self._adapter.begin_edit`` / ``self._adapter.set_value`` /
    # ``self._adapter.end_edit`` in one of the _on_* handlers.
    import inspect

    banned = ("self._adapter.begin_edit",
              "self._adapter.set_value",
              "self._adapter.end_edit")
    for cls in expected_classes:
        src = inspect.getsource(cls)
        for token in banned:
            assert token not in src, (
                f"{cls.__name__} still calls {token!r} directly — Step 1.4 regression"
            )
    print("OK: no row class calls adapter.begin_edit/set_value/end_edit directly")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
