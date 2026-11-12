# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for LAYERS-PLAN Step 35 — Save-All toolbar button.

Covers the contract:

- :class:`SaveAllValueModel` reports ``True`` iff any concrete (non-
  anonymous) layer in the stack is dirty and returns the same filtered
  identifier list through :meth:`get_dirty_identifiers`.
- :meth:`LayerModel._request_save_all` groups one
  :class:`SaveLayerCommand` per dirty layer under a ``"Save All"``
  undo group. Every command is ``non_undoable`` so the group ends
  empty and :meth:`UndoManager.end_group` auto-discards — the undo
  stack does not grow.
- Anonymous layers are excluded from both the badge and the save
  path (Step 36 will route them through save-as).
- The aggregate ``_value_changed`` fires after dirty events so the
  badge / button state tracks live adapter state without a full
  tree rebuild.
- Headless (``app=None``) construction falls back to direct adapter
  calls for each dirty identifier, mirroring the per-row
  :meth:`LayerModel._request_save` fallback.
"""

from __future__ import annotations

import os
from typing import Any, List

import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerModel
from ovui_widgets.layers.commands import (
    SaveLayerAsCommand,
    SaveLayerCommand,
    SetLayerMutenessCommand,
)


class _App:
    """Minimal :class:`Application` stand-in for the Save-All tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_b.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./clean.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./anon")
    ad._layers["./anon"].anonymous = True
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter, app) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


# ─── SaveAllValueModel read surface ──────────────────────────────────


class TestSaveAllModelRead:
    def test_clean_stack_reports_false(self, model) -> None:
        sam = model.get_save_all_model()
        assert sam.get_value_as_bool() is False
        assert sam.get_dirty_identifiers() == []

    def test_any_dirty_reports_true(self, adapter, model) -> None:
        adapter.set_dirty("./child_a.usda", True)
        sam = model.get_save_all_model()
        assert sam.get_value_as_bool() is True
        assert "./child_a.usda" in sam.get_dirty_identifiers()

    def test_multiple_dirty_all_listed(self, adapter, model) -> None:
        adapter.set_dirty("./child_a.usda", True)
        adapter.set_dirty("./child_b.usda", True)
        ids = model.get_save_all_model().get_dirty_identifiers()
        assert set(ids) == {"./child_a.usda", "./child_b.usda"}

    def test_anonymous_dirty_excluded(self, adapter, model) -> None:
        # Anonymous layers have no file path — Save-All can't persist
        # them. Step 36 will swap this branch for save-as routing.
        adapter._layers["./anon"].dirty = True
        sam = model.get_save_all_model()
        # Exclusively anonymous dirty → badge must stay dark.
        assert sam.get_value_as_bool() is False
        assert "./anon" not in sam.get_dirty_identifiers()

    def test_mixed_anonymous_plus_concrete(self, adapter, model) -> None:
        adapter._layers["./anon"].dirty = True
        adapter.set_dirty("./child_a.usda", True)
        sam = model.get_save_all_model()
        assert sam.get_value_as_bool() is True
        ids = sam.get_dirty_identifiers()
        assert "./child_a.usda" in ids
        assert "./anon" not in ids

    def test_detached_adapter_returns_false(self, model) -> None:
        sam = model.get_save_all_model()
        model._adapter = None
        assert sam.get_value_as_bool() is False
        assert sam.get_dirty_identifiers() == []

    def test_model_is_singleton_per_layer_model(self, model) -> None:
        # The window caches this once on the LayerModel; repeated
        # get_save_all_model() calls must return the same instance so
        # the value_changed subscription stays wired after a hypothetical
        # frame rebuild.
        assert model.get_save_all_model() is model.get_save_all_model()


# ─── _request_save_all — grouping + command pipeline ─────────────────


