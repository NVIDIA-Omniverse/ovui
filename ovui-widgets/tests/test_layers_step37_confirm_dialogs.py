# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for LAYERS-PLAN Step 37 — confirm-dirty-remove / confirm-reload
dialogs.

Covers:

- :class:`~ovui_widgets.common.undo.CommandCancelled` — raising it from a command's
  :meth:`do` short-circuits :meth:`UndoManager.push` without mutating
  the undo / redo stacks.
- :class:`~ovui_widgets.layers.commands.RemoveSublayerCommand` /
  :class:`~ovui_widgets.layers.commands.ReloadLayerCommand` ``confirm_callback``
  hook — a ``False`` return aborts via ``CommandCancelled``; ``True``
  allows the mutation to run; the hook is only consulted on the first
  ``do`` so redos after undo replay state without re-asking.
- :mod:`ovui_widgets.common.dialogs` — the three helpers
  (:func:`confirm_dialog`, :func:`confirm_dirty_remove_dialog`,
  :func:`confirm_reload_dialog`) fire the right callback on each
  button and on title-bar close; the open-dialog registry keeps the
  window alive until dismissal, removes it on dismissal, and never
  double-fires the cancel path.
- :class:`~ovui_widgets.layers.LayerModel` ``_request_remove_sublayer`` /
  ``_request_reload`` entry points — clean layers skip the dialog,
  dirty layers open the prompt; every button path reaches the
  expected commands (or no commands for Cancel).
