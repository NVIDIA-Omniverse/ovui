# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 36: PropertyWindow full integration with UsdPropertyAdapter.

Covers: set_stage_adapter wiring, selection-driven adapter creation, and
Application._load_stage plumbing.

All tests skip when pxr (OpenUSD) is not available.
"""

import pytest

try:
    from pxr import Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="pxr (OpenUSD) not available")

from ovui_data_adapters.openusd import UsdPropertyAdapter
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

from ovwidgets.common.undo import UndoManager


def _make_headless_widget():
    from ovwidgets.property.window import PropertyWindow
    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._content = None
    w._window = None
    w._group_collapse_state = {}
    w._bus_sub = None
    w._stage_adapter = None
    w._stage_change_sub = None
    w._undo_manager_ref = None
    w._adapter_factory = None
    return w


class TestSetStageAdapter:

    def test_factory_builds_adapter_on_selection(self):
        """Step 10: set_property_adapter_factory + set_selection drives adapter creation."""
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/Sphere")

        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, ["/Sphere"], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        w.set_property_adapter_factory(lambda paths: prop_adapter)
        w.set_stage_adapter(stage_adapter)
        w.set_selection(["/Sphere"])

        assert w._adapter is prop_adapter

    def test_stores_stage_adapter(self):
        """set_stage_adapter stores stage_adapter on the widget."""
        stage = Usd.Stage.CreateInMemory()
        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, [], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        w.set_property_adapter_factory(lambda paths: prop_adapter)
        w.set_stage_adapter(stage_adapter)

        assert w._stage_adapter is stage_adapter

    def test_subscribes_to_stage_changes(self):
        """set_stage_adapter creates a stage change subscription."""
        stage = Usd.Stage.CreateInMemory()
        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, [], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        w.set_property_adapter_factory(lambda paths: prop_adapter)
        w.set_stage_adapter(stage_adapter)

        assert w._stage_change_sub is not None

    def test_cancels_old_subscription_on_rewire(self):
        """Calling set_stage_adapter a second time cancels the first subscription."""
        stage = Usd.Stage.CreateInMemory()
        stage_adapter = UsdStageAdapter(stage)
        prop1 = UsdPropertyAdapter(stage, [], stage_adapter=stage_adapter)
        prop2 = UsdPropertyAdapter(stage, [], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        w.set_property_adapter_factory(lambda paths: prop1)
        w.set_stage_adapter(stage_adapter)
        first_sub = w._stage_change_sub

        w.set_property_adapter_factory(lambda paths: prop2)
        w.set_stage_adapter(stage_adapter)

        assert w._stage_change_sub is not first_sub


class TestSelectionDrivenAdapter:

    def test_select_prim_shows_properties(self):
        """After set_selection, _adapter has attribute names for the selected prim."""
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        sphere.GetRadiusAttr().Set(2.5)

        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, [], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        # Step 10 factory: builds a fresh UsdPropertyAdapter for each selection.
        w.set_property_adapter_factory(
            lambda paths: UsdPropertyAdapter(stage, paths, stage_adapter=stage_adapter)
        )
        w.set_stage_adapter(stage_adapter)
        w.set_selection(["/Sphere"])

        assert w._adapter is not None
        assert "radius" in w._adapter.get_attribute_names()

    def test_change_selection_updates_adapter(self):
        """Switching selection creates a new adapter with the new prim's attributes."""
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/Sphere")
        UsdGeom.Cube.Define(stage, "/Cube")

        stage_adapter = UsdStageAdapter(stage)

        w = _make_headless_widget()
        w.set_property_adapter_factory(
            lambda paths: UsdPropertyAdapter(stage, paths, stage_adapter=stage_adapter)
        )
        w.set_stage_adapter(stage_adapter)

        w.set_selection(["/Sphere"])
        sphere_names = set(w._adapter.get_attribute_names())

        w.set_selection(["/Cube"])
        cube_names = set(w._adapter.get_attribute_names())

        assert "radius" in sphere_names
        assert "size" in cube_names
        assert sphere_names != cube_names

    def test_clear_selection_gives_empty_adapter(self):
        """Clearing selection creates an adapter with no attribute names."""
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/Sphere")

        stage_adapter = UsdStageAdapter(stage)

        w = _make_headless_widget()
        w.set_property_adapter_factory(
            lambda paths: UsdPropertyAdapter(stage, paths, stage_adapter=stage_adapter)
        )
        w.set_stage_adapter(stage_adapter)
        w.set_selection(["/Sphere"])
        assert len(w._adapter.get_attribute_names()) > 0

        w.set_selection([])
        assert len(w._adapter.get_attribute_names()) == 0


class TestApplicationLoadStage:

    def test_open_stage_wires_property_window(self):
        """Application.open_stage() calls set_stage_adapter on the property window."""
        from ovwidgets.app.application import Application
        from ovwidgets.common.selection import SelectionBus
        from ovwidgets.common.settings import Settings

        app = Application.__new__(Application)
        app._settings = Settings()
        app._undo_manager = UndoManager()
        app._selection_bus = SelectionBus()
        app._pending_callbacks = []
        app._running = False
        app._main_win = None
        app._dockspace = None
        app._status_bar = None
        app._stage_window = None
        app._property_window = _make_headless_widget()
        app._viewport_window = None
        app._layer_window = None
        app._current_stage_sub = None
        app._stage_adapter = None
        app._layer_adapter = None
        app._stage_change_listeners = []
        app._theme_sub = None
        Application._instance = app

        try:
            stage = Usd.Stage.CreateInMemory()
            UsdGeom.Sphere.Define(stage, "/Sphere")
            app.open_stage(stage)

            # Step 10: Application registers the adapter factory before
            # set_stage_adapter. The adapter itself is built lazily inside
            # _create_adapter_for_paths on the next selection event, so the
            # post-open_stage state is: factory + stage adapter present,
            # _adapter still None until selection arrives.
            assert app._property_window._stage_adapter is not None
            assert app._property_window._adapter_factory is not None

            # Driving a selection through the property window calls the
            # factory and produces a real PropertyAdapter.
            app._property_window.set_selection(["/Sphere"])
            assert app._property_window._adapter is not None
        finally:
            Application._instance = None
            SelectionBus._instance = None
