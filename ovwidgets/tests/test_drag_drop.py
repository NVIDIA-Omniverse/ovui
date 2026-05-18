# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Stage Browser drag-and-drop reparent (Steps 21 & 71).

Covers:
- DropVisualController state tracking
- HierarchyModel drag/drop overrides (get_drag_mime_data, drop_accepted, drop)
- MockStageAdapter.reparent / can_reparent edge cases
- Multi-item reparent
- Undo group wrapping in drop() (Step 71)
- StageWidget drop_between_items=True (Step 71)
"""


from ovui_data_adapters.common import ReparentPosition

from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.drop_visual_controller import DropVisualController
from ovwidgets.stage.hierarchy_model import DRAG_MIME, HierarchyItem, HierarchyModel

# ── DropVisualController ──────────────────────────────────────────────────────


class TestDropVisualController:
    def test_initial_state_is_none(self):
        dvc = DropVisualController()
        assert dvc.current_target is None
        assert dvc.current_position == -1

    def test_show_drop_target_sets_state(self):
        dvc = DropVisualController()
        sentinel = object()
        dvc.show_drop_target(sentinel, 0)
        assert dvc.current_target is sentinel
        assert dvc.current_position == 0

    def test_show_drop_target_updates_on_second_call(self):
        dvc = DropVisualController()
        a, b = object(), object()
        dvc.show_drop_target(a, 0)
        dvc.show_drop_target(b, 1)
        assert dvc.current_target is b
        assert dvc.current_position == 1

    def test_clear_resets_target_and_position(self):
        dvc = DropVisualController()
        dvc.show_drop_target(object(), 1)
        dvc.clear()
        assert dvc.current_target is None
        assert dvc.current_position == -1

    def test_clear_is_idempotent(self):
        dvc = DropVisualController()
        dvc.clear()
        dvc.clear()
        assert dvc.current_target is None


# ── HierarchyModel drag/drop overrides ───────────────────────────────────────


class TestHierarchyModelDragDrop:
    def setup_method(self):
        self.adapter = MockStageAdapter()
        self.model = HierarchyModel(self.adapter)
        self.dvc = DropVisualController()
        self.model.set_drop_visual_controller(self.dvc)
        # Populate path_cache by loading children
        root_children = self.model.get_item_children(self.model._root)
        for child in root_children:
            self.model.get_item_children(child)

    def _item(self, path: str) -> HierarchyItem:
        return self.model._path_cache[path]

    def test_get_drag_mime_data_returns_mime_constant(self):
        sphere = self._item("/World/Geometry/Sphere")
        result = self.model.get_drag_mime_data(sphere)
        assert result == DRAG_MIME
        assert result == "application/ovwidgets.stage-item"

    def test_get_drag_mime_data_cancels_rename_timer(self):
        cancelled = []

        class FakeController:
            def cancel_pending_timer(self):
                cancelled.append(True)

        self.model.set_rename_controller(FakeController())
        sphere = self._item("/World/Geometry/Sphere")
        self.model.get_drag_mime_data(sphere)
        assert cancelled == [True]

    def test_drop_accepted_valid_reparent_returns_true(self):
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        assert self.model.drop_accepted(lights, sphere) is True

    def test_drop_accepted_updates_visual_controller(self):
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        self.model.drop_accepted(lights, sphere, drop_location=0)
        assert self.dvc.current_target is lights
        assert self.dvc.current_position == 0

    def test_drop_accepted_self_reparent_returns_false(self):
        sphere = self._item("/World/Geometry/Sphere")
        assert self.model.drop_accepted(sphere, sphere) is False

    def test_drop_accepted_clears_visual_on_invalid(self):
        sphere = self._item("/World/Geometry/Sphere")
        self.dvc.show_drop_target(sphere, 0)
        self.model.drop_accepted(sphere, sphere)
        assert self.dvc.current_target is None

    def test_drop_accepted_non_hierarchy_item_returns_false(self):
        sphere = self._item("/World/Geometry/Sphere")
        assert self.model.drop_accepted(None, sphere) is False
        assert self.model.drop_accepted(sphere, None) is False

    def test_drop_executes_reparent(self):
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        self.model.drop(lights, sphere)
        # After reparent, sphere's adapter_item should be under lights
        sphere_item = self.adapter._find_by_path("/World/Lights/Sphere")
        assert sphere_item is not None

    def test_drop_clears_visual_controller(self):
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        self.dvc.show_drop_target(lights, 0)
        self.model.drop(lights, sphere)
        assert self.dvc.current_target is None

    def test_drop_invalid_reparent_does_not_move(self):
        geometry = self._item("/World/Geometry")
        sphere = self._item("/World/Geometry/Sphere")
        # Cannot reparent geometry INTO sphere (sphere is a descendant of geometry)
        self.model.drop(sphere, geometry)
        # geometry should still be under World
        assert self.adapter._find_by_path("/World/Geometry") is not None


# ── MockStageAdapter reparent edge cases ─────────────────────────────────────


class TestMockStageAdapterReparent:
    def setup_method(self):
        self.adapter = MockStageAdapter()

    def test_reparent_moves_item_to_new_parent(self):
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        lights = self.adapter._find_by_path("/World/Lights")
        self.adapter.reparent([sphere], lights, ReparentPosition.CHILD)
        assert sphere.parent is lights
        assert sphere in lights.children

    def test_reparent_updates_item_path(self):
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        lights = self.adapter._find_by_path("/World/Lights")
        self.adapter.reparent([sphere], lights, ReparentPosition.CHILD)
        assert sphere.path == "/World/Lights/Sphere"

    def test_reparent_removes_from_old_parent(self):
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        geometry = self.adapter._find_by_path("/World/Geometry")
        lights = self.adapter._find_by_path("/World/Lights")
        self.adapter.reparent([sphere], lights, ReparentPosition.CHILD)
        assert sphere not in geometry.children

    def test_reparent_notifies_subscribers(self):
        events = []
        sub = self.adapter.subscribe_changes(lambda e: events.append(e))  # noqa: F841
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        lights = self.adapter._find_by_path("/World/Lights")
        self.adapter.reparent([sphere], lights, ReparentPosition.CHILD)
        assert len(events) == 1
        assert "/World/Lights/Sphere" in events[0].resynced_paths

    def test_can_reparent_returns_false_for_self(self):
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        assert self.adapter.can_reparent([sphere], sphere) is False

    def test_can_reparent_returns_false_for_reparent_into_descendant(self):
        geometry = self.adapter._find_by_path("/World/Geometry")
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        # Trying to reparent geometry INTO sphere (its own descendant)
        assert self.adapter.can_reparent([geometry], sphere) is False

    def test_can_reparent_returns_true_for_valid_move(self):
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        lights = self.adapter._find_by_path("/World/Lights")
        assert self.adapter.can_reparent([sphere], lights) is True

    def test_multi_item_reparent(self):
        sphere = self.adapter._find_by_path("/World/Geometry/Sphere")
        cube = self.adapter._find_by_path("/World/Geometry/Cube")
        lights = self.adapter._find_by_path("/World/Lights")
        self.adapter.reparent([sphere, cube], lights, ReparentPosition.CHILD)
        assert self.adapter._find_by_path("/World/Lights/Sphere") is not None
        assert self.adapter._find_by_path("/World/Lights/Cube") is not None
        assert sphere.parent is lights
        assert cube.parent is lights


# ── Undo group wiring in HierarchyModel.drop() — Step 71 ─────────────────────


class TestUndoGroupWiring:
    def setup_method(self):
        self.adapter = MockStageAdapter()
        self.model = HierarchyModel(self.adapter)
        root_children = self.model.get_item_children(self.model._root)
        for child in root_children:
            self.model.get_item_children(child)

    def _item(self, path: str) -> HierarchyItem:
        return self.model._path_cache[path]

    def test_drop_calls_begin_undo_group(self):
        calls = []
        self.adapter.begin_undo_group = lambda label: calls.append(("begin", label))
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        self.model.drop(lights, sphere)
        assert ("begin", "Reparent") in calls

    def test_drop_calls_end_undo_group(self):
        calls = []
        self.adapter.end_undo_group = lambda: calls.append("end")
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        self.model.drop(lights, sphere)
        assert "end" in calls

    def test_drop_begin_before_reparent_before_end(self):
        order = []
        real_reparent = self.adapter.reparent

        def tracking_reparent(items, parent, pos):
            order.append("reparent")
            real_reparent(items, parent, pos)

        self.adapter.begin_undo_group = lambda label: order.append("begin")
        self.adapter.end_undo_group = lambda: order.append("end")
        self.adapter.reparent = tracking_reparent
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        self.model.drop(lights, sphere)
        assert order == ["begin", "reparent", "end"]

    def test_invalid_drop_does_not_call_undo_group(self):
        calls = []
        self.adapter.begin_undo_group = lambda label: calls.append("begin")
        self.adapter.end_undo_group = lambda: calls.append("end")
        sphere = self._item("/World/Geometry/Sphere")
        geometry = self._item("/World/Geometry")
        # Drop geometry onto its own descendant (sphere) — invalid
        self.model.drop(sphere, geometry)
        assert calls == []

    def test_non_hierarchy_item_drop_does_not_call_undo_group(self):
        calls = []
        self.adapter.begin_undo_group = lambda label: calls.append("begin")
        sphere = self._item("/World/Geometry/Sphere")
        self.model.drop(None, sphere)
        self.model.drop(sphere, None)
        assert calls == []

    def test_undo_group_label_is_reparent(self):
        labels = []
        self.adapter.begin_undo_group = lambda label: labels.append(label)
        sphere = self._item("/World/Geometry/Sphere")
        lights = self._item("/World/Lights")
        self.model.drop(lights, sphere)
        assert labels == ["Reparent"]


# ── StageWidget drop_between_items — Step 71 ─────────────────────────────────


class TestStageWidgetDropBetweenItems:
    def test_tree_view_has_drop_between_items_enabled(self):
        from ovwidgets.stage.stage_widget import StageWidget
        widget = StageWidget.__new__(StageWidget)
        widget._adapter = MockStageAdapter()
        widget._model = HierarchyModel(widget._adapter)
        from ovwidgets.stage.drop_visual_controller import DropVisualController
        from ovwidgets.stage.rename_controller import RenameController
        from ovwidgets.stage.stage_delegate import StageDelegate
        widget._delegate = StageDelegate()
        widget._drop_visual = DropVisualController()
        widget._rename_controller = RenameController(widget._adapter, widget._model, widget._delegate)
        widget._delegate.set_rename_controller(widget._rename_controller)
        widget._model.set_rename_controller(widget._rename_controller)
        widget._model.set_drop_visual_controller(widget._drop_visual)
        widget._tree_view = None
        widget._filter_field = None
        widget._bus_sub = None
        widget._model_change_sub = None
        widget._selection_bus = None
        widget._visible_columns = ["Name", "Type", "Visibility"]
        widget._config = None
        import omni.ui as ui
        win = ui.Window("_test_drop_between", width=400, height=600)
        with win.frame:
            widget.build()
        assert widget._tree_view is not None
        assert widget._tree_view.drop_between_items is True

    def test_drop_executes_reparent_via_model(self):
        adapter = MockStageAdapter()
        model = HierarchyModel(adapter)
        root_children = model.get_item_children(model._root)
        for child in root_children:
            model.get_item_children(child)
        sphere = model._path_cache["/World/Geometry/Sphere"]
        lights = model._path_cache["/World/Lights"]
        model.drop(lights, sphere)
        assert adapter._find_by_path("/World/Lights/Sphere") is not None
        assert adapter._find_by_path("/World/Geometry/Sphere") is None


# ── Content Browser → Viewport drop (Content-Browser Step 40) ────────────────
#
# the content browser implementation step 40 / the content browser behavior — dragging a
# ``.usd`` from the content browser into the viewport opens it as a
# stage. The content browser's drag produces a ``"\n"``-joined URL MIME
# payload (see :meth:`FileBrowserWidget._tree_drag_payload`); Application
# ._on_drop parses it, branches on ``target``, and routes the USD URL
# into :meth:`Application.open_file`. Tests below exercise
# :meth:`Application._on_drop` directly (target routing, multi-URL,
# warning paths) plus :meth:`ViewportWidget._on_drop` (delegation).


class _FakeDropEvent:
    """Minimal stand-in for ovui's :class:`WidgetMouseDropEvent`."""

    def __init__(self, mime_data) -> None:
        self.mime_data = mime_data


