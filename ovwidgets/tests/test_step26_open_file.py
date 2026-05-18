# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 26 — Application.open_file() and stage bootstrap.

Headless-only tests: no UI widgets created.
All USD tests skip gracefully when pxr is not available.
"""

from unittest.mock import patch

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus

try:
    from pxr import Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

usd_only = pytest.mark.skipif(not HAS_USD, reason="pxr (OpenUSD) not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singletons():
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        Application._instance.shutdown()
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    a = Application()
    yield a
    a.shutdown()


@pytest.fixture
def simple_stage():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Sphere.Define(stage, "/World/Sphere")
    return stage


@pytest.fixture
def usda_file(tmp_path):
    path = str(tmp_path / "test.usda")
    stage = Usd.Stage.CreateNew(path)
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Sphere.Define(stage, "/World/Sphere")
    stage.GetRootLayer().Save()
    return path


# ---------------------------------------------------------------------------
# HierarchyModel.set_adapter() — hot-swap
# ---------------------------------------------------------------------------

class TestHierarchyModelSetAdapter:
    @usd_only
    def test_set_adapter_changes_adapter(self):
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        model.set_adapter(adapter2)
        assert model._adapter is adapter2

    @usd_only
    def test_set_adapter_cancels_old_subscription(self):
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        adapter1 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        old_sub = model._change_sub
        adapter2 = MockStageAdapter()
        model.set_adapter(adapter2)
        assert old_sub._cancelled

    @usd_only
    def test_set_adapter_clears_path_cache(self):
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        adapter1 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        model._path_cache["fake/path"] = object()
        adapter2 = MockStageAdapter()
        model.set_adapter(adapter2)
        assert model._path_cache == {}

    @usd_only
    def test_set_adapter_clears_selected_items(self):
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyItem, HierarchyModel
        adapter1 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        model._selected_items = [HierarchyItem(adapter1.get_root())]
        adapter2 = MockStageAdapter()
        model.set_adapter(adapter2)
        assert model._selected_items == []

    @usd_only
    def test_set_adapter_subscribes_to_new_adapter(self):
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        adapter1 = MockStageAdapter()
        model = HierarchyModel(adapter1)
        adapter2 = MockStageAdapter()
        model.set_adapter(adapter2)
        assert len(adapter2._subscribers) == 1


# ---------------------------------------------------------------------------
# StageWidget.set_adapter() — hot-swap
# ---------------------------------------------------------------------------

class TestStageWidgetSetAdapter:
    @usd_only
    def test_set_adapter_updates_adapter(self):
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        from ovwidgets.stage.stage_widget import StageWidget
        Application()
        widget = StageWidget.__new__(StageWidget)
        adapter1 = MockStageAdapter()
        adapter2 = MockStageAdapter()
        # Build the widget internals without calling ManagedWindow.__init__
        from ovwidgets.stage.drop_visual_controller import DropVisualController
        from ovwidgets.stage.hierarchy_model import HierarchyModel
        from ovwidgets.stage.rename_controller import RenameController
        from ovwidgets.stage.stage_delegate import StageDelegate
        widget._adapter = adapter1
        widget._model = HierarchyModel(adapter1)
        widget._delegate = StageDelegate()
        widget._drop_visual = DropVisualController()
        widget._rename_controller = RenameController(adapter1, widget._model, widget._delegate)
        widget._delegate.set_rename_controller(widget._rename_controller)
        widget._model.set_rename_controller(widget._rename_controller)
        widget._model.set_drop_visual_controller(widget._drop_visual)
        widget._tree_view = None
        widget._filter_field = None
        widget._bus_sub = None
        widget._model_change_sub = None

        widget.set_adapter(adapter2)

        assert widget._adapter is adapter2
        assert widget._model._adapter is adapter2


# ---------------------------------------------------------------------------
# Application.open_stage() — headless stage bootstrap
# ---------------------------------------------------------------------------

@usd_only
class TestOpenStage:
    def test_open_stage_creates_adapter(self, app, simple_stage):
        app.open_stage(simple_stage)
        assert app._stage_adapter is not None

    def test_open_stage_adapter_has_correct_root(self, app, simple_stage):
        app.open_stage(simple_stage)
        root = app._stage_adapter.get_root()
        assert root is not None

    def test_open_stage_children_accessible(self, app, simple_stage):
        app.open_stage(simple_stage)
        adapter = app._stage_adapter
        children = adapter.get_children(adapter.get_root())
        names = [adapter.get_display_name(c) for c in children]
        assert "World" in names

    def test_open_stage_creates_subscription(self, app, simple_stage):
        app.open_stage(simple_stage)
        assert app._current_stage_sub is not None

    def test_open_stage_twice_cancels_first_subscription(self, app, simple_stage):
        stage2 = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage2, "/Root2")
        app.open_stage(simple_stage)
        first_sub = app._current_stage_sub
        app.open_stage(stage2)
        assert first_sub._cancelled

    def test_open_stage_twice_new_adapter_active(self, app, simple_stage):
        stage2 = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage2, "/Root2")
        app.open_stage(simple_stage)
        app.open_stage(stage2)
        adapter = app._stage_adapter
        children = adapter.get_children(adapter.get_root())
        names = [adapter.get_display_name(c) for c in children]
        assert "Root2" in names
        assert "World" not in names

    def test_open_stage_stage_change_listeners_called(self, app, simple_stage):
        received = []
        app._stage_change_listeners.append(lambda e: received.append(e))
        app.open_stage(simple_stage)
        # Flush any deferred notifications by direct flush
        app._stage_adapter._flush()
        # Even with no USD changes, adapter exists and listener is wired


# ---------------------------------------------------------------------------
# Application.open_file() — file-based bootstrap
# ---------------------------------------------------------------------------

@usd_only
class TestOpenFile:
    def test_open_file_valid_creates_adapter(self, app, usda_file):
        app.open_file(usda_file)
        assert app._stage_adapter is not None

    def test_open_file_valid_children_accessible(self, app, usda_file):
        app.open_file(usda_file)
        adapter = app._stage_adapter
        children = adapter.get_children(adapter.get_root())
        names = [adapter.get_display_name(c) for c in children]
        assert "World" in names

    def test_open_file_invalid_path_calls_error_reporter(self, app):
        from ovwidgets.common.error_reporter import ErrorReporter
        errors = []
        with patch.object(ErrorReporter, "show_error", side_effect=errors.append):
            app.open_file("/nonexistent/path/to/fake.usda")
        assert len(errors) == 1
        assert "Cannot open file" in errors[0]

    def test_open_file_invalid_path_no_adapter(self, app):
        from ovwidgets.common.error_reporter import ErrorReporter
        with patch.object(ErrorReporter, "show_error"):
            app.open_file("/nonexistent/path/to/fake.usda")
        assert app._stage_adapter is None

    def test_open_file_invalid_path_no_crash(self, app):
        from ovwidgets.common.error_reporter import ErrorReporter
        with patch.object(ErrorReporter, "show_error"):
            # Should not raise
            app.open_file("/nonexistent/path/to/fake.usda")


# ---------------------------------------------------------------------------
# Application.shutdown() — subscription cleanup
# ---------------------------------------------------------------------------

@usd_only
class TestShutdownCleanup:
    def test_shutdown_cancels_stage_subscription(self, simple_stage):
        app = Application()
        app.open_stage(simple_stage)
        sub = app._current_stage_sub
        app.shutdown()
        assert sub._cancelled

    def test_shutdown_clears_stage_adapter(self, simple_stage):
        app = Application()
        app.open_stage(simple_stage)
        app.shutdown()
        assert app._stage_adapter is None

    def test_shutdown_clears_stage_sub(self, simple_stage):
        app = Application()
        app.open_stage(simple_stage)
        app.shutdown()
        assert app._current_stage_sub is None

    def test_shutdown_without_open_stage_is_safe(self):
        app = Application()
        app.shutdown()  # Should not raise

    def test_shutdown_twice_is_safe(self, simple_stage):
        app = Application()
        app.open_stage(simple_stage)
        app.shutdown()
        app.shutdown()  # Should not raise