class TestRequestSaveAllCommandPipeline:
    def test_persists_layer_state_once_before_discovering_dirty_layers(
        self,
        adapter,
        app,
        monkeypatch,
        tmp_path,
    ) -> None:
        # The root lists the anonymous ``./anon``, so Save-All asks for its
        # path first. The user answers with a new file.
        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog",
            lambda title, default_name, on_selected, **kw: on_selected(
                str(tmp_path / "anon.usda")
            ),
        )
        events: List[Any] = []
        original_save = adapter.save_layer

        def before_save_all() -> bool:
            events.append(("persist",))
            # The metadata hook dirties the root. Save-All must discover dirty
            # identifiers only after this callback or the new metadata is lost.
            adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
            return True

        def save_layer(identifier: str) -> bool:
            events.append(("save", identifier))
            return original_save(identifier)

        adapter.save_layer = save_layer
        model = LayerModel(
            adapter,
            services=app,
            before_save_all_fn=before_save_all,
        )
        try:
            model._request_save_all()
        finally:
            model.destroy()

        assert events == [
            ("persist",),
            ("save", ROOT_LAYER_IDENTIFIER),
        ]

    def test_failed_layer_state_persistence_aborts_save_all(
        self,
        adapter,
        app,
    ) -> None:
        adapter.set_dirty("./child_a.usda", True)
        saved: List[str] = []
        adapter.save_layer = lambda identifier: saved.append(identifier) or True
        model = LayerModel(
            adapter,
            services=app,
            before_save_all_fn=lambda: False,
        )
        try:
            model._request_save_all()
        finally:
            model.destroy()

        assert saved == []
        assert adapter.is_dirty(adapter.find_layer("./child_a.usda")) is True

    def test_pushes_one_save_command_per_dirty_layer(
        self, adapter, app, model
    ) -> None:
        adapter.set_dirty("./child_a.usda", True)
        adapter.set_dirty("./child_b.usda", True)

        pushed: List[Any] = []
        original_push = app.undo_manager.push

        def _spy(cmd):
            pushed.append(cmd)
            return original_push(cmd)

        app.undo_manager.push = _spy

        model._request_save_all()

        assert len(pushed) == 2
        assert all(isinstance(c, SaveLayerCommand) for c in pushed)
        assert {c._identifier for c in pushed} == {
            "./child_a.usda",
            "./child_b.usda",
        }

    def test_clears_every_dirty_bit(self, adapter, model) -> None:
        adapter.set_dirty("./child_a.usda", True)
        adapter.set_dirty("./child_b.usda", True)

        model._request_save_all()

        assert adapter.is_dirty(adapter.find_layer("./child_a.usda")) is False
        assert adapter.is_dirty(adapter.find_layer("./child_b.usda")) is False

    def test_save_all_does_not_land_on_undo_stack(
        self, adapter, app, model
    ) -> None:
        """Save-All groups N non_undoable commands; the group ends
        empty so :meth:`UndoManager.end_group`'s empty-commands
        short-circuit discards it. Prime the stack with a real
        undoable command first so "empty before, empty after" cannot
        mask a mis-routed append.
        """
        app.undo_manager.push(
            SetLayerMutenessCommand(
                adapter, app.selection_bus, "./child_a.usda", True,
            )
        )
        depth_before = len(app.undo_manager._undo_stack)

        adapter.set_dirty("./child_a.usda", True)
        adapter.set_dirty("./child_b.usda", True)

        model._request_save_all()

        assert len(app.undo_manager._undo_stack) == depth_before

    def test_save_all_preserves_redo_stack(
        self, adapter, app, model
    ) -> None:
        # Because every inner :class:`SaveLayerCommand` is
        # ``non_undoable``, :meth:`UndoManager.push` does not clear
        # redo from inside an open group (clearing happens at the
        # top-level push path). :meth:`end_group` only clears redo
        # when the group actually appended commands — an empty
        # Save-All group does not. Treat this as part of the
        # contract: Save-All runs saves without disrupting the
        # user's redo history, matching "save is not an editing
        # operation" semantics.
        app.undo_manager.push(
            SetLayerMutenessCommand(
                adapter, app.selection_bus, "./child_a.usda", True,
            )
        )
        app.undo_manager.undo()
        assert app.undo_manager.can_redo() is True

        adapter.set_dirty("./child_a.usda", True)
        model._request_save_all()

        assert app.undo_manager.can_redo() is True

    def test_clean_stack_is_noop(self, adapter, app, model) -> None:
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        model._request_save_all()

        assert pushed == []

    def test_only_anonymous_dirty_is_noop(
        self, adapter, app, model
    ) -> None:
        adapter._layers["./anon"].dirty = True
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        model._request_save_all()

        assert pushed == []
        # The anonymous layer is untouched — Step 36 will route it.
        assert adapter.is_dirty(adapter.find_layer("./anon")) is True

    def test_save_all_after_destroy_is_noop(
        self, adapter, app, model
    ) -> None:
        adapter.set_dirty("./child_a.usda", True)
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)
        model.destroy()

        model._request_save_all()  # must not raise

        assert pushed == []

    def test_save_all_after_detach_is_noop(
        self, adapter, app, model
    ) -> None:
        adapter.set_dirty("./child_a.usda", True)
        model._adapter = None
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        model._request_save_all()

        assert pushed == []