class TestApplicationOnDropMultiUrl:
    """:meth:`Application._on_drop` parses ``"\\n"``-joined payloads."""

    def test_single_url_opens_stage(self, headless_app):
        from unittest.mock import MagicMock
        headless_app.open_file = MagicMock()
        headless_app._on_drop(_FakeDropEvent("/tmp/scene.usd"))
        headless_app.open_file.assert_called_once_with("/tmp/scene.usd")

    def test_multi_url_opens_first_usd(self, headless_app):
        from unittest.mock import MagicMock
        headless_app.open_file = MagicMock()
        headless_app._on_drop(
            _FakeDropEvent("/tmp/a.usda\n/tmp/b.usd\n/tmp/c.usdc")
        )
        headless_app.open_file.assert_called_once_with("/tmp/a.usda")

    def test_multi_url_mixed_opens_first_usd_only(self, headless_app):
        """With mixed USD + non-USD URLs, open the first USD; non-USD
        URLs surface their own unsupported-type warning."""
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        payload = "/tmp/image.png\n/tmp/scene.usd\n/tmp/other.jpg"
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeDropEvent(payload))
        headless_app.open_file.assert_called_once_with("/tmp/scene.usd")
        # ``.png`` + ``.jpg`` each get their own warning
        assert mock_show.call_count == 2

    def test_multi_url_second_usd_ignored_v1(self, headless_app):
        """Step 40 v1: remaining USDs in a multi-URL drop are ignored
        (future step adds them as references on the new stage)."""
        from unittest.mock import MagicMock
        headless_app.open_file = MagicMock()
        headless_app._on_drop(
            _FakeDropEvent("/tmp/main.usd\n/tmp/ref1.usd\n/tmp/ref2.usda")
        )
        headless_app.open_file.assert_called_once_with("/tmp/main.usd")

    def test_whitespace_only_segments_filtered(self, headless_app):
        from unittest.mock import MagicMock
        headless_app.open_file = MagicMock()
        headless_app._on_drop(
            _FakeDropEvent("\n  \n/tmp/scene.usd\n\n\t\n")
        )
        headless_app.open_file.assert_called_once_with("/tmp/scene.usd")

    def test_all_whitespace_payload_noop(self, headless_app):
        """A payload that splits into only empty/whitespace segments
        must not fire a warning or open anything."""
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeDropEvent("\n  \n\t\n"))
        headless_app.open_file.assert_not_called()
        mock_show.assert_not_called()

    def test_multi_url_all_unsupported_warns_each(self, headless_app):
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(
                _FakeDropEvent("/tmp/a.png\n/tmp/b.jpg\n/tmp/c.obj")
            )
        headless_app.open_file.assert_not_called()
        assert mock_show.call_count == 3


