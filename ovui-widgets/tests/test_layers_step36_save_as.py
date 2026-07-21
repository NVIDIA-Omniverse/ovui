# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 36 — Save-As file picker.

Covers the full contract:

- :class:`SaveLayerAsCommand` writes the file via
  :meth:`LayerStackAdapter.save_layer_as` (with
  ``replace_in_parent=False``) and then explicitly rewrites every
  parent sublayer reference via
  :meth:`LayerStackAdapter.replace_sublayer`. The split is load-
  bearing for redo — a second ``save_layer_as`` would fail because
  the file now exists.
- Undo restores each captured ``(parent_id, position)`` to the pre-
  save identifier. The file on disk stays (M5 — undoing a save
  would surprise users).
- Redo re-applies the parent swap without rewriting the file.
- :meth:`LayerModel._request_save_as` opens the file dialog via
  :mod:`ovui_widgets.common.file_dialogs` and, on Save, pushes a
  :class:`SaveLayerAsCommand`. On Cancel nothing is pushed.
- :meth:`SaveValueModel.get_value_as_bool` now reports ``True`` for
  dirty anonymous layers (the icon lights so the user has a click
  target for the save-as dialog).
- Per-row right-click routes through save-as even on concrete
  layers so "clone as" is available before the Phase-H context menu
  (Step 38) ships.
"""

from __future__ import annotations

import os
from typing import Any, List

import pytest
from ovui_data_adapters.common import LayerEventType

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerModel
from ovui_widgets.layers.commands import (
    SaveLayerAsCommand,
    SaveLayerCommand,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in — ``undo_manager`` +
    ``selection_bus`` are the only attributes the save-as path reads.
    """

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=True)
    # One concrete child sublayer — matches the Step 34 fixture.
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
    return ad


@pytest.fixture
def adapter_with_anon(adapter) -> MockLayerStackAdapter:
    # Add an anonymous sublayer under root so we have a realistic
    # save-as target (anonymous in-memory → user picks a path).
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, position=-1, new_layer_path="")
    return adapter


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter_with_anon, app) -> LayerModel:
    m = LayerModel(adapter_with_anon, services=app)
    yield m
    m.destroy()


def _anon_identifier(adapter: MockLayerStackAdapter) -> str:
    for ident in adapter.get_layer_stack_identifiers(include_anonymous=True):
        if adapter._layers[ident].anonymous and ident.startswith("anon:"):
            return ident
    raise AssertionError("no anonymous sublayer in fixture")


def _anon_item(model: LayerModel):
    return model._items_by_id[_anon_identifier(model.adapter)]


# ─── SaveLayerAsCommand — file write + parent-reference swap ────────────────


class TestSaveLayerAsCommandWrite:
    def test_do_writes_file_via_adapter(self, adapter_with_anon, app) -> None:
        anon_id = _anon_identifier(adapter_with_anon)
        adapter_with_anon.set_dirty(anon_id, True)

        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./saved.usda",
        )
        cmd.do()

        # File now exists in the mock adapter's layer registry.
        assert "./saved.usda" in adapter_with_anon._layers
        # Exported record is non-anonymous, clean, and writable.
        saved = adapter_with_anon._layers["./saved.usda"]
        assert saved.anonymous is False
        assert saved.dirty is False

    def test_do_swaps_parent_reference_when_requested(
        self, adapter_with_anon, app,
    ) -> None:
        anon_id = _anon_identifier(adapter_with_anon)
        root = adapter_with_anon._layers[ROOT_LAYER_IDENTIFIER]
        assert anon_id in root.sublayer_identifiers

        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./saved.usda", replace_in_parent=True,
        )
        cmd.do()

        # Parent now references the new path, not the anon identifier.
        assert "./saved.usda" in root.sublayer_identifiers
        assert anon_id not in root.sublayer_identifiers

    def test_do_without_replace_in_parent_leaves_parents_alone(
        self, adapter_with_anon, app,
    ) -> None:
        anon_id = _anon_identifier(adapter_with_anon)
        root = adapter_with_anon._layers[ROOT_LAYER_IDENTIFIER]

        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./saved.usda", replace_in_parent=False,
        )
        cmd.do()

        # File was written but parent keeps the anonymous reference.
        assert "./saved.usda" in adapter_with_anon._layers
        assert anon_id in root.sublayer_identifiers
        assert "./saved.usda" not in root.sublayer_identifiers

    def test_failed_save_returns_silently_no_swap(
        self, adapter_with_anon, app,
    ) -> None:
        # Empty path triggers the mock's ``save_layer_as`` failure
        # branch (returns ``None``). The command reports the error
        # and leaves the parent reference alone.
        anon_id = _anon_identifier(adapter_with_anon)
        root = adapter_with_anon._layers[ROOT_LAYER_IDENTIFIER]

        class _Reporter:
            def __init__(self) -> None:
                self.errors: List[str] = []

            def show_error(self, msg: str) -> None:
                self.errors.append(msg)

        reporter = _Reporter()
        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "", replace_in_parent=True,
            error_reporter=reporter,
        )
        cmd.do()

        assert reporter.errors  # surfaced to the user
        assert anon_id in root.sublayer_identifiers


