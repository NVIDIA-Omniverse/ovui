# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for RenameController — inline rename with 500ms delay.

RenameController handles inline rename timing and callbacks.
"""

import pytest

from ovui_widgets.app.application import Application
from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.stage.hierarchy_model import HierarchyModel
from ovui_widgets.stage.rename_controller import RenameController
from ovui_widgets.stage.stage_delegate import StageDelegate


@pytest.fixture(autouse=True)
def reset_app():
    app = Application()
    yield
    app.shutdown()


@pytest.fixture
def adapter():
    return MockStageAdapter()


@pytest.fixture
def model(adapter):
    return HierarchyModel(adapter)


@pytest.fixture
def delegate():
    return StageDelegate()


@pytest.fixture
def controller(adapter, model, delegate):
    return RenameController(adapter, model, delegate)


@pytest.fixture
def renameable_item(model):
    """A non-root HierarchyItem that can_rename returns True for."""
    root = model.get_item_children(None)[0]
    children = model.get_item_children(root)
    return children[0]  # /World/Geometry


class TestRequestRenameOnClick:
    def test_starts_timer_for_renameable_item(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        assert controller._timer is not None

    def test_stores_pending_item(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        assert controller._pending_item is renameable_item

    def test_cancels_previous_timer_on_second_click(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        first_timer = controller._timer
        controller.request_rename_on_click(renameable_item)
        assert first_timer.is_cancelled

    def test_no_timer_for_root_item(self, controller, model):
        root = model.get_item_children(None)[0]  # /World — can_rename = False
        controller.request_rename_on_click(root)
        assert controller._timer is None

    def test_timer_is_callable_handle(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        assert hasattr(controller._timer, "cancel")


class TestRequestRenameF2:
    def test_begins_rename_immediately(self, controller, delegate, renameable_item):
        controller.request_rename_f2(renameable_item)
        assert controller._active_item is renameable_item

    def test_sets_rename_mode_on_delegate(self, controller, delegate, renameable_item):
        controller.request_rename_f2(renameable_item)
        assert renameable_item in delegate._rename_items

    def test_no_rename_for_root_item(self, controller, model):
        root = model.get_item_children(None)[0]
        controller.request_rename_f2(root)
        assert controller._active_item is None

    def test_cancels_any_pending_timer(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        timer = controller._timer
        controller.request_rename_f2(renameable_item)
        assert timer.is_cancelled
        assert controller._timer is None


class TestCommitRename:
    def test_calls_adapter_rename_with_new_name(self, controller, adapter, renameable_item):
        controller.request_rename_f2(renameable_item)
        controller.commit_rename("NewName")
        assert adapter.get_display_name(renameable_item.adapter_item) == "NewName"

    def test_ends_rename_mode(self, controller, delegate, renameable_item):
        controller.request_rename_f2(renameable_item)
        controller.commit_rename("AnotherName")
        assert renameable_item not in delegate._rename_items
        assert controller._active_item is None

    def test_empty_name_does_not_rename(self, controller, adapter, renameable_item):
        original = adapter.get_display_name(renameable_item.adapter_item)
        controller.request_rename_f2(renameable_item)
        controller.commit_rename("")
        assert adapter.get_display_name(renameable_item.adapter_item) == original

    def test_whitespace_only_name_does_not_rename(self, controller, adapter, renameable_item):
        original = adapter.get_display_name(renameable_item.adapter_item)
        controller.request_rename_f2(renameable_item)
        controller.commit_rename("   ")
        assert adapter.get_display_name(renameable_item.adapter_item) == original

    def test_same_name_does_not_call_adapter_rename(self, controller, adapter, renameable_item):
        original = adapter.get_display_name(renameable_item.adapter_item)
        rename_calls = []
        original_rename = adapter.rename

        def tracked_rename(item, name):
            rename_calls.append(name)
            return original_rename(item, name)

        adapter.rename = tracked_rename
        controller.request_rename_f2(renameable_item)
        controller.commit_rename(original)
        assert rename_calls == []

    def test_commit_with_no_active_rename_is_noop(self, controller):
        controller.commit_rename("SomeName")  # No active rename


class TestCancelRename:
    def test_ends_rename_without_changes(self, controller, adapter, renameable_item):
        original = adapter.get_display_name(renameable_item.adapter_item)
        controller.request_rename_f2(renameable_item)
        controller.cancel_rename()
        assert adapter.get_display_name(renameable_item.adapter_item) == original

    def test_clears_rename_mode_on_delegate(self, controller, delegate, renameable_item):
        controller.request_rename_f2(renameable_item)
        controller.cancel_rename()
        assert renameable_item not in delegate._rename_items

    def test_clears_active_item(self, controller, renameable_item):
        controller.request_rename_f2(renameable_item)
        controller.cancel_rename()
        assert controller._active_item is None

    def test_cancel_with_no_active_rename_is_noop(self, controller):
        controller.cancel_rename()  # No active rename


class TestRenameControllerIntegration:
    def test_delegate_rename_mode_toggled_by_begin_and_end(
        self, controller, delegate, renameable_item
    ):
        assert renameable_item not in delegate._rename_items
        controller.request_rename_f2(renameable_item)
        assert renameable_item in delegate._rename_items
        controller.commit_rename("FinalName")
        assert renameable_item not in delegate._rename_items

    def test_cancel_timer_clears_both_timer_and_pending(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        assert controller._timer is not None
        assert controller._pending_item is not None
        controller._cancel_timer()
        assert controller._timer is None
        assert controller._pending_item is None


class TestTimerFires:
    """Verify that the 500ms timer actually fires and triggers rename begin."""

    def test_timer_fires_begins_rename(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        controller._timer._due_time = 0  # force past-due
        Application.instance()._on_frame_update(0.0)
        assert controller._active_item is renameable_item

    def test_timer_fires_sets_rename_mode_on_delegate(
        self, controller, delegate, renameable_item
    ):
        controller.request_rename_on_click(renameable_item)
        controller._timer._due_time = 0
        Application.instance()._on_frame_update(0.0)
        assert renameable_item in delegate._rename_items

    def test_cancelled_timer_does_not_begin_rename(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        controller.cancel_pending_timer()
        # Even if we advance the frame, nothing fires (handle is cancelled)
        Application.instance()._on_frame_update(0.0)
        assert controller._active_item is None

    def test_timer_delay_is_500ms(self, controller, renameable_item):
        import time as _time
        before = _time.monotonic()
        controller.request_rename_on_click(renameable_item)
        delay = controller._timer._due_time - before
        expected = RenameController.RENAME_DELAY_MS / 1000.0
        assert abs(delay - expected) < 0.05  # within 50ms tolerance

    def test_rename_mode_cleared_after_timer_fires_and_commit(
        self, controller, delegate, renameable_item
    ):
        controller.request_rename_on_click(renameable_item)
        controller._timer._due_time = 0
        Application.instance()._on_frame_update(0.0)
        assert renameable_item in delegate._rename_items
        controller.commit_rename("UpdatedName")
        assert renameable_item not in delegate._rename_items


class TestEdgeCases:
    """Edge cases: different items, no-op calls, public cancel API."""

    def test_click_different_item_cancels_first_timer(self, controller, model, renameable_item):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        item_a = children[0]  # /World/Geometry
        item_b = children[1]  # /World/Lights

        controller.request_rename_on_click(item_a)
        first_timer = controller._timer
        controller.request_rename_on_click(item_b)

        assert first_timer.is_cancelled
        assert controller._pending_item is item_b
        assert not controller._timer.is_cancelled

    def test_click_different_item_new_timer_not_cancelled(self, controller, model):
        root = model.get_item_children(None)[0]
        children = model.get_item_children(root)
        controller.request_rename_on_click(children[0])
        controller.request_rename_on_click(children[1])
        assert not controller._timer.is_cancelled

    def test_cancel_pending_timer_public_api(self, controller, renameable_item):
        controller.request_rename_on_click(renameable_item)
        timer = controller._timer
        controller.cancel_pending_timer()
        assert timer.is_cancelled
        assert controller._pending_item is None
        assert controller._timer is None

    def test_cancel_pending_timer_when_no_timer_is_noop(self, controller):
        controller.cancel_pending_timer()  # must not crash

    def test_f2_on_non_renameable_item_no_crash(self, controller, model):
        root = model.get_item_children(None)[0]  # /World — can_rename False
        controller.request_rename_f2(root)
        assert controller._active_item is None

    def test_click_non_renameable_item_no_timer(self, controller, model):
        root = model.get_item_children(None)[0]  # /World — can_rename False
        controller.request_rename_on_click(root)
        assert controller._timer is None
        assert controller._pending_item is None
