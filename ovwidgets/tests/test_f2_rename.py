# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for F2 rename flow — OvGear Step 69.

Covers the full chain:
  StageWidget.begin_rename_selected() → RenameController.request_rename_f2()
  → delegate set_rename_mode() → StringField commit (Enter/focus-loss)
  → StringField Escape → cancel_rename()

These tests complement test_rename_controller.py (which covers the controller
in isolation) by testing the StageWidget-level wiring and the Escape key
handler added to StageDelegate._build_rename_field().
"""

from unittest.mock import patch

import omni.ui as ui
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_app_singleton():
    from ovwidgets.app.application import Application
    from ovwidgets.common.selection import SelectionBus
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        Application._instance.shutdown()
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    from ovwidgets.app.application import Application
    return Application()


@pytest.fixture
def adapter():
    from ovwidgets.common.testing.mock_stage import MockStageAdapter
    return MockStageAdapter()


@pytest.fixture
def setup(adapter, app):
    """Return (model, delegate, controller, renameable_item)."""
    from ovwidgets.stage.hierarchy_model import HierarchyModel
    from ovwidgets.stage.rename_controller import RenameController
    from ovwidgets.stage.stage_delegate import StageDelegate

    model = HierarchyModel(adapter)
    delegate = StageDelegate()
    ctrl = RenameController(adapter, model, delegate)
    delegate.set_rename_controller(ctrl)

    root = model.get_item_children(None)[0]
    children = model.get_item_children(root)
    renameable = children[0]  # /World/Geometry — can_rename() is True
    return model, delegate, ctrl, renameable


def _build_rename_field_and_capture(delegate, model, item):
    """Build the rename field in a window; return (field, kpf_callback, end_edit_callback).

    Uses patch.object to capture the key-pressed and end-edit callbacks that
    _build_rename_field registers on the StringField. Calling the returned
    callbacks directly is more reliable than calling call_key_pressed_fn /
    end_edit() in the headless adapter.
    """
    kpf_calls = []
    eof_calls = []

    real_set_kpf = ui.StringField.set_key_pressed_fn

    def spy_kpf(self, fn):
        kpf_calls.append(fn)
        real_set_kpf(self, fn)

    created = []
    orig_init = ui.StringField.__init__

    def capturing_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        created.append(self)

    ui.StringField.__init__ = capturing_init
    try:
        with patch.object(ui.StringField, 'set_key_pressed_fn', spy_kpf):
            win = ui.Window("_test_f2_rename", width=400, height=60)
            with win.frame:
                with ui.VStack():
                    delegate._build_rename_field(model, item)
    finally:
        ui.StringField.__init__ = orig_init

    field = created[0] if created else None
    kpf = kpf_calls[0] if kpf_calls else None
    return field, kpf


# ---------------------------------------------------------------------------
# StageWidget.begin_rename_selected()
# ---------------------------------------------------------------------------

class TestBeginRenameSelected:
    def test_f2_triggers_rename_on_selected_item(self, setup):
        model, delegate, ctrl, item = setup
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = model
        sw._rename_controller = ctrl
        model._selected_items = [item]
        sw.begin_rename_selected()
        assert ctrl._active_item is item

    def test_no_selection_is_noop(self, setup):
        model, delegate, ctrl, item = setup
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = model
        sw._rename_controller = ctrl
        model._selected_items = []
        sw.begin_rename_selected()
        assert ctrl._active_item is None

    def test_uses_first_selected_item_only(self, setup):
        model, delegate, ctrl, item_a = setup
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        item_b = children[1]
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = model
        sw._rename_controller = ctrl
        model._selected_items = [item_a, item_b]
        sw.begin_rename_selected()
        assert ctrl._active_item is item_a

    def test_non_renameable_item_not_renamed(self, setup):
        model, delegate, ctrl, _ = setup
        root = model.get_item_children(None)[0]  # /World — can_rename False
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = model
        sw._rename_controller = ctrl
        model._selected_items = [root]
        sw.begin_rename_selected()
        assert ctrl._active_item is None

    def test_none_rename_controller_no_crash(self, setup):
        model, delegate, ctrl, item = setup
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = model
        sw._rename_controller = None
        model._selected_items = [item]
        sw.begin_rename_selected()  # must not raise


# ---------------------------------------------------------------------------
# begin_rename switches to editable field
# ---------------------------------------------------------------------------

class TestBeginRenameMode:
    def test_begin_rename_sets_rename_mode_on_delegate(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        assert item in delegate._rename_items

    def test_begin_rename_sets_active_item(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        assert ctrl._active_item is item

    def test_rename_field_built_when_in_rename_mode(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        field, _ = _build_rename_field_and_capture(delegate, model, item)
        assert field is not None

    def test_rename_field_has_current_name(self, setup, adapter):
        model, delegate, ctrl, item = setup
        current = adapter.get_display_name(item.adapter_item)
        ctrl.request_rename_f2(item)
        field, _ = _build_rename_field_and_capture(delegate, model, item)
        assert field is not None
        assert field.model.get_value_as_string() == current


# ---------------------------------------------------------------------------
# Enter commits rename
# ---------------------------------------------------------------------------

class TestCommitRename:
    def test_commit_new_name_updates_adapter(self, setup, adapter):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        ctrl.commit_rename("ShinyNewName")
        assert adapter.get_display_name(item.adapter_item) == "ShinyNewName"

    def test_commit_ends_rename_mode(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        ctrl.commit_rename("AnotherName")
        assert item not in delegate._rename_items
        assert ctrl._active_item is None

    def test_end_edit_callback_commits(self, setup, adapter):
        """Verify the field's end_edit callback calls commit_rename when fired."""
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)

        end_edit_cbs = []
        real_add_eef = ui.SimpleStringModel.add_end_edit_fn

        def spy_eef(self, fn):
            end_edit_cbs.append((self, fn))
            real_add_eef(self, fn)

        with patch.object(ui.SimpleStringModel, 'add_end_edit_fn', spy_eef):
            win = ui.Window("_test_eef", width=400, height=60)
            with win.frame:
                with ui.VStack():
                    delegate._build_rename_field(model, item)

        assert len(end_edit_cbs) == 1
        field_model, cb = end_edit_cbs[0]
        field_model.set_value("ViaEndEdit")
        cb(field_model)  # simulate end-edit firing
        assert adapter.get_display_name(item.adapter_item) == "ViaEndEdit"

    def test_empty_name_does_not_rename(self, setup, adapter):
        model, delegate, ctrl, item = setup
        original = adapter.get_display_name(item.adapter_item)
        ctrl.request_rename_f2(item)
        ctrl.commit_rename("")
        assert adapter.get_display_name(item.adapter_item) == original

    def test_whitespace_only_does_not_rename(self, setup, adapter):
        model, delegate, ctrl, item = setup
        original = adapter.get_display_name(item.adapter_item)
        ctrl.request_rename_f2(item)
        ctrl.commit_rename("   ")
        assert adapter.get_display_name(item.adapter_item) == original

    def test_same_name_does_not_call_adapter_rename(self, setup, adapter):
        model, delegate, ctrl, item = setup
        original = adapter.get_display_name(item.adapter_item)
        rename_calls = []
        real_rename = adapter.rename
        adapter.rename = lambda i, n: (rename_calls.append(n), real_rename(i, n))[1]
        ctrl.request_rename_f2(item)
        ctrl.commit_rename(original)
        assert rename_calls == []