class TestSaveLayerAsCommandUndo:
    def test_undo_restores_parent_reference(
        self, adapter_with_anon, app,
    ) -> None:
        anon_id = _anon_identifier(adapter_with_anon)
        root = adapter_with_anon._layers[ROOT_LAYER_IDENTIFIER]

        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./saved.usda", replace_in_parent=True,
        )
        cmd.do()
        assert "./saved.usda" in root.sublayer_identifiers

        cmd.undo()

        # Parent is back to the pre-save identifier.
        assert anon_id in root.sublayer_identifiers
        assert "./saved.usda" not in root.sublayer_identifiers

    def test_undo_does_not_delete_file(
        self, adapter_with_anon, app,
    ) -> None:
        # M5: undoing a save does NOT remove the file on disk. The
        # user can discard the file through the filesystem if they
        # really want it gone.
        anon_id = _anon_identifier(adapter_with_anon)
        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./saved.usda", replace_in_parent=True,
        )
        cmd.do()
        cmd.undo()
        assert "./saved.usda" in adapter_with_anon._layers

    def test_redo_reapplies_parent_swap_without_rewriting_file(
        self, adapter_with_anon, app,
    ) -> None:
        anon_id = _anon_identifier(adapter_with_anon)
        root = adapter_with_anon._layers[ROOT_LAYER_IDENTIFIER]

        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./saved.usda", replace_in_parent=True,
        )
        cmd.do()
        cmd.undo()

        # Redo must NOT call ``save_layer_as`` a second time — the
        # mock adapter would fail because the path already exists.
        # Instead, the command replays the cached parent swaps.
        cmd.redo()

        assert "./saved.usda" in root.sublayer_identifiers
        assert anon_id not in root.sublayer_identifiers

    def test_undo_without_replace_in_parent_is_noop(
        self, adapter_with_anon, app,
    ) -> None:
        anon_id = _anon_identifier(adapter_with_anon)
        root = adapter_with_anon._layers[ROOT_LAYER_IDENTIFIER]

        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./saved.usda", replace_in_parent=False,
        )
        cmd.do()
        # Parent was never swapped; undo should not touch it.
        cmd.undo()
        assert anon_id in root.sublayer_identifiers


class TestSaveLayerAsCommandMultipleParents:
    def test_captures_every_parent_reference(self, app) -> None:
        # Two parents both reference the same anonymous source layer
        # — USD allows sublayer references to be shared. Save-As
        # with replace_in_parent=True must rewrite every parent, and
        # undo must restore every parent.
        adapter = MockLayerStackAdapter(include_session=True)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./parent_a.usda")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./parent_b.usda")
        adapter.create_sublayer(
            "./parent_a.usda", position=-1, new_layer_path="",
        )
        shared_anon = next(
            lid for lid in adapter._layers
            if lid.startswith("anon:")
        )
        # Also reference it from parent_b.
        adapter._layers["./parent_b.usda"].sublayer_identifiers.append(
            shared_anon
        )

        cmd = SaveLayerAsCommand(
            adapter, app.selection_bus,
            shared_anon, "./shared.usda", replace_in_parent=True,
        )
        cmd.do()

        assert "./shared.usda" in adapter._layers[
            "./parent_a.usda"
        ].sublayer_identifiers
        assert "./shared.usda" in adapter._layers[
            "./parent_b.usda"
        ].sublayer_identifiers

        cmd.undo()
        assert shared_anon in adapter._layers[
            "./parent_a.usda"
        ].sublayer_identifiers
        assert shared_anon in adapter._layers[
            "./parent_b.usda"
        ].sublayer_identifiers


