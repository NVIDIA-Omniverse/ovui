# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for StageDelegate and updated StageWidget (Steps 15–16)."""

import omni.ui as ui
from ovui_data_adapters.common import ItemFlags, VisibilityState

from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.hierarchy_model import HierarchyItem, HierarchyModel
from ovwidgets.stage.stage_delegate import StageDelegate
from ovwidgets.stage.style import STAGE_STYLES


class TestStageDelegateImport:
    def test_import(self):
        from ovwidgets.stage.stage_delegate import StageDelegate
        assert StageDelegate is not None

    def test_is_abstract_delegate_subclass(self):
        d = StageDelegate()
        assert isinstance(d, ui.AbstractItemDelegate)

    def test_instantiate(self):
        d = StageDelegate()
        assert d is not None

    def test_has_build_branch(self):
        assert callable(StageDelegate.build_branch)

    def test_has_build_header(self):
        assert callable(StageDelegate.build_header)

    def test_has_build_widget(self):
        assert callable(StageDelegate.build_widget)

    def test_row_height_matches_design_token(self):
        import ovwidgets.app
        import ovwidgets.app.style.constants  # noqa: F401
        from ovwidgets.stage.widget.stage_delegate import _ROW_HEIGHT

        assert _ROW_HEIGHT == ui.FloatStore.find("treeview_row_height")

    def test_prim_icon_size_is_smaller_than_dense_row(self):
        from ovwidgets.stage.widget.stage_delegate import _ROW_HEIGHT, _TYPE_ICON_SIZE

        assert _TYPE_ICON_SIZE == 10
        assert _TYPE_ICON_SIZE < _ROW_HEIGHT

    def test_tree_chevron_size_matches_property_header(self):
        from ovwidgets.property.group_widget import _CHEVRON_SIZE as property_size
        from ovwidgets.stage.widget.stage_delegate import _CHEVRON_SIZE as tree_size

        assert tree_size == property_size == 12

    def test_default_prim_pill_label_is_reference_abbreviation(self):
        from ovwidgets.stage.widget.stage_delegate import _DEFAULT_PILL_LABEL

        assert _DEFAULT_PILL_LABEL == "DEF"
        assert _DEFAULT_PILL_LABEL != "DEFAULT"

    def test_default_prim_pill_geometry_is_compact(self):
        from ovwidgets.stage.widget.stage_delegate import (
            _DEFAULT_PILL_HEIGHT,
            _DEFAULT_PILL_HORIZONTAL_PADDING,
            _DEFAULT_PILL_WIDTH,
            _ROW_HEIGHT,
        )

        assert _DEFAULT_PILL_WIDTH == 24
        assert _DEFAULT_PILL_HEIGHT == 12
        assert _DEFAULT_PILL_HEIGHT < _ROW_HEIGHT
        assert _DEFAULT_PILL_HORIZONTAL_PADDING == 4

    def test_exported_from_package(self):
        from ovwidgets.stage import StageDelegate as SD
        assert SD is StageDelegate


class TestStageWidgetCreation:
    def test_create_with_mock_adapter(self):
        from ovwidgets.stage.stage_widget import StageWidget
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        assert w is not None
        w.destroy()

    def test_create_with_default_adapter(self):
        from ovwidgets.stage.stage_widget import StageWidget
        w = StageWidget()
        assert w is not None
        w.destroy()

    def test_has_model(self):
        from ovwidgets.stage.stage_widget import StageWidget
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        assert isinstance(w._model, HierarchyModel)
        w.destroy()

    def test_has_delegate(self):
        from ovwidgets.stage.stage_widget import StageWidget
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        assert isinstance(w._delegate, StageDelegate)
        w.destroy()

    def test_adapter_stored(self):
        from ovwidgets.stage.stage_widget import StageWidget
        adapter = MockStageAdapter()
        w = StageWidget(adapter=adapter)
        assert w._adapter is adapter
        w.destroy()


