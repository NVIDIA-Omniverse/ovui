# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovwidgets.stage.models.visibility_value_model.VisibilityValueModel.

Exercises the inverted semantics (True == invisible), selection-aware group
toggle through VisibilityValueModel, undo-group wrapping, ``is_enabled`` for instance
proxies, and the ``mark_dirty`` rebroadcast path.

Headless — no visible window is needed; each test builds a
:class:`MockStageAdapter` + :class:`HierarchyModel` and exercises the value
model directly.
"""

from __future__ import annotations

import pytest
from ovui_data_adapters.common import ItemFlags, VisibilityState

from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.hierarchy_model import HierarchyItem, HierarchyModel
from ovwidgets.stage.models import VisibilityValueModel


@pytest.fixture
def adapter():
    return MockStageAdapter()


@pytest.fixture
def model(adapter):
    return HierarchyModel(adapter)


def _item(model: HierarchyModel, path: str) -> HierarchyItem:
    """Walk the tree until every item on the given path is cached, then return the leaf."""
    _ = model.get_item_children(None)  # root
    components = path.strip("/").split("/")
    current = model._root
    # Root is /World and it's always position 0 at the top level.
    assert current.adapter_item.path == "/" + components[0], path
    for name in components[1:]:
        children = model.get_item_children(current)
        match = next(c for c in children if c.adapter_item.name == name)
        current = match
    return current


# ── Construction ─────────────────────────────────────────────────────────────


class TestConstruction:
    def test_value_model_from_hierarchy_model(self, model):
        root = _item(model, "/World")
        vm = model.get_item_value_model(root, 2)
        assert isinstance(vm, VisibilityValueModel)

    def test_direct_construction(self, adapter, model):
        root = _item(model, "/World")
        vm = VisibilityValueModel(root, adapter, model)
        assert vm._item is root
        assert vm._adapter is adapter
        assert vm._model is model

    def test_same_value_model_returned_twice(self, model):
        root = _item(model, "/World")
        v1 = model.get_item_value_model(root, 2)
        v2 = model.get_item_value_model(root, 2)
        assert v1 is v2


# ── Inverted read semantics ──────────────────────────────────────────────────


class TestInvertedReadSemantics:
    def test_visible_item_reads_false(self, model):
        root = _item(model, "/World")
        vm = model.get_item_value_model(root, 2)
        assert vm.get_value_as_bool() is False

    def test_invisible_item_reads_true(self, model, adapter):
        cube = _item(model, "/World/Geometry/Cube")
        cube.adapter_item.visible = False
        vm = model.get_item_value_model(cube, 2)
        assert vm.get_value_as_bool() is True

    def test_inherited_invisible_reads_true(self, model, adapter):
        geometry = _item(model, "/World/Geometry")
        geometry.adapter_item.visible = False
        sphere = _item(model, "/World/Geometry/Sphere")
        assert adapter.compute_visibility(sphere.adapter_item) == VisibilityState.INHERITED_INVISIBLE
        vm = model.get_item_value_model(sphere, 2)
        assert vm.get_value_as_bool() is True

    def test_get_value_as_int_mirrors_bool(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        sphere.adapter_item.visible = False
        assert vm.get_value_as_int() == 1
        sphere.adapter_item.visible = True
        assert vm.get_value_as_int() == 0

    def test_get_value_as_string_mirrors_bool(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        sphere.adapter_item.visible = False
        assert vm.get_value_as_string() == "true"
        sphere.adapter_item.visible = True
        assert vm.get_value_as_string() == "false"


# ── Single-item write ────────────────────────────────────────────────────────


class TestSingleItemWrite:
    def test_set_value_true_hides(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)
        assert sphere.adapter_item.visible is False

    def test_set_value_false_shows(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        sphere.adapter_item.visible = False
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(False)
        assert sphere.adapter_item.visible is True

    def test_set_value_unrelated_item_untouched(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        cube = _item(model, "/World/Geometry/Cube")
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)
        assert cube.adapter_item.visible is True

    def test_set_value_single_selected_item_only_toggles_itself(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        cube = _item(model, "/World/Geometry/Cube")
        model._selected_items = [sphere]
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)
        assert sphere.adapter_item.visible is False
        assert cube.adapter_item.visible is True

    def test_set_value_coerces_non_bool(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(1)  # truthy → hidden
        assert sphere.adapter_item.visible is False


# ── Group toggle (selection-aware) ───────────────────────────────────────────


class TestGroupToggle:
    def test_multi_selection_toggles_every_item(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        cube = _item(model, "/World/Geometry/Cube")
        ground = _item(model, "/World/Geometry/Ground")
        model._selected_items = [sphere, cube, ground]
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)
        assert sphere.adapter_item.visible is False
        assert cube.adapter_item.visible is False
        assert ground.adapter_item.visible is False

    def test_multi_selection_shows_every_item(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        cube = _item(model, "/World/Geometry/Cube")
        for item in (sphere, cube):
            item.adapter_item.visible = False
        model._selected_items = [sphere, cube]
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(False)
        assert sphere.adapter_item.visible is True
        assert cube.adapter_item.visible is True

    def test_clicked_item_not_in_selection_only_toggles_itself(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        cube = _item(model, "/World/Geometry/Cube")
        ground = _item(model, "/World/Geometry/Ground")
        model._selected_items = [cube, ground]  # sphere not selected
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)
        assert sphere.adapter_item.visible is False
        assert cube.adapter_item.visible is True
        assert ground.adapter_item.visible is True

    def test_multi_selection_skips_noneditable_items(self, model, adapter):
        sphere = _item(model, "/World/Geometry/Sphere")
        cube = _item(model, "/World/Geometry/Cube")
        adapter.set_item_flags("/World/Geometry/Cube", ItemFlags.IS_INSTANCE_PROXY)
        model._selected_items = [sphere, cube]

        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)

        assert sphere.adapter_item.visible is False
        assert cube.adapter_item.visible is True

    def test_set_value_noops_when_item_is_not_editable(self, model, adapter, monkeypatch):
        cube = _item(model, "/World/Geometry/Cube")
        adapter.set_item_flags("/World/Geometry/Cube", ItemFlags.IS_INSTANCE_PROXY)
        calls: list[str] = []
        monkeypatch.setattr(
            model._adapter,
            "begin_undo_group",
            lambda label: calls.append("begin"),
        )
        monkeypatch.setattr(model._adapter, "end_undo_group", lambda: calls.append("end"))

        vm = model.get_item_value_model(cube, 2)
        vm.set_value(True)

        assert cube.adapter_item.visible is True
        assert calls == []


# ── Undo grouping ────────────────────────────────────────────────────────────


class TestUndoGrouping:
    def test_single_begin_end_undo_group_per_click(self, model, monkeypatch):
        calls: list[tuple[str, object]] = []
        monkeypatch.setattr(
            model._adapter,
            "begin_undo_group",
            lambda label: calls.append(("begin", label)),
        )
        monkeypatch.setattr(
            model._adapter,
            "end_undo_group",
            lambda: calls.append(("end", None)),
        )
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)
        assert calls == [("begin", "Toggle Visibility"), ("end", None)]

    def test_group_toggle_wraps_every_target_in_single_group(self, model, monkeypatch):
        sequence: list[str] = []
        orig_set_visibility = model._adapter.set_visibility
        monkeypatch.setattr(
            model._adapter,
            "begin_undo_group",
            lambda label: sequence.append("begin"),
        )
        monkeypatch.setattr(
            model._adapter,
            "end_undo_group",
            lambda: sequence.append("end"),
        )

        def tracked_set_visibility(item, visible):
            sequence.append(f"set:{item.path}={visible}")
            orig_set_visibility(item, visible)

        monkeypatch.setattr(model._adapter, "set_visibility", tracked_set_visibility)

        sphere = _item(model, "/World/Geometry/Sphere")
        cube = _item(model, "/World/Geometry/Cube")
        model._selected_items = [sphere, cube]
        vm = model.get_item_value_model(sphere, 2)
        vm.set_value(True)
        assert sequence[0] == "begin"
        assert sequence[-1] == "end"
        assert sequence.count("begin") == 1
        assert sequence.count("end") == 1
        # Two set_visibility calls between begin/end.
        assert sum(1 for s in sequence if s.startswith("set:")) == 2

    def test_end_undo_group_called_even_on_set_visibility_error(self, model, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            model._adapter, "begin_undo_group", lambda label: calls.append("begin")
        )
        monkeypatch.setattr(model._adapter, "end_undo_group", lambda: calls.append("end"))

        def raising(item, visible):
            raise RuntimeError("boom")

        monkeypatch.setattr(model._adapter, "set_visibility", raising)
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        with pytest.raises(RuntimeError):
            vm.set_value(True)
        assert calls == ["begin", "end"]


# ── is_enabled ───────────────────────────────────────────────────────────────


class TestIsEnabled:
    def test_default_is_enabled_true(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        assert vm.is_enabled() is True

    def test_is_enabled_reflects_adapter(self, model, monkeypatch):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        monkeypatch.setattr(
            model._adapter, "can_edit_visibility", lambda item: False
        )
        assert vm.is_enabled() is False

    def test_is_enabled_called_with_adapter_item(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        seen: list = []
        vm._adapter.can_edit_visibility = lambda item: seen.append(item) or True  # type: ignore[assignment]
        _ = vm.is_enabled()
        assert seen == [sphere.adapter_item]

    def test_is_enabled_false_for_instance_proxy_flag(self, model, adapter):
        camera = _item(model, "/World/Camera")
        adapter.set_item_flags("/World/Camera", ItemFlags.IS_INSTANCE_PROXY)
        vm = model.get_item_value_model(camera, 2)
        assert vm.is_enabled() is False


# ── Rebroadcast via mark_dirty ───────────────────────────────────────────────


class TestRebroadcast:
    def test_mark_dirty_triggers_value_changed(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        events: list[int] = []
        sub = vm.subscribe_value_changed_fn(lambda m: events.append(1))  # noqa: F841
        sphere.mark_dirty()
        assert len(events) == 1

    def test_mark_dirty_without_vis_model_is_safe(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        assert sphere._vis_model is None
        sphere.mark_dirty()  # no model bound yet → no-op path must not crash

    def test_adapter_change_fires_value_changed(self, model, adapter):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        events: list[int] = []
        sub = vm.subscribe_value_changed_fn(lambda m: events.append(1))  # noqa: F841
        # Simulate a visibility change elsewhere + change event.
        sphere.adapter_item.visible = False
        adapter.fire_change(["/World/Geometry/Sphere"])
        assert len(events) >= 1
        assert vm.get_value_as_bool() is True

    def test_adapter_change_rebroadcasts_cached_item_after_tree_reset(self, model, adapter):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        events: list[int] = []
        sub = vm.subscribe_value_changed_fn(lambda m: events.append(1))  # noqa: F841

        sphere.adapter_item.visible = False
        adapter.fire_change(["/World/Geometry/Sphere"])
        first_count = len(events)
        assert first_count >= 1

        sphere.adapter_item.visible = True
        adapter.fire_change(["/World/Geometry/Sphere"])
        assert len(events) > first_count
        assert vm.get_value_as_bool() is False


# ── HierarchyModel column-2 integration ──────────────────────────────────────


class TestHierarchyModelIntegration:
    def test_column_2_returns_visibility_value_model(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        assert isinstance(vm, VisibilityValueModel)

    def test_invalidate_item_keeps_vis_model_instance(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        model.invalidate_item(sphere)
        # The model stays — it re-reads adapter state on every access.
        assert sphere._vis_model is vm

    def test_invalidate_value_models_keeps_vis_model_instance(self, model):
        sphere = _item(model, "/World/Geometry/Sphere")
        vm = model.get_item_value_model(sphere, 2)
        model._invalidate_value_models(model._root)
        assert sphere._vis_model is vm