# ─── LayerModel._request_save_as — dialog seam ──────────────────────────────


class TestRequestSaveAs:
    def test_anonymous_click_opens_file_picker(
        self, adapter_with_anon, app, model, monkeypatch,
    ) -> None:
        # Swap out the real dialog for a spy — we only want to
        # verify the model reaches the picker seam. The dialog
        # itself is exercised by its own unit tests.
        calls: List[tuple] = []

        def _fake_dialog(
            title: str,
            default_name: str,
            on_selected,
            on_cancelled=None,
            filter_ext: str = ".usda",
            default_dir=None,
        ):
            calls.append((title, default_name, on_selected, on_cancelled))
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog,
        )

        anon = _anon_item(model)
        adapter_with_anon.set_dirty(anon.identifier, True)
        vm = model.get_item_value_model(anon, 2)
        vm.set_value(True)

        assert len(calls) == 1
        title, default_name, on_selected, _on_cancelled = calls[0]
        assert anon.identifier in title or "untitled" in title.lower()
        assert default_name.endswith(".usda")

    def test_dialog_save_pushes_save_layer_as_command(
        self, adapter_with_anon, app, model,
    ) -> None:
        # Drive the command seam directly (the dialog's ``on_selected``
        # callback is exactly a call to ``_perform_save_as``).
        anon = _anon_item(model)

        pushed: List[Any] = []
        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        model._perform_save_as(
            anon.identifier, "./from_dialog.usda", replace_in_parent=True,
        )

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, SaveLayerAsCommand)
        assert cmd._source_identifier == anon.identifier
        assert cmd._new_path == "./from_dialog.usda"
        assert cmd._replace_in_parent is True
        assert cmd._reporter is ErrorReporter

    def test_dialog_cancel_pushes_nothing(
        self, adapter_with_anon, app, model, monkeypatch,
    ) -> None:
        # Simulate the user hitting Cancel — the dialog layer fires
        # ``on_cancelled`` and the model must not reach the command
        # seam. We emulate by swapping the dialog for one that just
        # invokes the cancel callback synchronously.
        def _cancelling_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw,
        ):
            if on_cancelled is not None:
                on_cancelled()
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _cancelling_dialog,
        )

        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        anon = _anon_item(model)
        adapter_with_anon.set_dirty(anon.identifier, True)
        vm = model.get_item_value_model(anon, 2)
        vm.set_value(True)

        assert pushed == []

    def test_request_save_as_with_no_app_is_noop(
        self, adapter_with_anon,
    ) -> None:
        # Without an Application the model has no undo manager to
        # push through; ``_request_save_as`` must not crash (and
        # must not open a dialog).
        m = LayerModel(adapter_with_anon)
        try:
            anon = m._items_by_id[_anon_identifier(adapter_with_anon)]
            # Should not raise.
            m._request_save_as(anon)
        finally:
            m.destroy()

    def test_request_save_as_on_destroyed_model_is_noop(
        self, adapter_with_anon, app,
    ) -> None:
        m = LayerModel(adapter_with_anon, services=app)
        anon = m._items_by_id[_anon_identifier(adapter_with_anon)]
        m.destroy()

        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)
        # Must not raise even though adapter is detached.
        m._request_save_as(anon)
        assert pushed == []


# ─── SaveValueModel — anonymous dirty layers light the icon ─────────────────