class TestHierarchyModelItems:
    def test_root_is_returned(self):
        model = HierarchyModel(MockStageAdapter())
        roots = model.get_item_children(None)
        assert len(roots) == 1

    def test_root_is_hierarchy_item(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        assert isinstance(root, HierarchyItem)

    def test_root_name_is_world(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        name_model = model.get_item_value_model(root, 0)
        assert name_model is not None
        assert name_model.as_string == "World"

    def test_root_children_names(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        names = {model.get_item_value_model(c, 0).as_string for c in children}
        assert names == {"Geometry", "Lights", "Camera"}

    def test_geometry_children(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        geometry = next(c for c in children
                        if model.get_item_value_model(c, 0).as_string == "Geometry")
        geo_children = model.get_item_children(geometry)
        names = {model.get_item_value_model(c, 0).as_string for c in geo_children}
        assert names == {"Ground", "Sphere", "Cube"}

    def test_lights_children(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        lights = next(c for c in children
                      if model.get_item_value_model(c, 0).as_string == "Lights")
        light_children = model.get_item_children(lights)
        names = {model.get_item_value_model(c, 0).as_string for c in light_children}
        assert names == {"DomeLight"}

    def test_can_item_have_children_root(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        assert model.can_item_have_children(root) is True

    def test_can_item_have_children_geometry(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        geometry = next(c for c in children
                        if model.get_item_value_model(c, 0).as_string == "Geometry")
        assert model.can_item_have_children(geometry) is True

    def test_can_item_have_children_leaf(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        geometry = next(c for c in children
                        if model.get_item_value_model(c, 0).as_string == "Geometry")
        geo_children = model.get_item_children(geometry)
        ground = next(c for c in geo_children
                      if model.get_item_value_model(c, 0).as_string == "Ground")
        assert model.can_item_have_children(ground) is False

    def test_can_item_have_children_camera_leaf(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        camera = next(c for c in children
                      if model.get_item_value_model(c, 0).as_string == "Camera")
        assert model.can_item_have_children(camera) is False

    def test_can_item_have_children_non_item(self):
        model = HierarchyModel(MockStageAdapter())
        assert model.can_item_have_children(None) is False
        assert model.can_item_have_children("not_an_item") is False


class TestThreeColumnModel:
    """Step 16 — verify 3-column HierarchyModel."""

    def _get_root_child(self, model, name):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        return next(c for c in children
                    if model.get_item_value_model(c, 0).as_string == name)

    def test_column_count_is_3(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        assert model.get_item_value_model_count(root) == 3

    def test_num_columns_constant(self):
        assert HierarchyModel.NUM_COLUMNS == 3

    def test_column1_returns_type_name(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        type_model = model.get_item_value_model(root, 1)
        assert type_model is not None
        assert type_model.as_string == "Xform"

    def test_column1_mesh_type(self):
        model = HierarchyModel(MockStageAdapter())
        ground = self._get_root_child(model, "Geometry")
        # expand Geometry
        model.get_item_children(ground)
        geo_children = model.get_item_children(ground)
        cube = next(c for c in geo_children
                    if model.get_item_value_model(c, 0).as_string == "Cube")
        type_model = model.get_item_value_model(cube, 1)
        assert type_model.as_string == "Mesh"

    def test_column1_camera_type(self):
        model = HierarchyModel(MockStageAdapter())
        camera = self._get_root_child(model, "Camera")
        type_model = model.get_item_value_model(camera, 1)
        assert type_model.as_string == "Camera"

    def test_column2_visibility_visible(self):
        # Inverted: visible item → get_value_as_bool() is False (checkbox unchecked).
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        vis_model = model.get_item_value_model(root, 2)
        assert vis_model is not None
        assert vis_model.get_value_as_bool() is False

    def test_column2_visibility_hidden_after_set(self):
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        camera = self._get_root_child(model, "Camera")
        vis_model = model.get_item_value_model(camera, 2)
        assert vis_model.get_value_as_bool() is False
        # Hide via the adapter — VisibilityValueModel re-reads state on access.
        adapter.set_visibility(camera.adapter_item, False)
        assert vis_model.get_value_as_bool() is True

    def test_column2_is_visibility_value_model(self):
        from ovwidgets.stage.models import VisibilityValueModel
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        vis_model = model.get_item_value_model(root, 2)
        assert isinstance(vis_model, VisibilityValueModel)

    def test_column1_is_string_model(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        type_model = model.get_item_value_model(root, 1)
        assert isinstance(type_model, ui.SimpleStringModel)

    def test_column_out_of_range_returns_none(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        assert model.get_item_value_model(root, 3) is None
        assert model.get_item_value_model(root, -1) is None

    def test_type_model_cached(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        m1 = model.get_item_value_model(root, 1)
        m2 = model.get_item_value_model(root, 1)
        assert m1 is m2

    def test_vis_model_cached(self):
        model = HierarchyModel(MockStageAdapter())
        root = model.get_item_children(None)[0]
        m1 = model.get_item_value_model(root, 2)
        m2 = model.get_item_value_model(root, 2)
        assert m1 is m2

    def test_vis_model_rebroadcasts_on_adapter_change(self):
        # VisibilityValueModel stays in place on adapter changes — it reads
        # through to the adapter on every access and fires _value_changed()
        # via HierarchyItem.mark_dirty() so bound widgets repaint.
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        root = model.get_item_children(None)[0]
        vis_model = model.get_item_value_model(root, 2)
        events: list[int] = []
        sub = vis_model.subscribe_value_changed_fn(lambda m: events.append(1))  # noqa: F841
        adapter.set_visibility(root.adapter_item, False)
        assert root._vis_model is vis_model
        assert vis_model.get_value_as_bool() is True
        assert len(events) >= 1


class TestSelectionAccentRendering:
    def _patch_row_ui(self, monkeypatch):
        from ovwidgets.stage.widget import stage_delegate as delegate_mod

        rectangles = []

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _FakeImage:
            def set_mouse_pressed_fn(self, fn):
                self.mouse_pressed_fn = fn

        monkeypatch.setattr(delegate_mod.ui, "ZStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "HStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "VStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "Spacer", lambda **kwargs: None)
        monkeypatch.setattr(
            delegate_mod.ui,
            "ImageWithProvider",
            lambda *args, **kwargs: _FakeImage(),
        )
        monkeypatch.setattr(
            delegate_mod.ui,
            "Rectangle",
            lambda **kwargs: rectangles.append(kwargs),
        )
        return rectangles

    def test_selected_branch_draws_left_edge_accent(self, monkeypatch):
        rectangles = self._patch_row_ui(monkeypatch)
        model = HierarchyModel(MockStageAdapter())
        item = model.get_item_children(None)[0]
        model._selected_items = [item]

        StageDelegate().build_branch(model, item, 0, 0, False)

        assert {
            "width": 3,
            "height": 18,
            "style_type_name_override": "Stage.SelectionAccent",
        } in rectangles

    def test_unselected_branch_has_no_accent(self, monkeypatch):
        rectangles = self._patch_row_ui(monkeypatch)
        model = HierarchyModel(MockStageAdapter())
        item = model.get_item_children(None)[0]

        StageDelegate().build_branch(model, item, 0, 0, False)

        assert all(
            rect.get("style_type_name_override") != "Stage.SelectionAccent"
            for rect in rectangles
        )

    def test_selected_visibility_column_has_no_accent(self, monkeypatch):
        rectangles = self._patch_row_ui(monkeypatch)
        model = HierarchyModel(MockStageAdapter())
        item = model.get_item_children(None)[0]
        model._selected_items = [item]

        StageDelegate()._build_visibility_column(model, item)

        assert all(
            rect.get("style_type_name_override") != "Stage.SelectionAccent"
            for rect in rectangles
        )


class TestBranchChevronRendering:
    def _patch_branch_ui(self, monkeypatch):
        from ovwidgets.stage.widget import stage_delegate as delegate_mod

        images = []

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _FakeImage:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        def _image(*args, **kwargs):
            image = _FakeImage(*args, **kwargs)
            images.append(image)
            return image

        monkeypatch.setattr(delegate_mod.ui, "ZStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "HStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "VStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "Spacer", lambda **kwargs: None)
        monkeypatch.setattr(delegate_mod.ui, "Rectangle", lambda **kwargs: None)
        monkeypatch.setattr(delegate_mod.ui, "ImageWithProvider", _image)
        monkeypatch.setattr(delegate_mod.stage_icons, "provider", lambda path: path)
        return delegate_mod, images

    def test_tree_branch_chevron_uses_plan_selector_and_size(self, monkeypatch):
        delegate_mod, images = self._patch_branch_ui(monkeypatch)
        model = HierarchyModel(MockStageAdapter())
        item = model.get_item_children(None)[0]

        StageDelegate().build_branch(model, item, 0, 0, False)

        image = images[-1]
        assert image.kwargs["width"] == delegate_mod._CHEVRON_SIZE == 12
        assert image.kwargs["height"] == delegate_mod._CHEVRON_SIZE == 12
        assert image.kwargs["style_type_name_override"] == "Stage.TreeChevron"

    def test_tree_branch_chevron_rotates_by_expansion_state(self, monkeypatch):
        delegate_mod, images = self._patch_branch_ui(monkeypatch)
        model = HierarchyModel(MockStageAdapter())
        item = model.get_item_children(None)[0]

        StageDelegate().build_branch(model, item, 0, 0, False)
        StageDelegate().build_branch(model, item, 0, 0, True)

        assert images[-2].args == (delegate_mod._CHEVRON_RIGHT,)
        assert images[-1].args == (delegate_mod._CHEVRON_DOWN,)


class TestVisibilityIconRendering:
    def _item(self, model, path):
        current = model.get_item_children(None)[0]
        for name in path.strip("/").split("/")[1:]:
            current = next(
                child for child in model.get_item_children(current)
                if child.adapter_item.name == name
            )
        return current

    def _patch_visibility_ui(self, monkeypatch):
        from ovwidgets.stage.widget import stage_delegate as delegate_mod

        images = []
        frames = []

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _FakeImage:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        def _image(*args, **kwargs):
            image = _FakeImage(*args, **kwargs)
            images.append(image)
            return image

        class _FakeFrame:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.opaque_for_mouse_events = False
                self.mouse_pressed_fn = None
                self.build_fn = None
                self.rebuild_calls = 0
                frames.append(self)

            def set_mouse_pressed_fn(self, fn):
                self.mouse_pressed_fn = fn

            def set_build_fn(self, fn):
                self.build_fn = fn
                self.rebuild()

            def rebuild(self):
                self.rebuild_calls += 1
                if self.build_fn is not None:
                    self.build_fn()

        monkeypatch.setattr(delegate_mod.ui, "HStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "VStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "Frame", _FakeFrame)
        monkeypatch.setattr(delegate_mod.ui, "Spacer", lambda **kwargs: None)
        monkeypatch.setattr(delegate_mod.ui, "ImageWithProvider", _image)
        monkeypatch.setattr(delegate_mod.stage_icons, "provider", lambda path: path)
        return delegate_mod, images, frames

    def test_visible_icon_uses_visibility_selector_and_click_target(self, monkeypatch):
        delegate_mod, images, frames = self._patch_visibility_ui(monkeypatch)
        model = HierarchyModel(MockStageAdapter())
        sphere = self._item(model, "/World/Geometry/Sphere")

        delegate = StageDelegate()
        delegate._build_visibility_column(model, sphere)

        frame = frames[-1]
        eye = images[-1]
        assert eye.args == (delegate_mod.stage_icons.eye_on_icon(),)
        assert eye.kwargs["style_type_name_override"] == "Stage.VisibilityIcon"
        assert eye.kwargs["name"] == "visible"
        assert eye.kwargs["width"] == delegate_mod._VISIBILITY_ICON_SIZE == 14
        assert eye.kwargs["height"] == delegate_mod._VISIBILITY_ICON_SIZE == 14
        assert frame.kwargs["width"] == delegate_mod._VISIBILITY_ICON_SIZE == 14
        assert frame.kwargs["height"] == delegate_mod._VISIBILITY_ICON_SIZE == 14
        assert frame.opaque_for_mouse_events is True
        assert callable(frame.mouse_pressed_fn)

    def test_hidden_icon_derives_from_live_adapter_state(self, monkeypatch):
        delegate_mod, images, _ = self._patch_visibility_ui(monkeypatch)
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        sphere = self._item(model, "/World/Geometry/Sphere")
        adapter.set_visibility(sphere.adapter_item, False)

        delegate = StageDelegate()
        delegate._build_visibility_column(model, sphere)

        eye = images[-1]
        assert eye.args == (delegate_mod.stage_icons.eye_off_icon(),)
        assert eye.kwargs["name"] == "hidden"

    def test_left_click_toggles_visibility_through_value_model(self, monkeypatch):
        delegate_mod, images, frames = self._patch_visibility_ui(monkeypatch)
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        sphere = self._item(model, "/World/Geometry/Sphere")

        delegate = StageDelegate()
        delegate._build_visibility_column(model, sphere)
        frame = frames[-1]
        assert images[-1].args == (delegate_mod.stage_icons.eye_on_icon(),)
        frame.mouse_pressed_fn(0, 0, 0, 0)
        assert adapter.compute_visibility(sphere.adapter_item) == VisibilityState.INVISIBLE
        assert frame.rebuild_calls >= 2
        assert images[-1].args == (delegate_mod.stage_icons.eye_off_icon(),)
        assert images[-1].kwargs["name"] == "hidden"

        frame.mouse_pressed_fn(0, 0, 0, 0)
        assert adapter.compute_visibility(sphere.adapter_item) == VisibilityState.VISIBLE
        assert images[-1].args == (delegate_mod.stage_icons.eye_on_icon(),)
        assert images[-1].kwargs["name"] == "visible"

    def test_selected_item_click_group_toggles_selection(self, monkeypatch):
        _, _, frames = self._patch_visibility_ui(monkeypatch)
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        sphere = self._item(model, "/World/Geometry/Sphere")
        cube = self._item(model, "/World/Geometry/Cube")
        model._selected_items = [sphere, cube]

        delegate = StageDelegate()
        delegate._build_visibility_column(model, sphere)
        frames[-1].mouse_pressed_fn(0, 0, 0, 0)

        assert adapter.compute_visibility(sphere.adapter_item) == VisibilityState.INVISIBLE
        assert adapter.compute_visibility(cube.adapter_item) == VisibilityState.INVISIBLE

    def test_right_click_does_not_toggle_visibility(self, monkeypatch):
        _, _, frames = self._patch_visibility_ui(monkeypatch)
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        sphere = self._item(model, "/World/Geometry/Sphere")

        delegate = StageDelegate()
        delegate._build_visibility_column(model, sphere)
        frames[-1].mouse_pressed_fn(0, 0, 1, 0)

        assert adapter.compute_visibility(sphere.adapter_item) == VisibilityState.VISIBLE

    def test_disabled_visibility_icon_is_not_clickable(self, monkeypatch):
        _, images, frames = self._patch_visibility_ui(monkeypatch)
        model = HierarchyModel(MockStageAdapter())
        sphere = self._item(model, "/World/Geometry/Sphere")
        model._adapter.can_edit_visibility = lambda item: False

        delegate = StageDelegate()
        delegate._build_visibility_column(model, sphere)

        frame = frames[-1]
        eye = images[-1]
        assert eye.kwargs["name"] == "disabled"
        assert frame.opaque_for_mouse_events is False
        assert frame.mouse_pressed_fn is None

    def test_inactive_visibility_icon_is_not_clickable(self, monkeypatch):
        _, images, frames = self._patch_visibility_ui(monkeypatch)
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        sphere = self._item(model, "/World/Geometry/Sphere")
        adapter.set_item_flags("/World/Geometry/Sphere", ItemFlags.IS_INACTIVE)

        delegate = StageDelegate()
        delegate._build_visibility_column(model, sphere)

        frame = frames[-1]
        eye = images[-1]
        assert eye.kwargs["name"] == "disabled"
        assert frame.opaque_for_mouse_events is False
        assert frame.mouse_pressed_fn is None


class TestTypeLabelRendering:
    def test_type_column_displays_lowercase_without_category_name(self, monkeypatch):
        from ovwidgets.stage.widget import stage_delegate as delegate_mod

        calls = []

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _TypeModel:
            as_string = "DistantLight"

        class _Model:
            def get_item_value_model(self, item, column_id):
                assert column_id == 1
                return _TypeModel()

        def _label(text, **kwargs):
            calls.append((text, kwargs))

        monkeypatch.setattr(delegate_mod.ui, "HStack", lambda **kwargs: _Ctx())
        monkeypatch.setattr(delegate_mod.ui, "Spacer", lambda **kwargs: None)
        monkeypatch.setattr(delegate_mod.ui, "Label", _label)

        StageDelegate()._build_type_column(_Model(), object())

        assert calls == [
            (
                "distantlight",
                {
                    "style_type_name_override": "Stage.TypeLabel",
                    "alignment": delegate_mod.ui.Alignment.LEFT_CENTER,
                },
            )
        ]


class TestStageStyles:
    """STAGE_STYLES key completeness (feature/stage-design).

    The original prototype styled the Type column with coloured rectangle
    "badges" and the Vis column with a text ``Button`` (``Stage.TypeBadge*``
    / ``Stage.VisibilityButton*``). Design Step 6 keeps the Type column as
    a text label but removes category tinting: every displayed type label
    uses ``Stage.TypeLabel`` with ``cl.text_secondary``.
    """

    def test_column_header_key(self):
        assert "Stage.ColumnHeader" in STAGE_STYLES
        assert "Stage.ColumnHeader.Bg" in STAGE_STYLES
        assert "Stage.ColumnHeader.Rule" in STAGE_STYLES

    def test_column_header_style_matches_step4_tokens(self):
        style = STAGE_STYLES["Stage.ColumnHeader"]
        assert style["color"] == "text_secondary"
        assert style["font_size"] == "font_size_small"

    def test_column_header_rule_uses_default_border(self):
        assert (
            STAGE_STYLES["Stage.ColumnHeader.Rule"]["background_color"]
            == "border_default"
        )

    def test_type_label_base_key(self):
        assert "Stage.TypeLabel" in STAGE_STYLES

    def test_type_label_uses_single_muted_color(self):
        assert STAGE_STYLES["Stage.TypeLabel"]["color"] == "text_secondary"

    def test_type_label_selected_keeps_muted_color(self):
        assert "Stage.TypeLabel:selected" in STAGE_STYLES
        assert STAGE_STYLES["Stage.TypeLabel:selected"]["color"] == "text_secondary"

    def test_type_label_selected_matches_base_type_label_color(self):
        assert (
            STAGE_STYLES["Stage.TypeLabel:selected"]["color"]
            == STAGE_STYLES["Stage.TypeLabel"]["color"]
        )

    def test_type_label_has_no_category_color_overrides(self):
        category_selectors = [
            selector for selector in STAGE_STYLES
            if selector.startswith("Stage.TypeLabel::")
        ]
        assert category_selectors == []

    def test_visibility_icon_key(self):
        assert "Stage.VisibilityIcon" in STAGE_STYLES

    def test_visibility_icon_visible_uses_secondary_text(self):
        assert STAGE_STYLES["Stage.VisibilityIcon::visible"]["color"] == "text_secondary"

    def test_prim_icon_uses_muted_text_color(self):
        assert STAGE_STYLES["Stage.PrimIcon"]["color"] == "text_secondary"

    def test_stage_scrolling_frame_uses_step19_scrollbar_tokens(self):
        style = STAGE_STYLES["Stage.ScrollingFrame"]
        assert style["background_color"] == "treeview_well_background"
        assert style["secondary_color"] == "scrollbar_thumb"
        assert style["scrollbar_size"] == "scrollbar_width"
        assert style["border_radius"] == "radius_small"

    def test_stage_scrolling_frame_hover_uses_hover_thumb(self):
        assert (
            STAGE_STYLES["Stage.ScrollingFrame:hovered"]["secondary_color"]
            == "scrollbar_thumb_hovered"
        )
        assert (
            STAGE_STYLES["Stage.ScrollingFrame:pressed"]["secondary_color"]
            == "scrollbar_thumb_hovered"
        )

    def test_footer_style_key(self):
        assert "Stage.Footer" in STAGE_STYLES

    def test_footer_uses_small_muted_text(self):
        style = STAGE_STYLES["Stage.Footer"]
        assert style["color"] == "text_secondary"
        assert style["font_size"] == "font_size_small"

    def test_footer_top_rule_uses_default_border(self):
        assert "Stage.Footer.Rule" in STAGE_STYLES
        assert STAGE_STYLES["Stage.Footer.Rule"]["background_color"] == "border_default"

    def test_visibility_icon_hidden_key(self):
        assert "Stage.VisibilityIcon::hidden" in STAGE_STYLES

    def test_visibility_icon_hidden_is_dimmer_than_visible(self):
        assert STAGE_STYLES["Stage.VisibilityIcon::hidden"]["color"] == "text_disabled"

    def test_visibility_icon_disabled_key(self):
        assert "Stage.VisibilityIcon::disabled" in STAGE_STYLES

    def test_selection_accent_key(self):
        assert "Stage.SelectionAccent" in STAGE_STYLES

    def test_selection_accent_uses_primary_accent(self):
        assert (
            STAGE_STYLES["Stage.SelectionAccent"]["background_color"]
            == "treeview_selection"
        )

    def test_name_label_state_keys(self):
        assert "Stage.Name" in STAGE_STYLES
        assert "Stage.Name::inactive" in STAGE_STYLES
        assert "Stage.Name::abstract" in STAGE_STYLES
        assert "Stage.Name:selected" in STAGE_STYLES

    def test_default_prim_pill_key(self):
        assert "Stage.DefaultPrimPill" in STAGE_STYLES

    def test_default_prim_pill_uses_compact_dark_fill(self):
        style = STAGE_STYLES["Stage.DefaultPrimPill"]
        assert style["background_color"] == "stage_default_prim_pill_background"
        assert style["border_color"] == "stage_default_prim_pill_background"
        assert style["border_radius"] == "radius_small"
        assert style["border_width"] == 1

    def test_default_prim_pill_hover_does_not_imply_interaction(self):
        assert STAGE_STYLES["Stage.DefaultPrimPill:hovered"] == (
            STAGE_STYLES["Stage.DefaultPrimPill"]
        )

    def test_default_prim_pill_label_uses_muted_text(self):
        style = STAGE_STYLES["Stage.DefaultPrimPill.Label"]
        assert style["color"] == "text_secondary"
        assert style["font_size"] == "font_size_tiny"
        assert style["padding"] == 0