# ─── Anonymous sublayers of the saved layers ────────────


class TestSaveAllAnonymousSublayers:
    """A saved file must never refer to an in-memory ``anon:`` layer."""

    @staticmethod
    def _answer_dialogs(monkeypatch, answer) -> List[str]:
        titles: List[str] = []

        def _dialog(title, default_name, on_selected, on_cancelled=None, **kw):
            titles.append(title)
            path = answer(len(titles))
            if path is None:
                on_cancelled()
            else:
                on_selected(path)

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _dialog,
        )
        return titles

    def test_asks_path_for_anonymous_sublayer_before_saving_parent(
        self, adapter, app, model, monkeypatch, tmp_path,
    ) -> None:
        new_path = str(tmp_path / "anon.usda")
        titles = self._answer_dialogs(monkeypatch, lambda n: new_path)
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_dirty("./child_a.usda", True)

        model._request_save_all()

        assert len(titles) == 1
        root = adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        sublayers = adapter.get_sublayer_identifiers(root)
        assert "./anon" not in sublayers
        assert new_path in sublayers
        assert adapter.is_dirty(root) is False
        assert adapter.is_dirty(adapter.find_layer("./child_a.usda")) is False

    def test_cancel_keeps_parent_unsaved_and_reports_it(
        self, adapter, app, model, monkeypatch,
    ) -> None:
        self._answer_dialogs(monkeypatch, lambda n: None)
        warnings: List[str] = []
        monkeypatch.setattr(
            "ovui_widgets.common.error_reporter.ErrorReporter.show_warning",
            lambda message, duration_ms=4000: warnings.append(message),
        )
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_dirty("./child_a.usda", True)

        model._request_save_all()

        root = adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        assert adapter.is_dirty(root) is True
        assert "./anon" in adapter.get_sublayer_identifiers(root)
        # Layers that list no anonymous sublayer are still saved.
        assert adapter.is_dirty(adapter.find_layer("./child_a.usda")) is False
        root_name = adapter.get_display_name(root)
        assert len(warnings) == 1
        assert root_name in warnings[0]
        assert "anonymous sublayer has no file" in warnings[0]

    def test_nested_anonymous_sublayer_is_saved_before_its_parent(
        self, adapter, app, model, monkeypatch, tmp_path,
    ) -> None:
        adapter.add_sublayer("./anon", "./anon_child")
        adapter._layers["./anon_child"].anonymous = True
        self._answer_dialogs(
            monkeypatch, lambda n: str(tmp_path / f"layer{n}.usda"),
        )
        saved_as: List[str] = []
        original_push = app.undo_manager.push

        def _spy(cmd):
            if isinstance(cmd, SaveLayerAsCommand):
                saved_as.append(cmd._source_identifier)
            return original_push(cmd)

        app.undo_manager.push = _spy
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)

        model._request_save_all()

        # The child first, so the parent's new file lists the child's file.
        assert saved_as == ["./anon_child", "./anon"]
        root = adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        assert adapter.is_dirty(root) is False

    def test_failed_child_save_keeps_parents_unsaved_and_reports_cause(
        self, adapter, app, model, monkeypatch, tmp_path,
    ) -> None:
        adapter.add_sublayer("./anon", "./anon_child")
        adapter._layers["./anon_child"].anonymous = True
        titles = self._answer_dialogs(
            monkeypatch, lambda n: str(tmp_path / f"layer{n}.usda"),
        )
        original_save_as = adapter.save_layer_as

        def save_layer_as(identifier, new_path, replace_in_parent):
            if identifier == "./anon_child":
                raise PermissionError("no write permission in the folder")
            return original_save_as(identifier, new_path, replace_in_parent)

        adapter.save_layer_as = save_layer_as
        errors: List[str] = []
        monkeypatch.setattr(
            "ovui_widgets.common.error_reporter.ErrorReporter.show_error",
            lambda message, duration_ms=5000: errors.append(message),
        )
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_dirty("./child_a.usda", True)

        model._request_save_all()

        # No Save-As of the parent: its file would list the child's anon name.
        assert len(titles) == 1
        anon = adapter.find_layer("./anon")
        assert adapter.is_anonymous(anon) is True
        assert adapter.get_sublayer_identifiers(anon) == ["./anon_child"]
        root = adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        assert adapter.is_dirty(root) is True
        assert "./anon" in adapter.get_sublayer_identifiers(root)
        assert adapter.is_dirty(adapter.find_layer("./child_a.usda")) is False
        assert len(errors) == 1
        assert adapter.get_display_name(root) in errors[0]
        assert "no write permission in the folder" in errors[0]