class TestSaveValueModelAnonymous:
    def test_anonymous_dirty_is_saveable(
        self, adapter_with_anon, app, model,
    ) -> None:
        # Step 36 flipped the Step-19 clamp: the icon now lights on
        # dirty anonymous rows because the click has a valid
        # destination (the save-as file picker).
        anon = _anon_item(model)
        vm = model.get_item_value_model(anon, 2)
        assert vm.get_value_as_bool() is False  # clean
        adapter_with_anon.set_dirty(anon.identifier, True)
        assert vm.get_value_as_bool() is True

    def test_anonymous_clean_is_not_saveable(
        self, adapter_with_anon, app, model,
    ) -> None:
        anon = _anon_item(model)
        vm = model.get_item_value_model(anon, 2)
        # Clean anonymous: no dot, no click.
        assert vm.get_value_as_bool() is False

    def test_missing_layer_still_clamped(
        self, adapter_with_anon, app, model,
    ) -> None:
        # Step 36 did not flip missing — the adapter can't resolve
        # a missing layer so neither save nor save-as can run.
        child_id = "./child.usda"
        adapter_with_anon._layers[child_id].missing = True
        adapter_with_anon._layers[child_id].dirty = True
        model._items_by_id[child_id].invalidate_flags()

        vm = model.get_item_value_model(model._items_by_id[child_id], 2)
        assert vm.get_value_as_bool() is False


# ─── Default filename for save-as dialog ────────────────────────────────────


class TestDefaultFilename:
    def test_anonymous_strips_anon_prefix(
        self, adapter_with_anon, app, model,
    ) -> None:
        from ovui_widgets.layers.layer_model import _default_save_as_filename

        anon = _anon_item(model)
        name = _default_save_as_filename(anon)
        assert not name.startswith("anon:")
        assert name.endswith(".usda")

    def test_concrete_keeps_existing_extension(
        self, adapter_with_anon, app, model,
    ) -> None:
        from ovui_widgets.layers.layer_model import _default_save_as_filename

        child = model._items_by_id["./child.usda"]
        name = _default_save_as_filename(child)
        assert name.endswith(".usda")


# ─── End-to-end via UndoManager ─────────────────────────────────────────────


class TestThroughUndoManager:
    def test_push_undo_redo_round_trip(
        self, adapter_with_anon, app, model,
    ) -> None:
        anon = _anon_item(model)
        root = adapter_with_anon._layers[ROOT_LAYER_IDENTIFIER]

        model._perform_save_as(
            anon.identifier, "./round_trip.usda", replace_in_parent=True,
        )

        assert "./round_trip.usda" in root.sublayer_identifiers
        assert app.undo_manager.can_undo() is True

        app.undo_manager.undo()
        assert anon.identifier in root.sublayer_identifiers

        app.undo_manager.redo()
        assert "./round_trip.usda" in root.sublayer_identifiers

    def test_save_as_lands_on_undo_stack(
        self, adapter_with_anon, app, model,
    ) -> None:
        # Unlike ``SaveLayerCommand`` (non_undoable), SaveLayerAs
        # lands on the undo stack — the parent-reference swap is
        # the reversible half we need to protect.
        depth_before = len(app.undo_manager._undo_stack)
        anon = _anon_item(model)

        model._perform_save_as(
            anon.identifier, "./on_stack.usda", replace_in_parent=True,
        )
        assert len(app.undo_manager._undo_stack) == depth_before + 1


# ─── file_dialogs module — save_file_dialog API contract ────────────────────