# ---------------------------------------------------------------------------
# Escape cancels rename
# ---------------------------------------------------------------------------

class TestEscapeCancel:
    def test_escape_key_cancels_rename(self, setup):
        """Escape key handler captured from delegate calls cancel_rename()."""
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        _, kpf = _build_rename_field_and_capture(delegate, model, item)
        assert kpf is not None, "set_key_pressed_fn must be called"
        kpf(256, 0, True)  # simulate Escape pressed
        assert ctrl._active_item is None

    def test_escape_does_not_modify_adapter(self, setup, adapter):
        model, delegate, ctrl, item = setup
        original = adapter.get_display_name(item.adapter_item)
        ctrl.request_rename_f2(item)
        _, kpf = _build_rename_field_and_capture(delegate, model, item)
        assert kpf is not None
        kpf(256, 0, True)  # Escape
        assert adapter.get_display_name(item.adapter_item) == original

    def test_escape_clears_rename_mode_on_delegate(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        _, kpf = _build_rename_field_and_capture(delegate, model, item)
        assert kpf is not None
        kpf(256, 0, True)
        assert item not in delegate._rename_items

    def test_escape_release_does_not_cancel(self, setup):
        """Key-release (pressed=False) must not trigger cancel."""
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        _, kpf = _build_rename_field_and_capture(delegate, model, item)
        assert kpf is not None
        kpf(256, 0, False)  # Escape released
        assert ctrl._active_item is item  # still in rename mode

    def test_other_keys_do_not_cancel(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        _, kpf = _build_rename_field_and_capture(delegate, model, item)
        assert kpf is not None
        for key in [ord('a'), 65, 258, 257]:
            kpf(key, 0, True)
        assert ctrl._active_item is item  # still in rename mode

    def test_set_key_pressed_fn_is_called(self, setup):
        """Verify _build_rename_field calls set_key_pressed_fn on the field."""
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        _, kpf = _build_rename_field_and_capture(delegate, model, item)
        assert kpf is not None

    def test_cancel_with_no_active_rename_is_noop(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.cancel_rename()  # must not raise

    def test_escape_constant_is_256(self):
        from ovwidgets.stage.stage_delegate import _KEY_ESCAPE
        assert _KEY_ESCAPE == 256


# ---------------------------------------------------------------------------
# Rename updates display immediately
# ---------------------------------------------------------------------------

class TestDisplayUpdate:
    def test_commit_updates_name_in_adapter(self, setup, adapter):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        ctrl.commit_rename("Sphere_New")
        assert adapter.get_display_name(item.adapter_item) == "Sphere_New"

    def test_cancel_preserves_original_name(self, setup, adapter):
        model, delegate, ctrl, item = setup
        original = adapter.get_display_name(item.adapter_item)
        ctrl.request_rename_f2(item)
        ctrl.cancel_rename()
        assert adapter.get_display_name(item.adapter_item) == original

    def test_rename_mode_cleared_after_commit(self, setup):
        model, delegate, ctrl, item = setup
        ctrl.request_rename_f2(item)
        assert item in delegate._rename_items
        ctrl.commit_rename("Done")
        assert item not in delegate._rename_items
