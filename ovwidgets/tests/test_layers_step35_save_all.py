# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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

from typing import Any, List

import pytest

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerModel
from ovwidgets.layers.commands import SaveLayerCommand, SetLayerMutenessCommand


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
        from ovwidgets.layers import LayerWindow

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