class TestSaveFileDialogAPI:
    def test_save_path_triggers_on_selected(self) -> None:
        from ovui_widgets.common.file_dialogs import save_file_dialog

        seen: List[str] = []
        dialog = save_file_dialog(
            title="Save as...",
            default_name="untitled.usda",
            on_selected=lambda p: seen.append(p),
        )
        if dialog is None:
            pytest.skip("ovui Window refused to construct in this env")
        selected_path = "/tmp/chosen.usda"
        dialog.set_path(selected_path)
        dialog.confirm()
        assert seen == [os.path.abspath(selected_path)]

    def test_cancel_triggers_on_cancelled(self) -> None:
        from ovui_widgets.common.file_dialogs import save_file_dialog

        cancelled = [False]
        dialog = save_file_dialog(
            title="Save as...",
            default_name="untitled.usda",
            on_selected=lambda p: None,
            on_cancelled=lambda: cancelled.__setitem__(0, True),
        )
        if dialog is None:
            # ovui refused — on_cancelled already fired as part of
            # the fallback branch in ``save_file_dialog``.
            assert cancelled[0] is True
            return
        dialog.cancel()
        assert cancelled[0] is True

    def test_empty_path_treated_as_cancel(self) -> None:
        from ovui_widgets.common.file_dialogs import save_file_dialog

        seen: List[str] = []
        cancelled = [False]
        dialog = save_file_dialog(
            title="Save as...",
            default_name="untitled.usda",
            on_selected=lambda p: seen.append(p),
            on_cancelled=lambda: cancelled.__setitem__(0, True),
        )
        if dialog is None:
            pytest.skip("ovui Window refused to construct in this env")
        dialog.set_path("")
        dialog.confirm()
        assert seen == []  # no selection
        assert cancelled[0] is True

    def test_missing_extension_appends_usda(self) -> None:
        from ovui_widgets.common.file_dialogs import save_file_dialog

        seen: List[str] = []
        dialog = save_file_dialog(
            title="Save as...",
            default_name="x.usda",
            on_selected=lambda p: seen.append(p),
        )
        if dialog is None:
            pytest.skip("ovui Window refused to construct in this env")
        dialog.set_path("/tmp/no_extension")
        dialog.confirm()
        assert seen and seen[0].endswith(".usda")

    def test_existing_usd_extension_preserved(self) -> None:
        from ovui_widgets.common.file_dialogs import save_file_dialog

        seen: List[str] = []
        dialog = save_file_dialog(
            title="Save as...",
            default_name="x.usda",
            on_selected=lambda p: seen.append(p),
        )
        if dialog is None:
            pytest.skip("ovui Window refused to construct in this env")
        dialog.set_path("/tmp/explicit.usdc")
        dialog.confirm()
        assert seen and seen[0].endswith(".usdc")
        assert not seen[0].endswith(".usdc.usda")


# ─── Step-34 regressions — concrete-layer save path unchanged ───────────────


class TestConcreteStillUsesSaveLayerCommand:
    def test_concrete_dirty_click_pushes_save_layer_command(
        self, adapter_with_anon, app, model,
    ) -> None:
        # Step 36 did not touch the concrete path — a dirty
        # concrete layer's click still pushes a plain
        # ``SaveLayerCommand``, not ``SaveLayerAsCommand``.
        adapter_with_anon.set_dirty("./child.usda", True)

        pushed: List[Any] = []
        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        child = model._items_by_id["./child.usda"]
        vm = model.get_item_value_model(child, 2)
        vm.set_value(True)

        assert len(pushed) == 1
        assert isinstance(pushed[0], SaveLayerCommand)
        # Dirty bit cleared through the direct save path.
        assert adapter_with_anon._layers["./child.usda"].dirty is False


# ─── Event-bus round-trip — SUBLAYERS_CHANGED fires on parent swap ──────────


class TestEventsOnSaveAs:
    def test_parent_swap_emits_sublayers_changed(
        self, adapter_with_anon, app,
    ) -> None:
        anon_id = _anon_identifier(adapter_with_anon)
        events: List[Any] = []
        # Hold the subscription so ``__del__`` doesn't cancel it
        # before the test runs.
        sub = adapter_with_anon.subscribe_events(
            lambda e: events.append(e)
        )  # noqa: F841

        cmd = SaveLayerAsCommand(
            adapter_with_anon, app.selection_bus,
            anon_id, "./event_test.usda", replace_in_parent=True,
        )
        cmd.do()

        sublayers_events = [
            e for e in events
            if e.event_type == LayerEventType.SUBLAYERS_CHANGED
        ]
        # At least one SUBLAYERS_CHANGED on the parent that held the
        # anon reference.
        assert sublayers_events