class TestApplicationOnDropTargetRouting:
    """:meth:`Application._on_drop` branches on the ``target`` arg."""

    def test_viewport_target_opens_stage(self, headless_app):
        """Viewport drop of a USD opens the stage (same as main target)."""
        from unittest.mock import MagicMock
        headless_app.open_file = MagicMock()
        headless_app._on_drop(
            _FakeDropEvent("/tmp/scene.usda"), target="viewport"
        )
        headless_app.open_file.assert_called_once_with("/tmp/scene.usda")

    def test_viewport_target_unsupported_warns(self, headless_app):
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(
                _FakeDropEvent("/tmp/image.png"), target="viewport"
            )
        headless_app.open_file.assert_not_called()
        msg = mock_show.call_args[0][0]
        assert ".png" in msg
        assert mock_show.call_args[1].get("level") == "warning"

    def test_stage_target_logs_stub(self, headless_app, capsys):
        """Stage-window drop v1: log ``Add Reference not yet implemented``
        and fall back to open-as-stage for a USD URL."""
        from unittest.mock import MagicMock
        headless_app.open_file = MagicMock()
        headless_app._on_drop(
            _FakeDropEvent("/tmp/scene.usd"), target="stage"
        )
        captured = capsys.readouterr()
        assert "Add Reference not yet implemented" in captured.out
        headless_app.open_file.assert_called_once_with("/tmp/scene.usd")

    def test_stage_target_unsupported_warns_no_reference_log(
        self, headless_app, capsys,
    ):
        """A non-USD stage drop should still log the "not implemented"
        stub (the user's intent was a reference regardless of extension)
        and surface the unsupported-type warning for the non-USD URL."""
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(
                _FakeDropEvent("/tmp/image.png"), target="stage"
            )
        captured = capsys.readouterr()
        assert "Add Reference not yet implemented" in captured.out
        headless_app.open_file.assert_not_called()
        mock_show.assert_called_once()

    def test_main_target_does_not_log_reference_stub(
        self, headless_app, capsys,
    ):
        from unittest.mock import MagicMock
        headless_app.open_file = MagicMock()
        headless_app._on_drop(
            _FakeDropEvent("/tmp/scene.usd"), target="main"
        )
        captured = capsys.readouterr()
        assert "Add Reference not yet implemented" not in captured.out