"""

from __future__ import annotations

from typing import Any, List

import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import CommandCancelled, UndoManager
from ovui_widgets.layers import LayerModel
from ovui_widgets.layers.commands import (
    ReloadLayerCommand,
    RemoveSublayerCommand,
    SaveLayerCommand,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in — only the two attributes
    the save / remove / reload flows read."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter, app) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


# ─── CommandCancelled + UndoManager.push integration ───────────────────────


class TestCommandCancelled:
    def test_exported_from_undo_module(self) -> None:
        # Sanity: the symbol is re-exported at the package seam the
        # plan prose references (``ovui_widgets.common.undo.CommandCancelled``).
        from ovui_widgets.common.undo import CommandCancelled as Imported

        assert Imported is CommandCancelled

    def test_push_swallows_cancelled_without_undo_entry(self) -> None:
        manager = UndoManager()

        class _Cancelling:
            non_undoable = False

            def do(self) -> None:
                raise CommandCancelled()

            def undo(self) -> None:
                raise AssertionError("undo should not run")

        manager.push(_Cancelling())  # must not raise.
        assert not manager.can_undo()
        assert not manager.can_redo()

    def test_cancel_does_not_clear_redo_stack(self) -> None:
        # A user-cancelled dialog leaves history alone; the redo stack
        # must survive an aborted push so the user can still redo the
        # last action they intentionally undid.
        manager = UndoManager()

        class _Normal:
            non_undoable = False
            ran_do = False
            ran_undo = False

            def do(self) -> None:
                self.ran_do = True

            def undo(self) -> None:
                self.ran_undo = True

            def redo(self) -> None:
                self.ran_do = True

        first = _Normal()
        manager.push(first)
        manager.undo()
        assert manager.can_redo()

        class _Cancelling:
            non_undoable = False

            def do(self) -> None:
                raise CommandCancelled()

            def undo(self) -> None:
                pass

        manager.push(_Cancelling())
        assert manager.can_redo(), "redo stack must survive cancel"

    def test_cancel_inside_group_is_swallowed(self) -> None:
        manager = UndoManager()
        manager.begin_group("test")

        class _Cancelling:
            non_undoable = False

            def do(self) -> None:
                raise CommandCancelled()

            def undo(self) -> None:
                pass

        manager.push(_Cancelling())
        manager.end_group()
        # No commands accumulated → group discarded.
        assert not manager.can_undo()


# ─── RemoveSublayerCommand confirm_callback hook ───────────────────────────


class TestRemoveSublayerConfirmHook:
    def test_confirm_true_proceeds_with_remove(
        self, adapter, app,
    ) -> None:
        seen_ids: List[str] = []
        cmd = RemoveSublayerCommand(
            adapter, app.selection_bus,
            ROOT_LAYER_IDENTIFIER, 0,
            confirm_callback=lambda cid: (seen_ids.append(cid), True)[1],
        )
        app.undo_manager.push(cmd)

        assert seen_ids == ["./child.usda"]
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" not in root.sublayer_identifiers
        assert app.undo_manager.can_undo()

    def test_confirm_false_raises_cancelled_and_discards(
        self, adapter, app,
    ) -> None:
        cmd = RemoveSublayerCommand(
            adapter, app.selection_bus,
            ROOT_LAYER_IDENTIFIER, 0,
            confirm_callback=lambda _cid: False,
        )
        app.undo_manager.push(cmd)

        # The adapter was not mutated and no entry was added to undo.
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" in root.sublayer_identifiers
        assert not app.undo_manager.can_undo()

    def test_confirm_callback_only_runs_on_first_do(
        self, adapter, app,
    ) -> None:
        # Redo after undo must not re-prompt — the first ``do`` made
        # the decision for the command instance.
        calls: List[str] = []

        def _confirm(cid: str) -> bool:
            calls.append(cid)
            return True

        cmd = RemoveSublayerCommand(
            adapter, app.selection_bus,
            ROOT_LAYER_IDENTIFIER, 0,
            confirm_callback=_confirm,
        )
        app.undo_manager.push(cmd)
        app.undo_manager.undo()
        app.undo_manager.redo()

        assert calls == ["./child.usda"]

    def test_no_confirm_callback_behaves_like_before(
        self, adapter, app,
    ) -> None:
        cmd = RemoveSublayerCommand(
            adapter, app.selection_bus,
            ROOT_LAYER_IDENTIFIER, 0,
        )
        app.undo_manager.push(cmd)
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" not in root.sublayer_identifiers


# ─── ReloadLayerCommand confirm_callback hook ──────────────────────────────


class TestReloadLayerConfirmHook:
    def test_confirm_true_proceeds_with_reload(self, adapter, app) -> None:
        adapter.set_dirty("./child.usda", True)

        cmd = ReloadLayerCommand(
            adapter, app.selection_bus, "./child.usda",
            confirm_callback=lambda _cid: True,
        )
        app.undo_manager.push(cmd)

        # Reload clears the dirty bit on the mock adapter.
        assert adapter._layers["./child.usda"].dirty is False

    def test_confirm_false_raises_cancelled(self, adapter, app) -> None:
        adapter.set_dirty("./child.usda", True)

        cmd = ReloadLayerCommand(
            adapter, app.selection_bus, "./child.usda",
            confirm_callback=lambda _cid: False,
        )
        app.undo_manager.push(cmd)

        # Dirty bit untouched because the command cancelled before
        # calling ``reload_layer``.
        assert adapter._layers["./child.usda"].dirty is True

    def test_no_confirm_callback_still_reloads(self, adapter, app) -> None:
        adapter.set_dirty("./child.usda", True)
        cmd = ReloadLayerCommand(
            adapter, app.selection_bus, "./child.usda",
        )
        app.undo_manager.push(cmd)
        assert adapter._layers["./child.usda"].dirty is False


# ─── ovui_widgets.common.dialogs — dialog helper API ────────────────────────────────────


class TestConfirmDialogAPI:
    def test_confirm_click_fires_on_confirm_and_closes(
        self, monkeypatch,
    ) -> None:
        from ovui_widgets.common.dialogs import _OPEN_DIALOGS, confirm_dialog

        confirmed: List[bool] = []
        cancelled: List[bool] = []

        dialog = confirm_dialog(
            title="Proceed?",
            message="Do the thing?",
            on_confirm=lambda: confirmed.append(True),
            on_cancel=lambda: cancelled.append(True),
            confirm_label="Go",
            cancel_label="Stop",
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")

        assert dialog in _OPEN_DIALOGS
        dialog.confirm()

        assert confirmed == [True]
        assert cancelled == []
        assert dialog not in _OPEN_DIALOGS

    def test_cancel_click_fires_on_cancel_and_closes(self) -> None:
        from ovui_widgets.common.dialogs import _OPEN_DIALOGS, confirm_dialog

        confirmed: List[bool] = []
        cancelled: List[bool] = []

        dialog = confirm_dialog(
            title="Proceed?",
            message="Do the thing?",
            on_confirm=lambda: confirmed.append(True),
            on_cancel=lambda: cancelled.append(True),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")

        dialog.cancel()

        assert confirmed == []
        assert cancelled == [True]
        assert dialog not in _OPEN_DIALOGS

    def test_on_cancel_defaults_to_noop(self) -> None:
        from ovui_widgets.common.dialogs import confirm_dialog

        dialog = confirm_dialog(
            title="Proceed?",
            message="Do the thing?",
            on_confirm=lambda: None,
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        # Should not raise — the default no-op cancel kicks in.
        dialog.cancel()

    def test_double_click_does_not_fire_twice(self) -> None:
        from ovui_widgets.common.dialogs import confirm_dialog

        confirmed: List[bool] = []

        dialog = confirm_dialog(
            title="Proceed?",
            message="Do the thing?",
            on_confirm=lambda: confirmed.append(True),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        dialog.confirm()
        dialog.confirm()  # already closed — must be a no-op.
        dialog.cancel()   # ditto.
        assert confirmed == [True]

    def test_registry_keeps_dialog_alive_until_dismiss(self) -> None:
        from ovui_widgets.common.dialogs import _OPEN_DIALOGS, confirm_dialog

        before = list(_OPEN_DIALOGS)
        dialog = confirm_dialog(
            title="Proceed?",
            message="Do the thing?",
            on_confirm=lambda: None,
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        assert dialog in _OPEN_DIALOGS
        # Pre-existing dialogs from other tests remain untouched.
        for prior in before:
            assert prior in _OPEN_DIALOGS
        dialog.cancel()
        assert dialog not in _OPEN_DIALOGS


def _window_error() -> str:
    """Return why ovui cannot create a window here, or "" when it can."""
    import omni.ui as ui

    try:
        window = ui.Window("__probe_step37__", width=10, height=10)
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    window.destroy()
    return ""


_WINDOW_ERROR = _window_error()
_skip_no_window = pytest.mark.skipif(
    bool(_WINDOW_ERROR),
    reason=f"ovui cannot create a window on this machine ({_WINDOW_ERROR})",
)


class TestConfirmDirtyRemoveDialog:
    def test_save_and_remove_click_fires_save_branch(self) -> None:
        from ovui_widgets.common.dialogs import confirm_dirty_remove_dialog

        events: List[str] = []
        dialog = confirm_dirty_remove_dialog(
            layer_name="child.usda",
            on_save_and_remove=lambda: events.append("save"),
            on_remove_without_saving=lambda: events.append("discard"),
            on_cancel=lambda: events.append("cancel"),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        dialog.save_and_remove()
        assert events == ["save"]

    def test_remove_without_saving_fires_discard_branch(self) -> None:
        from ovui_widgets.common.dialogs import confirm_dirty_remove_dialog

        events: List[str] = []
        dialog = confirm_dirty_remove_dialog(
            layer_name="child.usda",
            on_save_and_remove=lambda: events.append("save"),
            on_remove_without_saving=lambda: events.append("discard"),
            on_cancel=lambda: events.append("cancel"),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        dialog.remove_without_saving()
        assert events == ["discard"]

    def test_cancel_fires_cancel_branch(self) -> None:
        from ovui_widgets.common.dialogs import confirm_dirty_remove_dialog

        events: List[str] = []
        dialog = confirm_dirty_remove_dialog(
            layer_name="child.usda",
            on_save_and_remove=lambda: events.append("save"),
            on_remove_without_saving=lambda: events.append("discard"),
            on_cancel=lambda: events.append("cancel"),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        dialog.cancel()
        assert events == ["cancel"]

    def test_only_one_branch_fires(self) -> None:
        from ovui_widgets.common.dialogs import confirm_dirty_remove_dialog

        events: List[str] = []
        dialog = confirm_dirty_remove_dialog(
            layer_name="child.usda",
            on_save_and_remove=lambda: events.append("save"),
            on_remove_without_saving=lambda: events.append("discard"),
            on_cancel=lambda: events.append("cancel"),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        dialog.save_and_remove()
        # Further click handlers are no-ops after first dismissal.
        dialog.remove_without_saving()
        dialog.cancel()
        assert events == ["save"]

    @_skip_no_window
    @pytest.mark.parametrize(
        ("dirty_layer_names", "first_line"),
        [
            (None, "Layer 'A.usda' has unsaved changes."),
            (["A2.usda"], "Layer 'A.usda' contains unsaved changes in: 'A2.usda'."),
            (
                ["A.usda", "A2.usda"],
                "Layer 'A.usda' contains unsaved changes in: 'A.usda', 'A2.usda'.",
            ),
        ],
    )
    def test_message_names_the_layers_with_unsaved_changes(
        self, monkeypatch, dirty_layer_names, first_line,
    ) -> None:
        # Regression: the question also names a nested sublayer with
        # unsaved changes; the text for the removed layer alone stays.
        from ovui_widgets.common import dialogs

        labels: List[str] = []
        real_label = dialogs.ui.Label
        monkeypatch.setattr(
            dialogs.ui,
            "Label",
            lambda text, **kwargs: (labels.append(text), real_label(text, **kwargs))[1],
        )
        dialog = dialogs.confirm_dirty_remove_dialog(
            layer_name="A.usda",
            on_save_and_remove=lambda: None,
            on_remove_without_saving=lambda: None,
            dirty_layer_names=dirty_layer_names,
        )
        # This machine can create a window (``_skip_no_window``), so a
        # dialog that was not built is a software error in the dialog.
        assert dialog is not None, "the Remove Layer dialog was not built"
        dialog.cancel()
        assert labels == [f"{first_line}\nSave before removing?"]


class TestConfirmReloadDialog:
    def test_reload_click_fires_on_reload(self) -> None:
        from ovui_widgets.common.dialogs import confirm_reload_dialog

        events: List[str] = []
        dialog = confirm_reload_dialog(
            layer_name="child.usda",
            on_reload=lambda: events.append("reload"),
            on_cancel=lambda: events.append("cancel"),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        dialog.confirm()
        assert events == ["reload"]

    def test_cancel_click_fires_on_cancel(self) -> None:
        from ovui_widgets.common.dialogs import confirm_reload_dialog

        events: List[str] = []
        dialog = confirm_reload_dialog(
            layer_name="child.usda",
            on_reload=lambda: events.append("reload"),
            on_cancel=lambda: events.append("cancel"),
        )
        if dialog is None:
            pytest.skip("ovui cannot build a window in this environment")
        dialog.cancel()
        assert events == ["cancel"]


# ─── LayerModel._request_remove_sublayer ───────────────────────────────────


class _DialogSpy:
    """Capture dialog construction and expose the simulated clicks.

    Used to monkeypatch ``confirm_dirty_remove_dialog`` /
    ``confirm_reload_dialog`` so tests can drive the user choice
    without a real window.
    """

    def __init__(self) -> None:
        self.calls: List[dict] = []

    def dirty_remove(self, **kwargs: Any):
        self.calls.append({"type": "dirty_remove", **kwargs})
        return kwargs

    def reload(self, **kwargs: Any):
        self.calls.append({"type": "reload", **kwargs})
        return kwargs


class TestRequestRemoveSublayerCleanSkipsDialog:
    def test_clean_layer_pushes_remove_directly(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        pushed: List[Any] = []

        def _fake_dialog(**kwargs):
            pushed.append(("DIALOG_OPENED", kwargs))
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog", _fake_dialog,
        )

        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        # Clean layer — dirty flag is False by default.
        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

        assert any(isinstance(p, RemoveSublayerCommand) for p in pushed)
        assert all(
            not (isinstance(p, tuple) and p[0] == "DIALOG_OPENED")
            for p in pushed
        ), "dialog must not open for a clean layer"
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" not in root.sublayer_identifiers


class TestRequestRemoveSublayerDirtyRoutesThroughDialog:
    def test_dirty_opens_dialog(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        opened: List[dict] = []

        def _fake_dialog(**kwargs):
            opened.append(kwargs)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog", _fake_dialog,
        )

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

        assert len(opened) == 1
        assert opened[0]["layer_name"]
        assert "on_save_and_remove" in opened[0]
        assert "on_remove_without_saving" in opened[0]

        # Nothing pushed yet — the user has not clicked.
        assert not app.undo_manager.can_undo()
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" in root.sublayer_identifiers

    def test_dialog_save_and_remove_saves_then_removes(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        captured: List[dict] = []

        def _fake_dialog(**kwargs):
            captured.append(kwargs)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog", _fake_dialog,
        )

        pushed: List[Any] = []
        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        captured[0]["on_save_and_remove"]()

        # Inside an undo group: SaveLayerCommand (non-undoable) and
        # RemoveSublayerCommand both ran. Dirty cleared, child gone.
        assert any(isinstance(p, SaveLayerCommand) for p in pushed)
        assert any(isinstance(p, RemoveSublayerCommand) for p in pushed)
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" not in root.sublayer_identifiers
        assert adapter._layers["./child.usda"].dirty is False

    def test_dialog_remove_without_saving_removes_dirty_as_is(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        captured: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog",
            lambda **kwargs: (captured.append(kwargs), None)[1],
        )

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        captured[0]["on_remove_without_saving"]()

        # Layer is removed, dirty bit intact on the record (the mock
        # adapter keeps the ``MockLayer`` after remove).
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" not in root.sublayer_identifiers
        assert adapter._layers["./child.usda"].dirty is True

    def test_dialog_cancel_keeps_sublayer(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        captured: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog",
            lambda **kwargs: (captured.append(kwargs), None)[1],
        )

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

        # The dialog's default on_cancel (no argument) is a no-op, so
        # simply not calling any callback is equivalent to cancel for
        # the state-change assertion.
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" in root.sublayer_identifiers
        assert not app.undo_manager.can_undo()

    def test_dirty_nested_sublayer_opens_dialog_with_its_name(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        # Regression: the remove also takes the sublayers of the removed
        # layer out of the stack, so their unsaved changes need the same
        # question.
        adapter.add_sublayer("./child.usda", "./nested.usda", "nested.usda")
        adapter.set_dirty("./nested.usda", True)

        captured: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog",
            lambda **kwargs: (captured.append(kwargs), None)[1],
        )

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

        assert len(captured) == 1
        assert captured[0]["dirty_layer_names"] == ["nested.usda"]
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" in root.sublayer_identifiers

        captured[0]["on_save_and_remove"]()

        assert adapter._layers["./nested.usda"].dirty is False
        assert "./child.usda" not in root.sublayer_identifiers

    def test_save_and_remove_keeps_layer_with_unsaved_nested_layer(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        # An anonymous sublayer has no file to save to. Its changes are
        # still unsaved after Save & Remove, so the layer must stay.
        anonymous_id = adapter.create_sublayer("./child.usda", -1, "")
        adapter.set_dirty(anonymous_id, True)

        captured: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog",
            lambda **kwargs: (captured.append(kwargs), None)[1],
        )
        errors: List[str] = []
        monkeypatch.setattr(
            ErrorReporter, "show_error", lambda message, *_: errors.append(message),
        )

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        captured[0]["on_save_and_remove"]()

        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" in root.sublayer_identifiers
        assert adapter._layers[anonymous_id].dirty is True
        assert len(errors) == 1 and anonymous_id in errors[0]

    def test_remove_moves_authoring_out_of_removed_tree_with_message(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.add_sublayer("./child.usda", "./nested.usda", "nested.usda")
        adapter.set_edit_target("./nested.usda")
        warnings: List[str] = []
        monkeypatch.setattr(
            ErrorReporter, "show_warning", lambda message, *_: warnings.append(message),
        )

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
        assert len(warnings) == 1 and "nested.usda" in warnings[0]

    def test_redo_of_remove_that_moves_authoring_shows_message_again(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        # Undo makes the nested layer the authoring layer again, so the
        # Redo moves it to root again and must tell the user again.
        adapter.add_sublayer("./child.usda", "./nested.usda", "nested.usda")
        adapter.set_edit_target("./nested.usda")
        warnings: List[str] = []
        monkeypatch.setattr(
            ErrorReporter, "show_warning", lambda message, *_: warnings.append(message),
        )
        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

        app.undo_manager.undo()
        assert adapter.get_edit_target_identifier() == "./nested.usda"
        app.undo_manager.redo()

        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
        assert len(warnings) == 2 and warnings[1] == warnings[0]

    def test_missing_parent_no_ops(self, adapter, app, model) -> None:
        # Should not raise.
        model._request_remove_sublayer("@nope@", 0)

    def test_out_of_range_position_no_ops(
        self, adapter, app, model,
    ) -> None:
        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 99)
        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" in root.sublayer_identifiers

    def test_destroyed_model_no_ops(self, adapter, app) -> None:
        m = LayerModel(adapter, services=app)
        m.destroy()
        # Should not raise.
        m._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

    def test_headless_app_none_removes_clean_layer_directly(
        self, adapter,
    ) -> None:
        m = LayerModel(adapter)  # no app → no undo stack
        try:
            m._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
            root = adapter._layers[ROOT_LAYER_IDENTIFIER]
            assert "./child.usda" not in root.sublayer_identifiers
        finally:
            m.destroy()

    def test_headless_app_none_with_dirty_is_silent(
        self, adapter,
    ) -> None:
        adapter.set_dirty("./child.usda", True)
        m = LayerModel(adapter)
        try:
            # No dialog available; must leave the layer alone.
            m._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
            root = adapter._layers[ROOT_LAYER_IDENTIFIER]
            assert "./child.usda" in root.sublayer_identifiers
        finally:
            m.destroy()


# ─── LayerModel._request_reload ────────────────────────────────────────────


class TestRequestReloadCleanSkipsDialog:
    def test_clean_layer_pushes_reload_directly(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        opened: List[Any] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_reload_dialog",
            lambda **kwargs: (opened.append(kwargs), None)[1],
        )

        pushed: List[Any] = []
        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        child_item = model._items_by_id["./child.usda"]
        # Clean layer → no dialog.
        model._request_reload(child_item)

        assert opened == []
        reload_commands = [p for p in pushed if isinstance(p, ReloadLayerCommand)]
        assert reload_commands
        assert reload_commands[0]._reporter is ErrorReporter


class TestRequestReloadDirtyRoutesThroughDialog:
    def test_dirty_opens_dialog(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        opened: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_reload_dialog",
            lambda **kwargs: (opened.append(kwargs), None)[1],
        )

        child_item = model._items_by_id["./child.usda"]
        model._request_reload(child_item)

        assert len(opened) == 1
        assert "on_reload" in opened[0]
        assert adapter._layers["./child.usda"].dirty is True

    def test_dialog_reload_pushes_command(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        captured: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_reload_dialog",
            lambda **kwargs: (captured.append(kwargs), None)[1],
        )

        child_item = model._items_by_id["./child.usda"]
        model._request_reload(child_item)
        captured[0]["on_reload"]()

        assert adapter._layers["./child.usda"].dirty is False

    def test_dialog_cancel_does_not_reload(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_reload_dialog",
            lambda **kwargs: None,
        )

        child_item = model._items_by_id["./child.usda"]
        model._request_reload(child_item)

        # Simply not invoking ``on_reload`` is equivalent to Cancel
        # — the dirty bit must survive.
        assert adapter._layers["./child.usda"].dirty is True

    def test_anonymous_layer_is_silently_ignored(
        self, adapter, app,
    ) -> None:
        # Anonymous layers have no file to reload; the model must
        # skip the gesture rather than crash through the adapter.
        adapter.create_sublayer(
            ROOT_LAYER_IDENTIFIER, position=-1, new_layer_path="",
        )
        m = LayerModel(adapter, services=app)
        try:
            anon_id = next(
                i for i in m._items_by_id if i.startswith("anon:")
            )
            anon = m._items_by_id[anon_id]
            # Should not raise.
            m._request_reload(anon)
        finally:
            m.destroy()

    def test_missing_layer_is_silently_ignored(
        self, adapter, app, model,
    ) -> None:
        # Non-resident identifier — adapter returns None.
        from ovui_widgets.layers.layer_item import LayerItem
        fake_item = LayerItem(adapter, "@ghost@")
        model._request_reload(fake_item)  # must not raise

    def test_destroyed_model_no_ops(self, adapter, app) -> None:
        m = LayerModel(adapter, services=app)
        child_item = m._items_by_id["./child.usda"]
        m.destroy()
        m._request_reload(child_item)

    def test_headless_clean_reload_goes_direct_to_adapter(
        self, adapter,
    ) -> None:
        adapter.set_dirty("./child.usda", True)
        # Clear dirty via reload path on a headless model — must call
        # the adapter directly.
        m = LayerModel(adapter)
        try:
            child_item = m._items_by_id["./child.usda"]
            # Dirty → skipped (no dialog, no undo stack).
            m._request_reload(child_item)
            assert adapter._layers["./child.usda"].dirty is True
            # Clean → direct adapter call.
            adapter._layers["./child.usda"].dirty = False
            adapter.set_dirty("./child.usda", True)  # re-dirty + event
            # Flip back to a clean non-dirty layer and check reload
            # still routes to the adapter even without app.
            adapter._layers["./child.usda"].dirty = False
            m._request_reload(child_item)
            # reload_layer returns False on a non-dirty layer (the
            # mock adapter's contract); the call must not raise.
        finally:
            m.destroy()


# ─── Integration: Save & Remove end-to-end through undo/redo ───────────────


class TestSaveAndRemoveUndoSemantics:
    def test_undo_restores_sublayer_after_save_and_remove(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        adapter.set_dirty("./child.usda", True)

        captured: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog",
            lambda **kwargs: (captured.append(kwargs), None)[1],
        )

        model._request_remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        captured[0]["on_save_and_remove"]()

        root = adapter._layers[ROOT_LAYER_IDENTIFIER]
        assert "./child.usda" not in root.sublayer_identifiers

        # Undo rewinds the group — remove restored, save is
        # non-undoable so the file stays clean on disk.
        app.undo_manager.undo()
        assert "./child.usda" in root.sublayer_identifiers
        assert adapter._layers["./child.usda"].dirty is False
