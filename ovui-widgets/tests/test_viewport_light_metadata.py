# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Selected light metadata follows scene changes, not camera frame ordinals."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ovui_widgets.viewport.light_manipulator import LightManipulator
from ovui_widgets.viewport.viewport_widget import ViewportSurface


def make_view(light_type="StreamedPointCloud"):
    paths = ["/World/Cloud"]
    item = SimpleNamespace(light_type=light_type)
    adapter = SimpleNamespace(
        get_item_at_path=Mock(return_value=item),
        get_type_category=Mock(side_effect=lambda value: "Light" if value.light_type.endswith("Light") else "Other"),
        get_icon_name=Mock(side_effect=lambda value: value.light_type),
        get_light_shape_attributes=Mock(return_value={"radius": 2.0}),
        read_stage_meters_per_unit=Mock(return_value=1.0),
    )
    view = ViewportSurface.__new__(ViewportSurface)
    view._bus = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(paths=lambda: list(paths)))
    view._stage_adapter_provider = lambda: adapter
    view._selected_light_type_cache = None
    view._active_camera_path = None
    view._renderer = None
    view._get_outline_selection = lambda: []
    return view, adapter, item, paths


def change(*paths, resync=False):
    return SimpleNamespace(
        changed_paths=() if resync else paths,
        resynced_paths=paths if resync else (),
    )


def test_selected_cloud_camera_updates_do_not_repeat_topology_queries():
    view, adapter, _item, _paths = make_view()
    for frame in range(100):
        # Both a moving runtime camera and unrelated edits leave type unchanged.
        adapter.current_ordinal = frame
        view.notify_stage_changed(change("/Render/Camera"))
        assert view._selected_light_type() == ""
        assert view._selected_light_geometry() == {}
    adapter.get_item_at_path.assert_called_once_with("/World/Cloud")
    adapter.get_type_category.assert_called_once()
    adapter.get_light_shape_attributes.assert_not_called()


@pytest.mark.parametrize("changed_path", [
    "/World/Cloud", "/World", "/", "/World/Cloud.usd-prim-type", "/World.usd-schemas",
])
@pytest.mark.parametrize("resync", [False, True])
def test_relevant_change_invalidates_cached_nonlight_classification(changed_path, resync):
    view, adapter, item, _paths = make_view()
    assert view._selected_light_type() == ""
    item.light_type = "RectLight"
    view.notify_stage_changed(change(changed_path, resync=resync))
    assert view._selected_light_type() == "RectLight"
    assert adapter.get_item_at_path.call_count == 2


def test_same_path_delete_then_recreate_retries_until_population_finishes():
    view, adapter, _item, _paths = make_view("SphereLight")
    assert view._selected_light_type() == "SphereLight"
    adapter.get_item_at_path.return_value = None
    view.notify_stage_changed(change("/World/Cloud", resync=True))
    assert view._selected_light_type() == ""
    adapter.get_item_at_path.return_value = SimpleNamespace(light_type="StreamedPointCloud")
    assert view._selected_light_type() == ""
    assert view._selected_light_type() == ""
    assert adapter.get_item_at_path.call_count == 3


def test_failed_classification_is_retried():
    view, adapter, _item, _paths = make_view("SphereLight")
    adapter.get_item_at_path.side_effect = [RuntimeError("stage busy"), adapter.get_item_at_path.return_value]
    assert view._selected_light_type() == ""
    assert view._selected_light_type() == "SphereLight"
    assert adapter.get_item_at_path.call_count == 2


def test_selection_path_and_adapter_identity_are_cache_keys():
    view, adapter, _item, paths = make_view()
    assert view._selected_light_type() == ""
    paths[:] = ["/World/Light"]
    adapter.get_item_at_path.return_value = SimpleNamespace(light_type="DiskLight")
    assert view._selected_light_type() == "DiskLight"
    assert adapter.get_item_at_path.call_count == 2
    replacement = SimpleNamespace(
        get_item_at_path=Mock(return_value=object()),
        get_type_category=Mock(return_value="Other"),
    )
    view._stage_adapter_provider = lambda: replacement
    assert view._selected_light_type() == ""
    replacement.get_item_at_path.assert_called_once_with("/World/Light")


@pytest.mark.parametrize("self_published", [False, True])
def test_selection_notifications_drop_old_classification(self_published):
    view, adapter, item, paths = make_view()
    assert view._selected_light_type() == ""
    view._pushing_to_bus = False
    view._manipulator_registry = None
    view._transform_model = None
    view._transform_manipulator = None
    view._light_manipulator = None
    view._set_renderer_selection_highlight = Mock()
    view._request_selection_highlight_retry = Mock()
    view._refresh_toolbar_state = Mock()
    view._refresh_hud = Mock()
    item.light_type = "DistantLight"
    if self_published:
        view._apply_self_published_selection(paths)
    else:
        view._on_bus_selection_changed(SimpleNamespace(snapshot=view._bus.get_snapshot()))
    assert view._selected_light_type() == "DistantLight"
    assert adapter.get_item_at_path.call_count == 2


def test_attaching_stage_clears_cache_even_before_model_exists():
    view, adapter, item, _paths = make_view()
    assert view._selected_light_type() == ""
    view._transform_model = None
    item.light_type = "SphereLight"
    view.attach_stage(None, adapter, None)
    assert view._selected_light_type() == "SphereLight"


def test_light_geometry_remains_live_with_cached_classification():
    view, adapter, _item, _paths = make_view("SphereLight")
    assert view._selected_light_geometry()["radius"] == 2.0
    adapter.get_light_shape_attributes.return_value = {"radius": 5.0}
    assert view._selected_light_geometry()["radius"] == 5.0
    assert adapter.get_light_shape_attributes.call_count == 2


def make_manipulator(light_type="", previous_type=""):
    return SimpleNamespace(
        _current_type=Mock(return_value=light_type),
        _current_geometry=Mock(return_value=(1.0, 1.0, 1.0)),
        _current_transform=Mock(return_value=list(range(16))),
        _last_light_type=previous_type,
        _last_geometry=(1.0, 1.0, 1.0),
        _last_world_transform=list(range(16)),
        _world_transform=SimpleNamespace(transform=None),
        invalidate=Mock(),
    )


def test_nonlight_refresh_never_queries_geometry_or_world_transform():
    manipulator = make_manipulator()
    for _ in range(100):
        LightManipulator.refresh_transform(manipulator)
    manipulator._current_geometry.assert_not_called()
    manipulator._current_transform.assert_not_called()
    manipulator.invalidate.assert_not_called()


def test_changing_light_to_nonlight_removes_old_geometry_on_rebuild():
    manipulator = make_manipulator(previous_type="RectLight")
    LightManipulator.refresh_transform(manipulator)
    manipulator.invalidate.assert_called_once()
    LightManipulator.on_build(manipulator)
    assert manipulator._world_transform is None
    assert manipulator._last_light_type == ""
    assert manipulator._last_world_transform is None
    manipulator._current_geometry.assert_not_called()
    manipulator._current_transform.assert_not_called()


def test_light_refresh_still_updates_world_transform():
    manipulator = make_manipulator("SphereLight", "SphereLight")
    manipulator._last_world_transform = [0.0] * 16
    LightManipulator.refresh_transform(manipulator)
    assert manipulator._world_transform.transform == list(range(16))
    manipulator._current_geometry.assert_called_once_with("SphereLight")
    manipulator._current_transform.assert_called_once()