class TestApplicationOnDropEdgeCases:
    """Edge cases retained / extended from Step 68 after multi-URL refactor."""

    def test_empty_payload_noop_all_targets(self, headless_app):
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        for target in ("main", "viewport", "stage"):
            with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
                headless_app._on_drop(_FakeDropEvent(""), target=target)
            headless_app.open_file.assert_not_called()
            mock_show.assert_not_called()

    def test_none_payload_noop(self, headless_app):
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(_FakeDropEvent(None), target="viewport")
        headless_app.open_file.assert_not_called()
        mock_show.assert_not_called()

    def test_missing_mime_data_attr_noop(self, headless_app):
        from unittest.mock import MagicMock, patch
        headless_app.open_file = MagicMock()
        with patch("ovwidgets.common.error_reporter.ErrorReporter.show_status") as mock_show:
            headless_app._on_drop(object(), target="viewport")
        headless_app.open_file.assert_not_called()
        mock_show.assert_not_called()


class TestViewportDropDelegation:
    """:meth:`ViewportWidget._on_drop` delegates to the app dispatcher."""

    def test_on_drop_calls_on_drop_fn_callback(self):
        """A viewport drop event must invoke the explicit
        ``on_drop_fn`` callback (Step 11.3 contract). Application
        binds the ``target="viewport"`` argument via lambda at the
        call site so the viewport widget itself stays single-arg."""
        from unittest.mock import MagicMock

        from ovwidgets.viewport.viewport_widget import ViewportWidget

        captured: dict = {}

        def _drop_fn(event):
            captured["event"] = event

        widget = ViewportWidget.__new__(ViewportWidget)
        widget._on_drop_fn = _drop_fn
        evt = _FakeDropEvent("/tmp/scene.usd")
        widget._on_drop(evt)
        assert captured["event"] is evt

    def test_on_drop_noop_when_callback_is_none(self):
        """A viewport constructed without an ``on_drop_fn`` (pure-test
        case) must silently no-op — no AttributeError on the drop."""
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        widget = ViewportWidget.__new__(ViewportWidget)
        widget._on_drop_fn = None
        # Must not raise.
        widget._on_drop(_FakeDropEvent("/tmp/scene.usd"))