class TestSaveAllSeveralAnonymousSublayers:
    """Each anonymous layer keeps its own edits."""

    @pytest.fixture(autouse=True)
    def _two_anonymous_layers(self, adapter, monkeypatch, tmp_path) -> None:
        # The mock root has no folder, so the dialogs start in the working
        # folder. Both rows show "anonymous", as the USD adapter shows them.
        monkeypatch.chdir(tmp_path)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./anon_b")
        adapter._layers["./anon_b"].anonymous = True
        adapter._layers["./anon"].display_name = "anonymous"
        adapter._layers["./anon_b"].display_name = "anonymous"
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)

    @staticmethod
    def _answer_dialogs(monkeypatch, answer) -> List[dict]:
        dialogs: List[dict] = []

        def _dialog(title, default_name, on_selected, on_cancelled=None, **kw):
            dialogs.append(dict(kw, title=title, default_name=default_name))
            path = answer(dialogs[-1])
            if path is None:
                on_cancelled()
            else:
                on_selected(path)

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _dialog,
        )
        return dialogs

    @staticmethod
    def _record_replace_prompts(monkeypatch) -> List[dict]:
        prompts: List[dict] = []
        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dialog",
            lambda **kw: prompts.append(kw),
        )
        return prompts

    @staticmethod
    def _sublayers_of_root(adapter) -> List[str]:
        return adapter.get_sublayer_identifiers(
            adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        )

    def test_each_layer_has_its_own_question_and_a_free_default_name(
        self, adapter, model, monkeypatch, tmp_path,
    ) -> None:
        (tmp_path / "anonymous.usda").write_text("#usda 1.0\n")
        dialogs = self._answer_dialogs(
            monkeypatch,
            lambda d: os.path.join(d["default_dir"], d["default_name"]),
        )

        model._request_save_all()

        assert [d["title"] for d in dialogs] == [
            "Save All: save anonymous layer 1 of 2 as...",
            "Save All: save anonymous layer 2 of 2 as...",
        ]
        root_name = adapter.get_display_name(
            adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        )
        assert dialogs[0]["message"] == f"Layer: ./anon, sublayer 4 of {root_name}."
        assert dialogs[1]["message"] == f"Layer: ./anon_b, sublayer 5 of {root_name}."
        # The existing file and the file of the first layer are not offered.
        assert [d["default_name"] for d in dialogs] == [
            "anonymous_1.usda",
            "anonymous_2.usda",
        ]
        assert self._sublayers_of_root(adapter)[3:] == [
            str(tmp_path / "anonymous_1.usda"),
            str(tmp_path / "anonymous_2.usda"),
        ]
        assert adapter.is_dirty(adapter.find_layer(ROOT_LAYER_IDENTIFIER)) is False

    def test_file_written_by_this_save_all_is_refused_and_asked_again(
        self, adapter, model, monkeypatch, tmp_path,
    ) -> None:
        first = str(tmp_path / "anonymous.usda")
        answers = iter([first, first, str(tmp_path / "second.usda")])
        dialogs = self._answer_dialogs(monkeypatch, lambda d: next(answers))
        prompts = self._record_replace_prompts(monkeypatch)
        warnings: List[str] = []
        monkeypatch.setattr(
            "ovui_widgets.common.error_reporter.ErrorReporter.show_warning",
            lambda message, duration_ms=4000: warnings.append(message),
        )

        model._request_save_all()

        # No Replace prompt: the file holds the edits of the first layer.
        assert prompts == []
        assert len(warnings) == 1
        assert first in warnings[0]
        assert "Save All saved another anonymous layer to this file" in warnings[0]
        assert [d["title"] for d in dialogs[1:]] == [
            "Save All: save anonymous layer 2 of 2 as...",
        ] * 2
        assert warnings[0] in dialogs[2]["message"]
        assert self._sublayers_of_root(adapter)[3:] == [
            first,
            str(tmp_path / "second.usda"),
        ]
        assert adapter.is_dirty(adapter.find_layer(ROOT_LAYER_IDENTIFIER)) is False

    def test_layer_of_the_open_scene_is_refused(
        self, adapter, model, monkeypatch, tmp_path,
    ) -> None:
        # The file of ``./child_a.usda`` exists, so without the refusal
        # the Replace prompt would offer to write over that layer.
        (tmp_path / "child_a.usda").write_text("#usda 1.0\n")
        answers = iter([
            str(tmp_path / "child_a.usda"),
            str(tmp_path / "one.usda"),
            str(tmp_path / "two.usda"),
        ])
        dialogs = self._answer_dialogs(monkeypatch, lambda d: next(answers))
        prompts = self._record_replace_prompts(monkeypatch)

        model._request_save_all()

        assert prompts == []
        assert len(dialogs) == 3
        assert "the open scene uses this file" in dialogs[1]["message"]
        assert self._sublayers_of_root(adapter)[:1] == ["./child_a.usda"]
        assert self._sublayers_of_root(adapter)[3:] == [
            str(tmp_path / "one.usda"),
            str(tmp_path / "two.usda"),
        ]

    @pytest.mark.parametrize("button", ["on_confirm", "on_cancel"])
    def test_existing_file_is_written_only_after_replace(
        self, adapter, model, monkeypatch, tmp_path, button,
    ) -> None:
        old_file = str(tmp_path / "old.usda")
        (tmp_path / "old.usda").write_text("#usda 1.0\n")
        answers = iter([old_file, str(tmp_path / "two.usda")])
        self._answer_dialogs(monkeypatch, lambda d: next(answers))
        prompts = self._record_replace_prompts(monkeypatch)

        model._request_save_all()

        # Nothing is written while the Replace prompt is open.
        assert len(prompts) == 1
        assert prompts[0]["confirm_label"] == "Replace"
        assert old_file in prompts[0]["message"]
        assert self._sublayers_of_root(adapter)[3:] == ["./anon", "./anon_b"]

        prompts[0][button]()

        root = adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        if button == "on_confirm":
            assert self._sublayers_of_root(adapter)[3:] == [
                old_file,
                str(tmp_path / "two.usda"),
            ]
            assert adapter.is_dirty(root) is False
        else:
            # Cancel asks no more questions and keeps the root unsaved.
            assert self._sublayers_of_root(adapter)[3:] == ["./anon", "./anon_b"]
            assert adapter.is_dirty(root) is True

    def test_error_after_the_write_stops_save_all_with_its_cause(
        self, adapter, model, monkeypatch, tmp_path,
    ) -> None:
        dialogs = self._answer_dialogs(
            monkeypatch, lambda d: str(tmp_path / f"layer{len(dialogs)}.usda"),
        )

        def replace_sublayer(parent_id, position, new_identifier):
            raise RuntimeError(f"Duplicate item {new_identifier!r} not allowed")

        adapter.replace_sublayer = replace_sublayer
        errors: List[str] = []
        monkeypatch.setattr(
            "ovui_widgets.common.error_reporter.ErrorReporter.show_error",
            lambda message, duration_ms=5000: errors.append(message),
        )
        adapter.set_dirty("./child_a.usda", True)

        model._request_save_all()

        assert len(dialogs) == 1
        assert len(errors) == 1
        root = adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        assert f"Save All did not save {adapter.get_display_name(root)}" in errors[0]
        assert "Duplicate item" in errors[0]
        assert adapter.is_dirty(root) is True
        assert adapter.is_dirty(adapter.find_layer("./child_a.usda")) is False


