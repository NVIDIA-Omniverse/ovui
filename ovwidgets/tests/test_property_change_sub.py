# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 35: PropertyWindow subscribes to stage changes and rebuilds
when selected prim attributes change.

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


class TestPropertyChangeSubscription:

    def test_attr_change_on_selected_prim_triggers_rebuild(self):
        """Changing an attribute on the selected prim fires _rebuild_content."""
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        sphere.GetRadiusAttr().Set(1.0)

        # No call_later → UsdStageAdapter flushes synchronously via fallback
        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, ["/Sphere"], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        w._selection = ["/Sphere"]

        rebuilds = []
        w._rebuild_content = lambda: rebuilds.append(1)

        w.set_property_adapter_factory(lambda paths: prop_adapter)
        w.set_stage_adapter(stage_adapter)
        baseline = len(rebuilds)

        sphere.GetRadiusAttr().Set(2.0)

        assert len(rebuilds) > baseline

    def test_attr_change_on_unselected_prim_does_not_trigger_rebuild(self):
        """Changing an attribute on a prim NOT in the selection does not rebuild."""
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        cube = UsdGeom.Cube.Define(stage, "/Cube")
        sphere.GetRadiusAttr().Set(1.0)
        cube.GetSizeAttr().Set(2.0)

        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, ["/Sphere"], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        w._selection = ["/Sphere"]

        rebuilds = []
        w._rebuild_content = lambda: rebuilds.append(1)

        w.set_property_adapter_factory(lambda paths: prop_adapter)
        w.set_stage_adapter(stage_adapter)
        baseline = len(rebuilds)

        cube.GetSizeAttr().Set(99.0)

        assert len(rebuilds) == baseline

    def test_undo_of_attr_change_triggers_rebuild(self):
        """Undo of an attribute write re-fires TfNotice → PropertyWindow rebuilds."""
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        sphere.GetRadiusAttr().Set(1.0)

        undo = UndoManager()
        stage_adapter = UsdStageAdapter(stage, undo_manager=undo)
        prop_adapter = UsdPropertyAdapter(
            stage, ["/Sphere"], undo_manager=undo, stage_adapter=stage_adapter
        )

        w = _make_headless_widget()
        w._selection = ["/Sphere"]

        rebuilds = []
        w._rebuild_content = lambda: rebuilds.append(1)

        w.set_property_adapter_factory(lambda paths: prop_adapter)
        w.set_stage_adapter(stage_adapter, undo)

        prop_adapter.begin_edit("radius")
        prop_adapter.set_value("radius", 5.0)
        prop_adapter.end_edit("radius")

        after_edit = len(rebuilds)

        undo.undo()

        assert len(rebuilds) > after_edit

    def test_subscription_cleanup_on_destroy(self):
        """After the stage change subscription is cancelled, changes do not rebuild."""
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        sphere.GetRadiusAttr().Set(1.0)

        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, ["/Sphere"], stage_adapter=stage_adapter)

        w = _make_headless_widget()
        w._selection = ["/Sphere"]

        rebuilds = []
        w._rebuild_content = lambda: rebuilds.append(1)

        w.set_property_adapter_factory(lambda paths: prop_adapter)
        w.set_stage_adapter(stage_adapter)
        assert w._stage_change_sub is not None

        w._stage_change_sub.cancel()
        w._stage_change_sub = None

        baseline = len(rebuilds)
        sphere.GetRadiusAttr().Set(99.0)

        assert len(rebuilds) == baseline