class TestApplicationDropHandlerRegistration:
    """:meth:`Application._register_drop_handler` wires stage + main."""

    def test_stage_window_set_drop_fn_wired(self, headless_app):
        """When the stage window exposes ``set_drop_fn``, the app must
        wire a drop shim that routes into :meth:`_on_drop` with
        ``target="stage"``."""
        from unittest.mock import MagicMock
        main_win = MagicMock()
        stage_win_inner = MagicMock()
        stage_win = MagicMock()
        stage_win.window = stage_win_inner
        headless_app._main_win = main_win
        headless_app._stage_window = stage_win
        try:
            headless_app._register_drop_handler()
            main_win.set_drop_fn.assert_called_once()
            stage_win_inner.set_drop_fn.assert_called_once()
            # The stage-window shim must be a one-arg callable that
            # forwards with ``target="stage"``. Call it and verify
            # dispatch.
            shim = stage_win_inner.set_drop_fn.call_args[0][0]
            headless_app._on_drop = MagicMock()
            evt = _FakeDropEvent("/tmp/scene.usd")
            shim(evt)
            headless_app._on_drop.assert_called_once_with(evt, target="stage")
        finally:
            # Clear the mocks before the fixture's shutdown runs — the
            # ``_save_layout`` path walks panel windows and tries to
            # read numeric ``position_x`` etc. which raises on a plain
            # MagicMock.
            headless_app._stage_window = None
            headless_app._main_win = None

    def test_stage_window_without_set_drop_fn_graceful(self, headless_app):
        """ovui test builds lack ``set_drop_fn`` — must not raise."""
        from unittest.mock import MagicMock
        stage_win_inner = MagicMock(spec=[])  # spec=[] → no attributes
        stage_win = MagicMock()
        stage_win.window = stage_win_inner
        headless_app._stage_window = stage_win
        headless_app._main_win = None
        try:
            # Must not raise.
            headless_app._register_drop_handler()
        finally:
            headless_app._stage_window = None

    def test_no_stage_window_graceful(self, headless_app):
        headless_app._stage_window = None
        headless_app._main_win = None
        # Must not raise.
        headless_app._register_drop_handler()