# ─── Value-model write surface ───────────────────────────────────────


class TestSaveAllValueModelWrite:
    def test_set_value_drives_request_save_all(
        self, adapter, app, model
    ) -> None:
        adapter.set_dirty("./child_a.usda", True)
        pushed: List[Any] = []
        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        sam = model.get_save_all_model()
        sam.set_value(True)  # "do it" — value ignored

        assert len(pushed) == 1
        assert pushed[0]._identifier == "./child_a.usda"

    def test_set_value_on_clean_stack_is_noop(
        self, adapter, app, model
    ) -> None:
        # The value-model guard prevents an empty group from opening
        # and closing — otherwise ``end_group`` on an empty commands
        # list still fires no notify, but set_value on a clean stack
        # must be a complete no-op.
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        sam = model.get_save_all_model()
        sam.set_value(True)

        assert pushed == []


# ─── Badge repaint plumbing — _value_changed after dirty events ──────


class TestBadgeRepaint:
    def test_dirty_event_fires_save_all_value_changed(
        self, adapter, model
    ) -> None:
        # Subscribing to the SaveAllValueModel via ovui's native
        # ``subscribe_value_changed_fn`` mirrors the window path, but
        # the fixture is headless — we spy through a sentinel list in
        # a direct attribute override so the test doesn't depend on
        # ovui's Subscription object. ``_value_changed`` is the raw
        # hook we poke from _flush_events.
        sam = model.get_save_all_model()
        calls: List[int] = []
        sam._value_changed = lambda calls=calls: calls.append(1)

        adapter.set_dirty("./child_a.usda", True)

        assert calls, (
            "expected _value_changed to fire after a DIRTY event"
        )

    def test_save_round_trip_repoll_clears_badge(
        self, adapter, model
    ) -> None:
        # After saving, the badge must go dark on the very next
        # read — the _flush_events poke from the Save command's
        # DIRTY_STATE_CHANGED event is what drives this. Without
        # the Step-35 hook the aggregate would only refresh on a
        # full tree rebuild.
        adapter.set_dirty("./child_a.usda", True)
        sam = model.get_save_all_model()
        assert sam.get_value_as_bool() is True

        model._request_save_all()

        assert sam.get_value_as_bool() is False


# ─── Headless fallback — app=None ────────────────────────────────────


class TestWindowToolbar:
    """LayerWindow-level wiring for the Save-All toolbar button."""

    @staticmethod
    def _can_create_window() -> bool:
        import omni.ui as ui
        try:
            w = ui.Window("__probe_step35__", width=10, height=10)
            w.destroy()
            return True
        except Exception:
            return False

    def setup_method(self) -> None:
        if not self._can_create_window():
            pytest.skip(
                "ui.Window creation requires ui.init(); skipping"
            )

    def _build(self, adapter, app):
        from ovui_widgets.layers import LayerWindow

        w = LayerWindow(services=app, adapter=adapter)
        with w._window.frame:
            w._build_ui()
        return w

    def test_toolbar_builds_button_and_badge(self, adapter, app):
        w = self._build(adapter, app)
        try:
            assert w._save_all_button is not None, (
                "expected Save-All button to be constructed during "
                "_build_ui"
            )
            assert w._save_all_badge is not None, (
                "expected Save-All badge Circle to be constructed"
            )
            # Subscription must be live so dirty events repaint the
            # button without a full frame rebuild.
            assert w._save_all_sub is not None
        finally:
            w.destroy()

    def test_toolbar_button_disabled_when_clean(self, adapter, app):
        w = self._build(adapter, app)
        try:
            assert w._save_all_button.enabled is False
        finally:
            w.destroy()

    def test_toolbar_button_enabled_when_dirty(self, adapter, app):
        adapter.set_dirty("./child_a.usda", True)
        w = self._build(adapter, app)
        try:
            assert w._save_all_button.enabled is True
            assert w._save_all_badge.name == "dirty"
        finally:
            w.destroy()

    def test_toolbar_badge_updates_after_dirty_flip(self, adapter, app):
        w = self._build(adapter, app)
        try:
            assert w._save_all_badge.name == ""
            assert w._save_all_button.enabled is False

            adapter.set_dirty("./child_a.usda", True)

            assert w._save_all_badge.name == "dirty"
            assert w._save_all_button.enabled is True
        finally:
            w.destroy()

    def test_toolbar_click_pushes_save_commands(self, adapter, app):
        adapter.set_dirty("./child_a.usda", True)
        adapter.set_dirty("./child_b.usda", True)

        w = self._build(adapter, app)
        try:
            pushed: List[Any] = []
            original_push = app.undo_manager.push
            app.undo_manager.push = lambda cmd: (
                pushed.append(cmd), original_push(cmd)
            )[1]

            w._on_save_all_clicked()

            assert len(pushed) == 2
            assert all(isinstance(c, SaveLayerCommand) for c in pushed)
            # After the save the button re-disables on its own via
            # the value-changed subscription.
            assert w._save_all_button.enabled is False
            assert w._save_all_badge.name == ""
        finally:
            w.destroy()

    def test_destroy_releases_toolbar_subscription(self, adapter, app):
        w = self._build(adapter, app)
        w.destroy()
        # Every toolbar handle must be cleared so a late adapter
        # event can't reach into a torn-down widget.
        assert w._save_all_button is None
        assert w._save_all_badge is None
        assert w._save_all_sub is None


class TestHeadlessFallback:
    def test_save_all_without_app_falls_back_to_adapter(self) -> None:
        ad = MockLayerStackAdapter(include_session=True)
        ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./a.usda")
        ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./b.usda")
        ad.set_dirty("./a.usda", True)
        ad.set_dirty("./b.usda", True)

        model = LayerModel(ad)
        try:
            model._request_save_all()
            assert ad.is_dirty(ad.find_layer("./a.usda")) is False
            assert ad.is_dirty(ad.find_layer("./b.usda")) is False
        finally:
            model.destroy()
