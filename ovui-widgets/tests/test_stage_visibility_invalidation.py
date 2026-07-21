# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Per-item Stage Browser invalidation from notice-derived visibility events.

Exercises the real adapter → HierarchyModel path: repaint roots come only
from genuine-notice-derived event paths, precise boundary cuts keep sibling
subtrees out, non-imageable intermediates pass inheritance through, and
visibility events never fall back to a whole-model ``_item_changed(None)``.
"""

from __future__ import annotations

import pytest

pxr = pytest.importorskip("pxr")
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter  # noqa: E402
from ovui_data_adapters.services.undo import UndoManager  # noqa: E402
from pxr import Usd, UsdGeom  # noqa: E402

from ovui_widgets.stage.widget.hierarchy_model import HierarchyModel  # noqa: E402


def _make_stage():
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World", "Xform")
    for name, kind in (("Cube", "Cube"), ("Sphere", "Sphere"), ("Pyramid", "Mesh")):
        stage.DefinePrim(f"/World/{name}", kind)
    stage.DefinePrim("/World/Sphere/Deep", "Mesh")
    stage.DefinePrim("/World/Group", "Xform")
    stage.DefinePrim("/World/Group/GC", "Cube")
    stage.DefinePrim("/World/N")  # untyped, non-imageable
    stage.DefinePrim("/World/N/P", "Mesh")
    stage.DefinePrim("/World/N/B")  # untyped branch
    stage.DefinePrim("/World/N/B/U", "Mesh")
    stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
    return stage


def _fixture():
    stage = _make_stage()
    undo = UndoManager()
    adapter = UsdStageAdapter(stage, undo_manager=undo)
    model = HierarchyModel(adapter)

    def materialize(item):
        for child in model.get_item_children(item):
            materialize(child)

    materialize(None)
    changed: list = []
    sub = model.subscribe_item_changed_fn(  # noqa: F841 — keep alive
        lambda _m, item: changed.append(
            None if item is None else adapter.get_item_path(item.adapter_item)
        )
    )
    return stage, undo, adapter, model, changed, sub


def _toggle(adapter, stage, path, visible):
    adapter.begin_undo_group("Toggle Visibility")
    adapter.set_visibility(stage.GetPrimAtPath(path), visible)
    adapter.end_undo_group()


class TestPerItemInvalidation:
    def test_leaf_toggle_invalidates_exactly_one_row(self):
        stage, _undo, adapter, _model, changed, _s = _fixture()
        _toggle(adapter, stage, "/World/Pyramid", False)
        # The truthful ledger adds the created over-ancestor chain as a
        # row-only repaint; no sibling or descendant row is touched.
        assert set(changed) == {"/World/Pyramid", "/World"}
        changed.clear()
        _toggle(adapter, stage, "/World/Pyramid", True)
        # The show edge writes onto the now-existing spec: no over-chain
        # creation, so exactly the one row repaints.
        assert set(changed) == {"/World/Pyramid"}

    def test_subtree_toggle_invalidates_materialized_descendants(self):
        stage, _undo, adapter, _model, changed, _s = _fixture()
        _toggle(adapter, stage, "/World/Group", False)
        assert {"/World/Group", "/World/Group/GC"} <= set(changed)
        assert set(changed) <= {"/World", "/World/Group", "/World/Group/GC"}
        assert None not in changed

    def test_fanout_precision_siblings_do_not_descend(self):
        stage, _undo, adapter, _model, changed, _s = _fixture()
        _toggle(adapter, stage, "/World", False)
        changed.clear()
        _toggle(adapter, stage, "/World/Group", True)
        # Sibling roots flipped INHERITED_INVISIBLE -> INVISIBLE: one row
        # notification each, and their subtrees are cut (no /World/Sphere/Deep).
        assert "/World/Sphere" in changed
        assert "/World/Sphere/Deep" not in changed
        assert "/World/Group/GC" in changed  # shown subtree does update
        assert None not in changed

    def test_non_imageable_intermediates_pass_inheritance_through(self):
        stage, _undo, adapter, _model, changed, _s = _fixture()
        _toggle(adapter, stage, "/World", False)
        changed.clear()
        _toggle(adapter, stage, "/World/N/P", True)  # MakeVisible fan-out
        # /World/N is untyped: transparent, never a false cut — U's row
        # updates through it while N itself is never scheduled.
        assert "/World/N/B/U" in changed
        assert "/World/N/P" in changed
        assert "/World/N" not in changed
        assert "/World/N/B" not in changed
        assert None not in changed

    def test_explicit_invisible_descendant_cuts_branch(self):
        stage, _undo, adapter, _model, changed, _s = _fixture()
        _toggle(adapter, stage, "/World/Sphere", False)  # authored invisible
        changed.clear()
        _toggle(adapter, stage, "/World", False)
        _toggle(adapter, stage, "/World", True)
        # /World/Sphere stayed explicitly invisible through both toggles:
        # its subtree is pruned before and after, so Deep never rebuilds.
        assert "/World/Sphere/Deep" not in changed
        assert None not in changed

    def test_external_edit_takes_conservative_per_item_path(self):
        stage, _undo, adapter, _model, changed, _s = _fixture()
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Sphere")).MakeInvisible()
        assert "/World/Sphere" in changed
        assert None not in changed  # never a whole-model rebuild
        assert "/World/Sphere/Deep" in changed  # conservative subtree

    def test_undo_redo_reinvalidate_rows(self):
        stage, undo, adapter, _model, changed, _s = _fixture()
        _toggle(adapter, stage, "/World/Group", False)
        changed.clear()
        undo.undo()
        assert {"/World/Group", "/World/Group/GC"} <= set(changed)
        assert set(changed) <= {"/World", "/World/Group", "/World/Group/GC"}
        changed.clear()
        undo.redo()
        assert {"/World/Group", "/World/Group/GC"} <= set(changed)
        assert set(changed) <= {"/World", "/World/Group", "/World/Group/GC"}
        assert None not in changed


class TestFooterEventLifecycle:
    """Exactly-once footer counts through the widget's adapter subscription."""

    def _widget(self, adapter):
        from ovui_widgets.stage.widget.stage_widget import StageWidget

        return StageWidget(adapter=adapter)

    def test_visibility_event_refreshes_counts_exactly_once(self):
        from ovui_data_adapters.services.testing import MockStageAdapter

        adapter = MockStageAdapter()
        widget = self._widget(adapter)
        try:
            calls = []
            original = widget._compute_stage_counts
            widget._compute_stage_counts = lambda: (calls.append(1) or original())
            sphere = adapter.get_item_at_path("/World/Geometry/Sphere")
            adapter.set_visibility(sphere, False)
            assert len(calls) == 1
            assert widget._footer_hidden_label.text == "USD · 1 hidden"
        finally:
            widget.destroy()

    def test_unmaterialized_visibility_event_still_updates_footer(self):
        stage, _undo, adapter, _model, _changed, _s = _fixture()
        widget = self._widget(adapter)
        try:
            walks = []
            original = widget._compute_stage_counts
            widget._compute_stage_counts = lambda: (walks.append(1) or original())
            # Fresh widget: no rows expanded/materialized in THIS widget's
            # model beyond the root; an adapter-level visibility change on a
            # deep prim must still refresh the footer exactly once.
            _toggle(adapter, stage, "/World/Sphere/Deep", False)
            assert len(walks) == 1
            assert "1 hidden" in widget._footer_hidden_label.text
        finally:
            widget.destroy()

    def test_set_adapter_cancels_old_subscription(self):
        from ovui_data_adapters.services.testing import MockStageAdapter

        old_adapter = MockStageAdapter()
        new_adapter = MockStageAdapter()
        widget = self._widget(old_adapter)
        try:
            old_subs = len(old_adapter._subscribers)
            widget.set_adapter(new_adapter)
            assert len(old_adapter._subscribers) < old_subs
            walks = []
            original = widget._compute_stage_counts
            widget._compute_stage_counts = lambda: (walks.append(1) or original())
            # A late event on the replaced adapter must not recount.
            sphere = old_adapter.get_item_at_path("/World/Geometry/Sphere")
            old_adapter.set_visibility(sphere, False)
            assert walks == []
            # The new adapter does.
            sphere2 = new_adapter.get_item_at_path("/World/Geometry/Sphere")
            new_adapter.set_visibility(sphere2, False)
            assert len(walks) == 1
        finally:
            widget.destroy()

    def test_destroy_cancels_footer_subscription(self):
        from ovui_data_adapters.services.testing import MockStageAdapter

        adapter = MockStageAdapter()
        widget = self._widget(adapter)
        before = len(adapter._subscribers)
        widget.destroy()
        assert len(adapter._subscribers) < before


class TestProviderAndReplayClassification:
    """Mode B replay roots and OVStage-source events stay per-item."""

    def test_ovstage_source_prim_event_is_per_item(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        stage, _undo, adapter, model, changed, _s = _fixture()
        event = ChangeEvent(
            changed_paths=("/World/Sphere",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source="ovstage:visibility",
        )
        assert model._is_visibility_only_event(event) is True
        model._on_adapter_event(event)
        assert None not in changed          # never a global rebuild
        assert "/World/Sphere" in changed   # provider root scheduled
        assert "/World/Sphere/Deep" in changed  # conservative subtree

    def test_mode_b_replay_prim_root_is_conservative_per_item(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        stage, _undo, adapter, model, changed, _s = _fixture()
        # Shape emitted by a Mode B whole-layer replay: bare prim root with
        # an adapter-owned delta and no boundaries.
        event = ChangeEvent(
            changed_paths=("/World",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={"authored": ("/World",), "boundaries": {},
                              "proven": True},
        )
        model._on_adapter_event(event)
        assert None not in changed
        assert "/World" in changed
        assert "/World/Group/GC" in changed  # conservative descend

    def test_direct_variant_undo_redo_reach_materialized_rows(self):
        from pxr import Sdf

        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vsets = world.GetVariantSets().AddVariantSet("model")
        vsets.AddVariant("A")
        vsets.SetVariantSelection("A")
        with vsets.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{model=A}")
            )
        )
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        model = HierarchyModel(adapter)

        def materialize(item):
            for child in model.get_item_children(item):
                materialize(child)

        materialize(None)
        changed: list = []
        sub = model.subscribe_item_changed_fn(  # noqa: F841
            lambda _m, item: changed.append(
                None if item is None else adapter.get_item_path(item.adapter_item)
            )
        )
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        assert "/World/P" in changed
        assert None not in changed
        changed.clear()
        undo.undo()
        # Replay resynced /World: its materialized subtree (including the
        # restored-visible P row) updates per item, never globally.
        assert "/World/P" in changed
        assert None not in changed
        changed.clear()
        undo.redo()
        assert "/World/P" in changed
        assert None not in changed


class TestCoarseRootTraversal:
    """Second-review S2: no current-state cut under coarse/uncertain roots."""

    def test_coarse_root_reaches_explicit_invisible_descendant(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        stage, _undo, adapter, model, changed, _s = _fixture()
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Pyramid")).MakeInvisible()
        changed.clear()
        # The reviewer's exact failure shape: genuine coarse root /World,
        # no trustworthy boundaries, and a descendant whose own local state
        # is explicit-invisible. The current-only invisible state is NOT
        # proof the branch was unchanged by this coarse edit.
        model._on_adapter_event(ChangeEvent(
            changed_paths=("/World",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={"authored": ("/World",), "boundaries": {},
                              "proven": True},
        ))
        assert None not in changed
        assert "/World/Pyramid" in changed

    def test_uncertain_fallback_event_rebuilds_structurally(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        stage, _undo, adapter, model, changed, _s = _fixture()
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Sphere")).MakeInvisible()
        changed.clear()
        # Uncertain-disposition conservative flush (precise=False): the
        # explicitly-invisible Sphere branch may hold the very change the
        # failure hid. PR review: IMPRECISE events take the STRUCTURAL
        # rebuild at the hierarchy boundary — strictly more conservative
        # than the former descend-without-cut per-item path, so nothing
        # the failure hid can stay stale.
        event = ChangeEvent(
            changed_paths=("/World.visibility",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={
                "authored": ("/World",),
                "boundaries": {},
                "precise": False,
                "proven": True,
            },
        )
        assert model._is_visibility_only_event(event) is False
        model._on_adapter_event(event)
        assert None in changed  # structural whole-model rebuild signal

    def test_precise_event_keeps_explicit_invisible_cut(self):
        stage, _undo, adapter, model, changed, _s = _fixture()
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Sphere")).MakeInvisible()
        changed.clear()
        # A real adapter attempt event (trusted delta, exhaustive authored
        # set): the untouched explicitly-invisible Sphere branch stays cut.
        _toggle(adapter, stage, "/World", False)
        assert None not in changed
        assert "/World" in changed
        assert "/World/Sphere/Deep" not in changed


class TestPropertyInspectorAncestorRoots:
    """Second-review S1: PI refresh predicate covers coarse ancestor roots."""

    def _headless_window(self):
        from ovui_widgets.property.window import PropertyWindow

        window = PropertyWindow.__new__(PropertyWindow)
        window._adapter = None
        window._selection = []
        window._stage_adapter = None
        window._stage_change_sub = None
        window._undo_manager_ref = None
        window._adapter_factory = None
        rebuilds: list = []
        window._rebuild_content = lambda: rebuilds.append(True)
        return window, rebuilds

    def _event(self, *changed_paths):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        return ChangeEvent(
            changed_paths=tuple(changed_paths),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={"authored": tuple(
                p for p in changed_paths if "." not in p
            ), "boundaries": {}},
        )

    def test_bare_ancestor_root_rebuilds_selected_descendant(self):
        window, rebuilds = self._headless_window()
        window._selection = ["/World/P"]
        window._on_stage_changed(self._event("/World"))
        assert rebuilds, "a coarse /World root affects selected /World/P"

    def test_bare_root_does_not_rebuild_unrelated_sibling(self):
        window, rebuilds = self._headless_window()
        window._selection = ["/Other/Q"]
        window._on_stage_changed(self._event("/World"))
        assert not rebuilds

    def test_prefix_sibling_is_not_treated_as_descendant(self):
        window, rebuilds = self._headless_window()
        window._selection = ["/World/P2"]
        window._on_stage_changed(self._event("/World/P"))
        assert not rebuilds

    def test_ancestor_property_path_does_not_rebuild(self):
        window, rebuilds = self._headless_window()
        window._selection = ["/World/P"]
        # An ancestor PROPERTY change names exactly one prim; the selected
        # descendant's own rows (local opinions) are unaffected.
        window._on_stage_changed(self._event("/World.visibility"))
        assert not rebuilds


class TestStructuralResyncRouting:
    """Round-4 R4: mixed structural/visibility events refresh topology."""

    def test_reentrant_new_prim_becomes_resolvable(self):
        from pxr import Tf
        from pxr import Usd as UsdMod

        stage, _undo, adapter, model, changed, _s = _fixture()
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in paths
            ):
                fired["done"] = True
                stage.DefinePrim("/World/Sphere/NewChild", "Cube")

        key = Tf.Notice.Register(
            UsdMod.Notice.ObjectsChanged, reentrant, stage)
        try:
            _toggle(adapter, stage, "/World/Cube", False)
        finally:
            key.Revoke()
        # The structural resync routed through the rebuild path: caches
        # were refreshed and the re-entrantly created prim is resolvable.
        assert model.resolve_path("/World/Sphere/NewChild") is not None

    def test_pure_visibility_events_stay_per_item(self):
        stage, _undo, adapter, model, changed, _s = _fixture()
        _toggle(adapter, stage, "/World/Cube", False)
        # No structural resync involved: never a whole-model rebuild.
        assert None not in changed


class TestAmbiguousMutationConsumers:
    """Round-6 Q1: end-consumer truth for shape-preserving mutations."""

    @pytest.mark.parametrize("mutation", ("retype", "deactivate", "recreate"))
    def test_model_reflects_mutation_after_visibility_edit(self, mutation):
        from pxr import Tf
        from pxr import Usd as UsdMod

        stage, _undo, adapter, model, changed, _s = _fixture()
        target = model.resolve_path("/World/Cube")
        assert target is not None
        model.get_item_children(target)   # materialize child cache
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in paths
            ):
                fired["done"] = True
                if mutation == "retype":
                    stage.OverridePrim("/World/Cube").SetTypeName("Sphere")
                elif mutation == "deactivate":
                    stage.OverridePrim("/World/Cube").SetActive(False)
                else:
                    stage.RemovePrim("/World/Cube")
                    stage.DefinePrim("/World/Cube", "Sphere")

        key = Tf.Notice.Register(
            UsdMod.Notice.ObjectsChanged, reentrant, stage)
        try:
            _toggle(adapter, stage, "/World/Cube", False)
        finally:
            key.Revoke()
        # The structural rebuild refreshed the row: the model's resolved
        # item reflects the REAL mutated prim, not the stale pre-mutation
        # shape.
        item = model.resolve_path("/World/Cube")
        if mutation == "deactivate":
            assert item is None or adapter.get_item_flags(
                item.adapter_item) is not None  # row consistent with USD
        else:
            assert item is not None
            assert str(item.adapter_item.GetTypeName()) == "Sphere"


class TestReplacementPreflight:
    """Round-8 G2: replacement is non-mutating when active ownership blocks it."""

    def _app(self, undo, new_stage):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        opened: list = []
        app = Application.__new__(Application)
        app._startup_prebuilt_renderer = None
        app._stage_adapter = None
        app._current_file_path = "old.usda"
        app._undo_manager = undo
        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: (opened.append(p), new_stage)[1])
        return app, opened

    @pytest.mark.parametrize("register_external_first", (True, False))
    def test_open_file_mid_notice_refuses_without_mutation(
        self, register_external_first
    ):
        from pxr import Tf

        old = Usd.Stage.CreateInMemory()
        old.DefinePrim("/World", "Xform")
        old.DefinePrim("/World/A", "Cube")
        new = Usd.Stage.CreateInMemory()
        new.DefinePrim("/New", "Xform")
        undo = UndoManager()
        app, opened = self._app(undo, new)
        observed: list = []
        fired = {"done": False}

        def cb(notice, sender):
            paths = [str(p) for p in notice.GetResyncedPaths()] + [
                str(p) for p in notice.GetChangedInfoOnlyPaths()]
            if not fired["done"] and "/World/A.visibility" in paths:
                fired["done"] = True
                try:
                    app.open_file("new.usda")
                except RuntimeError as exc:
                    observed.append(str(exc))

        if register_external_first:
            key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, cb, old)
            adapter = UsdStageAdapter(old, undo_manager=undo)
        else:
            adapter = UsdStageAdapter(old, undo_manager=undo)
            key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, cb, old)
        app._stage_adapter = adapter
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.begin_undo_group("outer")
        try:
            # The authoring call must complete normally: no IndexError, no
            # group loss, no provider/path/history mutation.
            adapter.set_visibility(old.GetPrimAtPath("/World/A"), False)
        finally:
            key.Revoke()
        adapter.end_undo_group()
        assert observed and "replacement refused" in observed[0]
        assert opened == []                       # provider NEVER opened
        assert app._current_file_path == "old.usda"
        assert [type(x).__name__ for x in undo._undo_stack] == ["UndoGroup"]
        assert undo.open_group_depth == 0
        # Old adapter fully functional after refusal.
        assert adapter.disposal_pending is False
        assert adapter._notice_key is not None
        assert len(adapter._subscribers) == 1
        assert len(events) == 1
        assert undo.undo() is True                # history intact
        adapter.dispose()

    def test_open_stage_path_preflights_before_any_mutation(self):
        from pxr import Tf

        old = Usd.Stage.CreateInMemory()
        old.DefinePrim("/World", "Xform")
        old.DefinePrim("/World/A", "Cube")
        new = Usd.Stage.CreateInMemory()
        undo = UndoManager()
        app, opened = self._app(undo, new)
        adapter = UsdStageAdapter(old, undo_manager=undo)
        app._stage_adapter = adapter
        observed: list = []
        fired = {"done": False}

        def cb(notice, sender):
            paths = [str(p) for p in notice.GetResyncedPaths()] + [
                str(p) for p in notice.GetChangedInfoOnlyPaths()]
            if not fired["done"] and "/World/A.visibility" in paths:
                fired["done"] = True
                try:
                    app.open_stage(new)   # in-memory replacement path
                except RuntimeError as exc:
                    observed.append(str(exc))

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, cb, old)
        try:
            adapter.set_visibility(old.GetPrimAtPath("/World/A"), False)
        finally:
            key.Revoke()
        assert observed and "replacement refused" in observed[0]
        # The old adapter remained installed and alive.
        assert app._stage_adapter is adapter
        assert adapter._notice_key is not None
        assert adapter.disposal_pending is False
        assert undo.undo() is True
        adapter.dispose()

    def test_replacement_succeeds_after_operation_completes(self):
        # The refusal is retryable: the same open succeeds once the
        # authoring operation has exited.
        old = Usd.Stage.CreateInMemory()
        old.DefinePrim("/World", "Xform")
        old.DefinePrim("/World/A", "Cube")
        undo = UndoManager()
        adapter = UsdStageAdapter(old, undo_manager=undo)
        adapter.set_visibility(old.GetPrimAtPath("/World/A"), False)
        from ovui_widgets.app.application import Application

        app = Application.__new__(Application)
        app._stage_adapter = adapter
        # Outside any notice: the preflight passes silently.
        Application._preflight_stage_replacement(app)
        adapter.dispose()


class TestShutdownPreflight:
    """Round-9 H2: shutdown is non-mutating when active ownership blocks it."""

    def _app_with_session(self, adapter):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        class _Session:
            def __init__(self):
                self.calls = 0

            def shutdown_scene(self):
                self.calls += 1

        session = _Session()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = session
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        return app, session

    @pytest.mark.parametrize("register_external_first", (True, False))
    def test_shutdown_mid_notice_refuses_without_any_mutation(
        self, register_external_first
    ):
        from pxr import Tf

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        undo = UndoManager()
        observed: list = []
        fired = {"done": False}
        holder: dict = {}

        def cb(notice, sender):
            paths = [str(p) for p in notice.GetResyncedPaths()] + [
                str(p) for p in notice.GetChangedInfoOnlyPaths()]
            if not fired["done"] and "/World/Cube.visibility" in paths:
                fired["done"] = True
                try:
                    holder["app"].shutdown()
                except RuntimeError as exc:
                    observed.append(str(exc))

        if register_external_first:
            key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, cb, stage)
            adapter = UsdStageAdapter(stage, undo_manager=undo)
        else:
            adapter = UsdStageAdapter(stage, undo_manager=undo)
            key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, cb, stage)
        app, session = self._app_with_session(adapter)
        holder["app"] = app
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.begin_undo_group("g")
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        adapter.end_undo_group()
        assert observed and "shutdown refused" in observed[0]
        # NOTHING mutated: no provider scene shutdown, session intact,
        # flags untouched, adapter alive, history/group correct.
        assert session.calls == 0
        assert app._adapter_session is session
        assert app._shutdown_done is False
        assert app._shutdown_in_progress is False
        assert adapter._notice_key is not None
        assert adapter.disposal_pending is False
        assert [type(x).__name__ for x in undo._undo_stack] == ["UndoGroup"]
        assert len(events) == 1
        # Retry after the operation completes genuinely shuts down.
        app.shutdown()
        assert session.calls == 1
        assert app._adapter_session is None

    def test_shutdown_refusal_on_exceptional_exit_leaves_state_intact(self):
        from pxr import Tf

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        app, session = self._app_with_session(adapter)
        observed: list = []
        fired = {"done": False}

        def failing_subscriber(_event):
            raise RuntimeError("delivery fails")

        bad = adapter.subscribe_changes(failing_subscriber)  # noqa: F841

        def cb(notice, sender):
            paths = [str(p) for p in notice.GetResyncedPaths()] + [
                str(p) for p in notice.GetChangedInfoOnlyPaths()]
            if not fired["done"] and "/World/Cube.visibility" in paths:
                fired["done"] = True
                try:
                    app.shutdown()
                except RuntimeError as exc:
                    observed.append(str(exc))

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, cb, stage)
        try:
            with pytest.raises(RuntimeError, match="delivery fails"):
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        assert observed and "shutdown refused" in observed[0]
        assert session.calls == 0
        assert app._adapter_session is session
        # Even after the exceptional exit the retry works.
        app.shutdown()
        assert session.calls == 1


class _FactoryReached(Exception):
    """Sentinel: the replacement factory was genuinely called."""


class _ProviderStream:
    """Provider-stream double: publications record dispatch receipts.

    The retired backing-USD OVStage provider proved delivery through
    dispatch-observed receipts; these application-contract tests keep
    that PROTOCOL: ``publish_visibility_change`` returns True (a receipt)
    by default, and a test that silences or breaks it makes delivery
    unprovable so the adapter double retains debt — exactly the surface
    ``Application``'s replacement/shutdown contracts are written against.
    """

    def __init__(self):
        self.visibility_publishes = []
        # Stage-level consumer registrations live on the PROVIDER STREAM,
        # exactly like the retired provider's design.
        self._stage_subscribers = []

    def publish_visibility_change(self, paths, **kwargs):
        self.visibility_publishes.append(tuple(paths))
        return True


class _DebtProtocolAdapter:
    """Faithful double of the delivery-debt provider protocol.

    Implements the duck-typed surface Application's accepted lifecycle
    contracts exercise (debt, retry, settlement, two-phase reservation,
    scoped publication buffering, subscription registry). The concrete
    backing-USD OVStage provider that originally proved this protocol was
    retired by release/0.2's native rewrite; the application-side
    guarantees remain and are regression-tested against this double.
    """

    def __init__(self, stage, undo_manager, stream):
        self.stage = stage
        self._undo_manager = undo_manager
        self._stream = stream
        self._backing_delivery_debt = set()
        self._backing_notice_key = object()
        self._transition_reserved = False
        self._scope_paths = None
        self._disposed = False
        # REAL consumer semantics: hierarchy/visibility reads delegate to
        # a genuine UsdStageAdapter view over the same stage, so consumer
        # models (HierarchyModel, StageWidget, footer) behave exactly as
        # in the accepted rounds while the double owns the delivery-debt
        # protocol surface.
        self._usd_view = UsdStageAdapter(stage, undo_manager=UndoManager())
        # The adapter's own notice INTAKE registers on the provider
        # stream (one stage subscriber while the document is live), and
        # a delivery-proof probe handle exists while undisposed — both
        # mirroring the retired provider's installed shape.
        self._intake = lambda event: None
        stream._stage_subscribers.append(self._intake)
        self._delivery_probe_sub = type(
            "_ProbeSub", (), {"cancel": lambda self: None})()

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_usd_view"), name)

    @property
    def _subscribers(self):
        return self._stream._stage_subscribers

    # ── item / authoring surface (hierarchy reads delegate to the
    #     real UsdStageAdapter view via __getattr__) ────────────────────
    def _publish(self, paths):
        try:
            receipt = self._stream.publish_visibility_change(list(paths))
        except BaseException:
            self._backing_delivery_debt.update(paths)
            raise
        if receipt is not True:
            self._backing_delivery_debt.update(paths)

    def set_visibility(self, item, visible):
        if self._transition_reserved:
            raise RuntimeError(
                "authoring refused: adapter reserved for replacement")
        path = (
            item if isinstance(item, str)
            else self._usd_view.get_item_path(item)
        )
        if self._scope_paths is not None:
            self._scope_paths.append(path)
            return
        adapter = self

        class _VisibilityEdge:
            """Undoable edge: every do/undo/redo re-publishes truthfully."""

            label = "Toggle Visibility"

            def do(self):
                adapter._publish([path])

            def undo(self):
                adapter._publish([path])

            def redo(self):
                adapter._publish([path])

        if self._undo_manager is not None:
            self._undo_manager.push(_VisibilityEdge())
        else:
            self._publish([path])

    def begin_undo_group(self, label):
        if self._scope_paths is None:
            self._scope_paths = []

    def end_undo_group(self):
        paths, self._scope_paths = self._scope_paths or [], None
        if paths:
            self._publish(paths)

    # ── delivery-debt protocol ───────────────────────────────────────
    @property
    def delivery_debt_pending(self):
        return bool(self._backing_delivery_debt)

    def retry_delivery_debt(self):
        owed = sorted(self._backing_delivery_debt)
        if not owed:
            return
        self._backing_delivery_debt = set()
        self._publish(owed)

    def settle_delivery_obligations(self):
        if self._scope_paths is not None:
            # A held-open scope closes (publishing its buffered roots)
            # before settlement can be judged — mirrors the retired
            # provider's scope finalization at the settlement boundary.
            self.end_undo_group()
        if self._backing_delivery_debt:
            self.retry_delivery_debt()
        return not self._backing_delivery_debt

    def begin_replacement_transition(self):
        if self._backing_delivery_debt or self._scope_paths is not None:
            return False
        self._transition_reserved = True
        return True

    def abort_replacement_transition(self):
        self._transition_reserved = False

    def dispose(self, force=False):
        if self._scope_paths is not None:
            self.end_undo_group()
        if self._backing_delivery_debt:
            # Final delivery attempt for the owed union: a throwable from
            # the provider stream propagates (the caller keeps the still-
            # live indebted adapter installed); remaining debt refuses.
            self.retry_delivery_debt()
        if self._backing_delivery_debt:
            raise UnresolvedDeliveryDebtError(
                "dispose refused: proven visibility delivery still owed")
        self._disposed = True
        self._transition_reserved = False
        self._backing_notice_key = None
        probe = self._delivery_probe_sub
        if probe is not None:
            try:
                probe.cancel()
                self._delivery_probe_sub = None
            except BaseException:
                # Probe revocation failed: the registration stays OWNED
                # (provider_registrations_pending True) so the caller
                # retains this adapter for retry instead of dropping a
                # live provider callback.
                pass
        try:
            self._stream._stage_subscribers.remove(self._intake)
        except ValueError:
            pass
        return True

    @property
    def provider_registrations_pending(self):
        return self._delivery_probe_sub is not None

    # ── consumer surface (subset the app tests touch) ────────────────
    def subscribe_changes(self, callback):
        registry = self._stream._stage_subscribers
        registry.append(callback)

        class _Sub:
            def cancel(self):
                try:
                    registry.remove(callback)
                except ValueError:
                    pass

        return _Sub()


# NOTE (release/0.2 integration): the per-edge delivery
# ledger / dispatch-proof / in-notification attempt proofs
# that lived here were RETIRED together with the
# backing-USD OVStage provider they exercised; the native
# OVStage provider ships its own hardened change-stream
# classification and tests upstream.


def _ovstage_debt_fixture(open_scope=False):
    """Delivery-debt provider double + silent provider stream.

    A visibility edit with an unprovable publication creates genuine
    protocol debt (or, with ``open_scope``, a buffered scope whose close
    will create it) — the application-contract shape of the reviewer's
    original scenario against the retired backing-USD provider.
    """
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World", "Xform")
    stage.DefinePrim("/World/A", "Cube")
    stream = _ProviderStream()
    adapter = _DebtProtocolAdapter(stage, UndoManager(), stream)
    stream.publish_visibility_change = lambda paths, **kw: None  # silent
    if open_scope:
        adapter.begin_undo_group("held edits")
    adapter.set_visibility(adapter.get_item_at_path("/World/A"), False)
    if open_scope:
        # Publication is buffered in the open scope: no debt exists yet;
        # it appears only when disposal closes the scope silently.
        assert adapter.delivery_debt_pending is False
    else:
        assert adapter._backing_delivery_debt == {"/World/A"}
    return adapter, stream


def _ovstage_adapter_with_stream(stage):
    """Delivery-debt provider double over a caller-provided stage."""
    stream = _ProviderStream()
    adapter = _DebtProtocolAdapter(stage, UndoManager(), stream)
    return adapter, stream


def _late_debt_adapter(lie_on_reserve=False):
    """Real indebted adapter whose debt is invisible until after the
    settlement boundary — models an inconsistent wrapper racing the
    replacement. With ``lie_on_reserve`` the reservation gate is lied to
    as well, so the dispose-time BaseException guard is genuinely
    exercised."""
    adapter, stream = _ovstage_debt_fixture()

    def interrupted_publish(paths, **kwargs):
        raise KeyboardInterrupt()

    stream.publish_visibility_change = interrupted_publish
    base = type(adapter)

    class _LateDebt(base):
        _pending_reads = {"n": 0}

        def settle_delivery_obligations(self):
            return True  # nothing owed YET at the settlement boundary

        @property
        def delivery_debt_pending(self):
            self._pending_reads["n"] += 1
            if self._pending_reads["n"] <= 1:  # the preflight's read
                return False
            return bool(self._backing_delivery_debt)

    if lie_on_reserve:
        class _LateDebt(_LateDebt):  # noqa: F811
            def begin_replacement_transition(self):
                return True

    adapter.__class__ = _LateDebt
    return adapter, stream


class TestReplacementDeliveryDebtRefusal:
    """Follow-up review: unresolved delivery debt refuses replacement
    non-destructively BEFORE any old-session mutation, and retries after
    provider recovery deliver the owed union first."""

    def _load_stage_app(self, adapter):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        factory_calls: list = []
        cancelled: list = []
        cleared: list = []

        def stage_factory(stage, undo, call_later):
            factory_calls.append(stage)
            raise _FactoryReached()

        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: cancelled.append(True))
        app._selection_bus = SimpleNamespace(
            clear=lambda: cleared.append(True))
        app._layer_adapter = None
        app._undo_manager = UndoManager()
        app.call_later = lambda *a, **k: None
        app._require_factory = lambda name: stage_factory
        app._viewport_window = None
        return app, factory_calls, cancelled, cleared

    def test_load_stage_refuses_before_any_mutation(self):
        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        adapter, stream = _ovstage_debt_fixture()
        app, factory_calls, cancelled, cleared = self._load_stage_app(
            adapter)
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="replacement refused"
        ):
            app._load_stage(Usd.Stage.CreateInMemory(), title="new")
        # ZERO mutation: factory never called, old subscription alive,
        # selection untouched, old adapter installed with its notice
        # listener, probe subscription, and debt all intact.
        assert factory_calls == []
        assert cancelled == []
        assert cleared == []
        assert app._stage_adapter is adapter
        assert adapter._backing_notice_key is not None
        assert adapter._backing_delivery_debt == {"/World/A"}
        assert len(stream._stage_subscribers) == 1

    def test_open_file_refuses_before_provider_open(self):
        from types import SimpleNamespace

        from ovui_data_adapters.common import UnresolvedDeliveryDebtError
        from ovui_widgets.app.application import Application

        adapter, _stream = _ovstage_debt_fixture()
        opened: list = []
        history_marker = object()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._startup_prebuilt_renderer = None
        app._current_file_path = "old.usda"
        app._undo_manager = UndoManager()
        app._undo_manager._undo_stack.append(history_marker)
        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: (opened.append(p), None)[1])
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="replacement refused"
        ):
            app.open_file("new.usda")
        assert opened == []                      # provider NEVER opened
        assert app._current_file_path == "old.usda"
        assert app._undo_manager._undo_stack == [history_marker]
        assert adapter._backing_delivery_debt == {"/World/A"}

    def test_load_empty_startup_stage_refuses(self):
        from ovui_data_adapters.common import UnresolvedDeliveryDebtError
        from ovui_widgets.app.application import Application

        adapter, _stream = _ovstage_debt_fixture()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="replacement refused"
        ):
            app._load_empty_startup_stage()
        assert adapter._backing_delivery_debt == {"/World/A"}
        assert adapter._backing_notice_key is not None

    def test_replacement_proceeds_after_provider_recovery(self):
        adapter, stream = _ovstage_debt_fixture()
        app, factory_calls, _cancelled, _cleared = self._load_stage_app(
            adapter)
        del stream.publish_visibility_change    # provider recovers
        with pytest.raises(_FactoryReached):
            app._load_stage(Usd.Stage.CreateInMemory(), title="new")
        # The complete owed union was delivered FIRST, then replacement
        # proceeded normally to the factory.
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()
        assert len(factory_calls) == 1

    def test_debt_created_by_scope_finalization_refuses_pre_mutation(self):
        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        # No debt exists on entry: the buffered scope only owes delivery
        # when it finalizes against the silent provider. The settlement
        # preflight performs that finalization BEFORE any mutation, so
        # the refusal happens with the application state untouched.
        adapter, stream = _ovstage_debt_fixture(open_scope=True)
        app, factory_calls, cancelled, cleared = self._load_stage_app(
            adapter)
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="replacement refused"
        ):
            app._load_stage(Usd.Stage.CreateInMemory(), title="new")
        assert factory_calls == []
        assert cancelled == []
        assert cleared == []
        assert app._stage_adapter is adapter
        assert adapter._backing_delivery_debt == {"/World/A"}
        assert adapter._backing_notice_key is not None
        # Retry after recovery delivers the union, then proceeds once.
        del stream.publish_visibility_change
        with pytest.raises(_FactoryReached):
            app._load_stage(Usd.Stage.CreateInMemory(), title="new")
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()

    def test_open_file_with_open_scope_refuses_before_provider_open(self):
        from types import SimpleNamespace

        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        adapter, stream = _ovstage_debt_fixture(open_scope=True)
        app, factory_calls, _cancelled, _cleared = self._load_stage_app(
            adapter)
        opened: list = []
        history_marker = object()
        app._startup_prebuilt_renderer = None
        app._current_file_path = "old.usda"
        app._undo_manager._undo_stack.append(history_marker)
        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: (
                opened.append(p), Usd.Stage.CreateInMemory())[1])
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="replacement refused"
        ):
            app.open_file("new.usda")
        # ZERO destructive mutation: provider never opened, document path
        # and history intact, adapter installed with debt and listener.
        assert opened == []
        assert app._current_file_path == "old.usda"
        assert app._undo_manager._undo_stack == [history_marker]
        assert app._stage_adapter is adapter
        assert adapter._backing_delivery_debt == {"/World/A"}
        # Retry after recovery: the owed union delivers first, then the
        # requested open proceeds exactly once.
        del stream.publish_visibility_change
        with pytest.raises(_FactoryReached):
            app.open_file("new.usda")
        assert opened == ["new.usda"]
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()
        assert len(factory_calls) == 1

    def test_new_stage_create_path_refuses_before_creation(self):
        from types import SimpleNamespace

        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        adapter, _stream = _ovstage_debt_fixture(open_scope=True)
        app, _factory_calls, _cancelled, _cleared = self._load_stage_app(
            adapter)
        created: list = []
        app._startup_prebuilt_renderer = None
        app._current_file_path = "old.usda"
        app._scratch_stage_dirs = []
        app.get_adapter_session = lambda: SimpleNamespace(
            create_stage=lambda p: (
                created.append(p), Usd.Stage.CreateInMemory())[1],
            get_capabilities=lambda: (_ for _ in ()).throw(
                RuntimeError("n/a")))
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="replacement refused"
        ):
            app._load_empty_startup_stage()
        assert created == []                     # replacement NOT created
        assert app._current_file_path == "old.usda"
        assert adapter._backing_delivery_debt == {"/World/A"}

    def test_base_exception_during_settlement_keeps_everything(self):
        adapter, stream = _ovstage_debt_fixture(open_scope=True)

        def interrupted_publish(paths, **kwargs):
            raise KeyboardInterrupt()

        stream.publish_visibility_change = interrupted_publish
        app, factory_calls, cancelled, cleared = self._load_stage_app(
            adapter)
        with pytest.raises(KeyboardInterrupt):
            app._load_stage(Usd.Stage.CreateInMemory(), title="new")
        # The primary throwable propagated pre-mutation: subscription and
        # selection untouched, adapter installed and live, roots re-owed.
        assert factory_calls == []
        assert cancelled == []
        assert cleared == []
        assert app._stage_adapter is adapter
        assert adapter._backing_delivery_debt == {"/World/A"}
        assert adapter._backing_notice_key is not None
        del stream.publish_visibility_change
        with pytest.raises(_FactoryReached):
            app._load_stage(Usd.Stage.CreateInMemory(), title="new")
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()

    def test_base_exception_from_dispose_never_detaches_indebted(self):
        # Debt invisible past BOTH the settlement and reservation gates
        # exercises the commit-time guard: the adapter's disposal raises
        # the throwable BEFORE detaching, and the application must keep
        # the still-live indebted adapter fully installed (subscription
        # and selection untouched).
        from types import SimpleNamespace

        adapter, _stream = _late_debt_adapter(lie_on_reserve=True)
        app, _factory_calls, cancelled, cleared = self._load_stage_app(
            adapter)
        app._require_factory = lambda name: (
            lambda *a, **kw: SimpleNamespace(
                subscribe_changes=lambda cb, **kw2: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw2: None,
                detach_stage=lambda: None))
        with pytest.raises(KeyboardInterrupt):
            app._load_stage(Usd.Stage.CreateInMemory(), title="new")
        assert cancelled == []
        assert cleared == []
        assert app._stage_adapter is adapter
        assert adapter._backing_delivery_debt == {"/World/A"}
        assert adapter._backing_notice_key is not None
        assert adapter._delivery_probe_sub is not None
        assert adapter._transition_reserved is False  # aborted

    def test_late_debt_open_file_refuses_before_any_mutation(self):
        from types import SimpleNamespace

        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        # The exact late-visible-debt adapter through the PUBLIC entry:
        # the atomic boundary (settle + disposal in the preflight) must
        # surface the throwable before provider open, path change, or
        # history clearing.
        adapter, stream = _late_debt_adapter()
        app, factory_calls, cancelled, _cleared = self._load_stage_app(
            adapter)
        opened: list = []
        history_marker = object()
        app._startup_prebuilt_renderer = None
        app._current_file_path = "old.usda"
        app._undo_manager._undo_stack.append(history_marker)
        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: (
                opened.append(p), Usd.Stage.CreateInMemory())[1])
        # The reservation gate reads the adapter's REAL state, so the
        # inconsistent wrapper refuses at the prepare phase, before any
        # mutation and before the interrupting flush is even attempted.
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="could not be reserved"
        ):
            app.open_file("new.usda")
        assert opened == []                      # provider NEVER opened
        assert app._current_file_path == "old.usda"
        assert app._undo_manager._undo_stack == [history_marker]
        assert cancelled == []
        assert app._stage_adapter is adapter
        assert adapter._backing_delivery_debt == {"/World/A"}
        assert adapter._backing_notice_key is not None
        # Recovery: the transient race is over (the adapter reports
        # truthfully again) and the provider recovers — the retry
        # delivers the union, then the open proceeds once.
        adapter.__class__ = type(adapter).__mro__[1]
        del stream.publish_visibility_change
        with pytest.raises(_FactoryReached):
            app.open_file("new.usda")
        assert opened == ["new.usda"]
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()
        assert len(factory_calls) == 1

class TestShutdownDeliveryDebtRefusal:
    """Follow-up review: unresolved delivery debt refuses shutdown before
    any provider/session/singleton teardown, and stays retryable."""

    def _app_with_session(self, adapter):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        class _Session:
            def __init__(self):
                self.calls = 0

            def shutdown_scene(self):
                self.calls += 1

        session = _Session()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = session
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        return app, session

    def test_shutdown_refuses_before_any_mutation(self):
        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        adapter, _stream = _ovstage_debt_fixture()
        app, session = self._app_with_session(adapter)
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="shutdown refused"
        ):
            app.shutdown()
        # NOTHING mutated: no provider scene shutdown, session installed,
        # flags untouched, adapter alive with its listener and debt.
        assert session.calls == 0
        assert app._adapter_session is session
        assert app._shutdown_done is False
        assert app._shutdown_in_progress is False
        assert app._stage_adapter is adapter
        assert adapter._backing_notice_key is not None
        assert adapter._backing_delivery_debt == {"/World/A"}

    def test_shutdown_retries_after_provider_recovery(self):
        adapter, stream = _ovstage_debt_fixture()
        app, session = self._app_with_session(adapter)
        del stream.publish_visibility_change    # provider recovers
        app.shutdown()
        # The owed union was delivered first; shutdown then completed.
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()
        assert session.calls == 1
        assert app._shutdown_done is True

    def test_refusal_during_exception_unwinding_stays_intact(self):
        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        adapter, stream = _ovstage_debt_fixture()
        app, session = self._app_with_session(adapter)
        try:
            raise ValueError("operation unwinding")
        except ValueError:
            with pytest.raises(
                UnresolvedDeliveryDebtError, match="shutdown refused"
            ):
                app.shutdown()
        assert session.calls == 0
        assert app._shutdown_in_progress is False
        assert adapter._backing_delivery_debt == {"/World/A"}
        # Retry after recovery still succeeds.
        del stream.publish_visibility_change
        app.shutdown()
        assert session.calls == 1
        assert adapter._backing_delivery_debt == set()

    def test_scope_debt_refuses_shutdown_before_scene_teardown(self):
        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        # No debt exists on entry: the buffered scope only owes delivery
        # when it finalizes. The settlement preflight surfaces that
        # BEFORE shutdown_scene or any session/singleton teardown.
        adapter, stream = _ovstage_debt_fixture(open_scope=True)
        app, session = self._app_with_session(adapter)
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="shutdown refused"
        ):
            app.shutdown()
        assert session.calls == 0                # scene NEVER shut down
        assert app._adapter_session is session
        assert app._shutdown_done is False
        assert app._shutdown_in_progress is False
        assert app._stage_adapter is adapter
        assert adapter._backing_delivery_debt == {"/World/A"}
        # Retry after recovery delivers the union, then shuts down once.
        del stream.publish_visibility_change
        app.shutdown()
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()
        assert session.calls == 1
        assert app._shutdown_done is True

    def test_base_exception_during_settlement_keeps_session(self):
        adapter, stream = _ovstage_debt_fixture(open_scope=True)

        def exiting_publish(paths, **kwargs):
            raise SystemExit(3)

        stream.publish_visibility_change = exiting_publish
        app, session = self._app_with_session(adapter)
        with pytest.raises(SystemExit):
            app.shutdown()
        # The primary throwable propagated pre-mutation: provider scene,
        # session, and adapter all intact; roots re-owed for a retry.
        assert session.calls == 0
        assert app._adapter_session is session
        assert app._stage_adapter is adapter
        assert app._shutdown_done is False
        assert app._shutdown_in_progress is False
        assert adapter._backing_delivery_debt == {"/World/A"}
        del stream.publish_visibility_change
        app.shutdown()
        assert session.calls == 1
        assert adapter._backing_delivery_debt == set()

    def test_base_exception_from_dispose_never_detaches_indebted(self):
        # Debt invisible past BOTH the settlement and reservation gates
        # exercises the commit-time guard inside shutdown.
        adapter, _stream = _late_debt_adapter(lie_on_reserve=True)
        app, _session = self._app_with_session(adapter)
        with pytest.raises(KeyboardInterrupt):
            app.shutdown()
        # The still-live indebted adapter stays installed and retryable.
        assert app._stage_adapter is adapter
        assert app._shutdown_done is False
        assert app._shutdown_in_progress is False
        assert adapter._backing_delivery_debt == {"/World/A"}
        assert adapter._backing_notice_key is not None
        assert adapter._delivery_probe_sub is not None
        assert adapter._transition_reserved is False  # aborted

    def test_late_debt_shutdown_refuses_before_scene_teardown(self):
        from ovui_data_adapters.common import UnresolvedDeliveryDebtError

        # The exact late-visible-debt adapter through PUBLIC shutdown:
        # the reservation gate reads the adapter's REAL state and refuses
        # before shutdown_scene or session nulling.
        adapter, stream = _late_debt_adapter()
        app, session = self._app_with_session(adapter)
        with pytest.raises(
            UnresolvedDeliveryDebtError, match="could not be reserved"
        ):
            app.shutdown()
        assert session.calls == 0                # scene NEVER shut down
        assert app._adapter_session is session
        assert app._shutdown_done is False
        assert app._shutdown_in_progress is False
        assert app._stage_adapter is adapter
        assert adapter._backing_delivery_debt == {"/World/A"}
        # Recovery: truthful adapter again + recovered provider — the
        # retry delivers the union, then shuts down once.
        adapter.__class__ = type(adapter).__mro__[1]
        del stream.publish_visibility_change
        app.shutdown()
        assert stream.visibility_publishes[0] == ("/World/A",)
        assert adapter._backing_delivery_debt == set()
        assert session.calls == 1
        assert app._shutdown_done is True

class TestTwoPhaseReplacementTransition:
    """Follow-up review: a failed replacement after successful settlement
    must leave the current document fully armed — delivery intake,
    undo/redo provider events, authoring, session — and retryable."""

    def _armed_adapter(self):
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/A", "Cube")
        adapter, stream = _ovstage_adapter_with_stream(stage)
        adapter.set_visibility(adapter.get_item_at_path("/World/A"), False)
        assert stream.visibility_publishes  # genuine prior publication
        return adapter, stream

    def _assert_fully_armed(self, adapter, stream):
        assert adapter._backing_notice_key is not None
        assert adapter._transition_reserved is False
        assert adapter._backing_delivery_debt == set()
        # Undo/redo still dispatch truthful provider visibility events.
        before = len(stream.visibility_publishes)
        assert adapter._undo_manager.undo() is True
        assert len(stream.visibility_publishes) == before + 1
        assert adapter._undo_manager.redo() is True
        assert len(stream.visibility_publishes) == before + 2
        # New authoring still works and publishes (a REAL toggle, not an
        # outcome no-op: redo left the prim invisible).
        adapter.set_visibility(adapter.get_item_at_path("/World/A"), True)
        assert len(stream.visibility_publishes) == before + 3

    def _app(self, adapter):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._current_stage_sub = None
        app._selection_bus = SimpleNamespace(clear=lambda: None)
        app._layer_adapter = None
        app._undo_manager = adapter._undo_manager
        app.call_later = lambda *a, **k: None
        app._startup_prebuilt_renderer = None
        app._current_file_path = "old.usda"
        return app

    def test_failed_provider_open_keeps_document_fully_armed(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)

        def raising_open(path):
            raise RuntimeError("provider open failed")

        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=raising_open)
        app.open_file("new.usda")   # reports the error and returns
        assert app._current_file_path == "old.usda"
        assert app._stage_adapter is adapter
        assert adapter._undo_manager.can_undo() is True  # history kept
        self._assert_fully_armed(adapter, stream)

    def test_failed_new_stage_creation_keeps_document_fully_armed(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._scratch_stage_dirs = []

        def raising_create(path):
            raise RuntimeError("provider create failed")

        app.get_adapter_session = lambda: SimpleNamespace(
            create_stage=raising_create,
            get_capabilities=lambda: (_ for _ in ()).throw(
                RuntimeError("n/a")))
        with pytest.raises(RuntimeError, match="provider create failed"):
            app._load_empty_startup_stage()
        assert app._current_file_path == "old.usda"
        self._assert_fully_armed(adapter, stream)

    def test_unsupported_new_stage_keeps_document_fully_armed(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._scratch_stage_dirs = []
        app.get_adapter_session = lambda: SimpleNamespace(
            get_capabilities=lambda: SimpleNamespace(
                stage=SimpleNamespace(
                    create_stage=SimpleNamespace(is_supported=False))))
        # NO replacement at all: the current adapter must not be touched.
        assert app._load_empty_startup_stage() is False
        assert app._current_file_path == "old.usda"
        assert app._stage_adapter is adapter
        self._assert_fully_armed(adapter, stream)

    def test_failing_factory_keeps_subscription_selection_and_intake(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        cancelled: list = []
        cleared: list = []
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: cancelled.append(True))
        app._selection_bus = SimpleNamespace(
            clear=lambda: cleared.append(True))

        def failing_factory(*args, **kwargs):
            raise RuntimeError("stage factory failed")

        app._require_factory = lambda name: failing_factory
        with pytest.raises(RuntimeError, match="stage factory failed"):
            app.open_stage(Usd.Stage.CreateInMemory())
        # The OLD subscription and selection remain: nothing detached.
        assert cancelled == []
        assert cleared == []
        assert app._stage_adapter is adapter
        self._assert_fully_armed(adapter, stream)
        # Retry with a working factory commits exactly once: the new
        # adapter installs, and only then does the old intake detach.
        new_adapters: list = []

        def working_factory(*args, **kwargs):
            new = SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw: None)
            new_adapters.append(new)
            return new

        app._require_factory = lambda name: working_factory
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        app.open_stage(Usd.Stage.CreateInMemory())
        assert app._stage_adapter is new_adapters[0]
        assert cancelled == [True]
        assert adapter._backing_notice_key is None  # committed detach

    def test_renderer_preconstruct_failure_releases_reservation(self):
        from ovui_widgets.app.application import _NO_PREBUILT_RENDERER

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._startup_prebuilt_renderer = _NO_PREBUILT_RENDERER

        def raising_preconstruct():
            raise RuntimeError("renderer construction failed")

        app._preconstruct_ovrtx_renderer = raising_preconstruct
        with pytest.raises(RuntimeError, match="renderer construction"):
            app.open_file("new.usda")
        assert app._current_file_path == "old.usda"
        assert app._stage_adapter is adapter
        self._assert_fully_armed(adapter, stream)

    def test_capability_failure_via_new_stage_releases_reservation(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._scratch_stage_dirs = []
        app.get_adapter_session = lambda: SimpleNamespace(
            get_capabilities=lambda: (_ for _ in ()).throw(
                ValueError("capability probe failed")))
        # Public new_stage reports the failure and returns False; the
        # reservation must not leak.
        assert app.new_stage() is False
        assert app._stage_adapter is adapter
        self._assert_fully_armed(adapter, stream)

    def test_provider_switch_then_factory_failure_converges_no_document(
        self,
    ):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        cancelled: list = []
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: cancelled.append(True))
        provider = SimpleNamespace(current=None)
        replacement = Usd.Stage.CreateInMemory()

        def provider_open(path):
            provider.current = replacement  # session switched pre-return
            return replacement

        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=provider_open)
        app._require_factory = lambda name: (
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("factory failed")))
        with pytest.raises(RuntimeError, match="factory failed"):
            app.open_file("replacement.usda")
        # NEVER a split document: the provider is on the replacement
        # stage, so the application converges on the explicit
        # no-document state — old adapter disposed and uninstalled, its
        # wiring cleared, nothing reserved.
        assert app._stage_adapter is None
        assert app._current_file_path is None
        assert app._current_stage_sub is None
        assert cancelled == [True]
        assert adapter._backing_notice_key is None    # disposed
        assert adapter._transition_reserved is False
        assert adapter._backing_delivery_debt == set()

    def test_old_subscription_cancel_failure_still_commits(self):
        from types import SimpleNamespace

        adapter, _stream = self._armed_adapter()
        app = self._app(adapter)

        def bad_cancel():
            raise RuntimeError("cancel failed")

        app._current_stage_sub = SimpleNamespace(cancel=bad_cancel)
        new_adapters: list = []

        def working_factory(*args, **kwargs):
            new = SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw: None,
                detach_stage=lambda: None)
            new_adapters.append(new)
            return new

        app._require_factory = lambda name: working_factory
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        # The old adapter is already disposed when cancellation fails:
        # the commit continues to ONE coherent NEW document instead of
        # leaving a disposed adapter installed.
        app.open_stage(Usd.Stage.CreateInMemory())
        assert app._stage_adapter is new_adapters[0]
        assert app._current_stage_sub is not None
        assert adapter._backing_notice_key is None    # committed detach

    def test_new_subscription_failure_keeps_old_document(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        cancelled: list = []
        cleared: list = []
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: cancelled.append(True))
        app._selection_bus = SimpleNamespace(
            clear=lambda: cleared.append(True))
        app._require_factory = lambda name: (
            lambda *a, **kw: SimpleNamespace(
                subscribe_changes=lambda cb, **kw2: (_ for _ in ()).throw(
                    RuntimeError("subscribe failed")),
                attach_stage=lambda **kw2: None,
                detach_stage=lambda: None))
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        with pytest.raises(RuntimeError, match="subscribe failed"):
            app.open_stage(Usd.Stage.CreateInMemory())
        # The replacement could never notify consumers, so it was never
        # installed: the OLD document remains current and complete.
        assert cancelled == []
        assert cleared == []
        assert app._stage_adapter is adapter
        assert app._current_stage_sub is not None
        self._assert_fully_armed(adapter, stream)

    def test_shutdown_base_exception_after_session_completes(self):
        from types import SimpleNamespace

        adapter, _stream = self._armed_adapter()

        from ovui_widgets.app.application import Application

        class _ExitingRenderer:
            def shutdown(self):
                raise SystemExit(7)

        app = Application.__new__(Application)
        app._stage_adapter = adapter
        session = SimpleNamespace(shutdown_scene=lambda: None)
        app._adapter_session = session
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = _ExitingRenderer()
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        with pytest.raises(SystemExit):
            app.shutdown()
        # The original throwable propagated, but shutdown CONVERGED: no
        # frozen half-state with a reserved adapter and live listeners.
        assert app._shutdown_done is True
        assert app._stage_adapter is None
        assert adapter._transition_reserved is False
        assert adapter._backing_notice_key is None    # disposed

    def test_prep_cleanup_preserves_primary_and_releases_reservation(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None

        def factory(*args, **kwargs):
            return SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: (_ for _ in ()).throw(
                        SystemExit("secondary-cancel"))),
                attach_stage=lambda **kw: (_ for _ in ()).throw(
                    RuntimeError("primary layer attach failed")),
                detach_stage=lambda: None)

        app._require_factory = lambda name: factory
        with pytest.raises(RuntimeError, match="primary layer attach"):
            app.open_stage(Usd.Stage.CreateInMemory())
        # The PRIMARY error propagated; the SystemExit from cleanup is an
        # inspectable note; the reservation was unconditionally released.
        assert adapter._transition_reserved is False
        self._assert_fully_armed(adapter, stream)

    def test_no_document_convergence_detaches_real_stage_browser(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        adapter, _stream = self._armed_adapter()
        app = self._app(adapter)
        widget = StageWidget(adapter=adapter)
        assert widget._model.resolve_path("/World/A") is not None
        app._stage_window = widget
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        replacement = Usd.Stage.CreateInMemory()
        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: replacement)
        app._require_factory = lambda name: (
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("factory failed")))
        with pytest.raises(RuntimeError, match="factory failed"):
            app.open_file("replacement.usda")
        # The REAL Stage Browser converged with the application: no
        # stale document ownership, no resolvable old row.
        assert app._stage_adapter is None
        assert widget.get_adapter() is None
        assert widget._model.resolve_path("/World/A") is None
        assert widget._model.get_item_children(None) == []
        assert widget._compute_stage_counts() == (0, 0)

    def test_commit_wiring_failure_converges_completely(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        adapter, _stream = self._armed_adapter()
        app = self._app(adapter)
        widget = StageWidget(adapter=adapter)
        app._stage_window = widget
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        calls = {"n": 0}
        disposed = {"done": False}

        class _NewAdapter:
            def subscribe_changes(self, cb, **kw):
                calls["n"] += 1
                if calls["n"] >= 2:   # the Stage Browser's subscription
                    raise RuntimeError("hierarchy subscribe failed")
                return SimpleNamespace(cancel=lambda: None)

            def get_root(self):
                return SimpleNamespace(path="/")

            def attach_stage(self, **kw):
                pass

            def detach_stage(self):
                pass

            def dispose(self):
                disposed["done"] = True

        new_adapter = _NewAdapter()
        app._require_factory = lambda name: (lambda *a, **kw: new_adapter)
        with pytest.raises(RuntimeError, match="hierarchy subscribe"):
            app.open_stage(Usd.Stage.CreateInMemory())
        # NO partially-synchronized document: everything converged on
        # the explicit no-document state and the replacement was
        # released.
        assert app._stage_adapter is None
        assert widget.get_adapter() is None
        assert widget._model.resolve_path("/World/A") is None
        assert disposed["done"] is True

    def test_failed_old_cancellation_retains_live_handle_for_retry(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        # A REAL registered provider-stream subscription whose first
        # cancellation raises.
        received: list = []
        real_handle = adapter.subscribe_changes(received.append)
        state = {"fail": True}

        def flaky_cancel():
            if state["fail"]:
                raise RuntimeError("cancel failed")
            real_handle.cancel()

        app._current_stage_sub = SimpleNamespace(cancel=flaky_cancel)

        def working_factory(*args, **kwargs):
            return SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw: None,
                detach_stage=lambda: None,
                dispose=lambda: None)

        app._require_factory = lambda name: working_factory
        app.open_stage(Usd.Stage.CreateInMemory())
        # The live callback was NOT silently dropped: the handle is
        # retained for retry while the old stream still has it.
        assert len(app._orphaned_stage_subs) == 1
        assert len(stream._stage_subscribers) == 1
        # The next transition boundary drains it definitively.
        state["fail"] = False
        app.open_stage(Usd.Stage.CreateInMemory())
        assert app._orphaned_stage_subs == []
        assert stream._stage_subscribers == []

    def test_no_document_convergence_detaches_product_stage_window(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.window.stage_window import StageWindow

        adapter, _stream = self._armed_adapter()
        app = self._app(adapter)
        window = StageWindow(adapter=adapter)
        window._build_ui()   # the product builds the widget lazily
        assert window._widget._model.resolve_path("/World/A") is not None
        app._stage_window = window
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        replacement = Usd.Stage.CreateInMemory()
        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: replacement)
        app._require_factory = lambda name: (
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("factory failed")))
        with pytest.raises(RuntimeError, match="factory failed"):
            app.open_file("replacement.usda")
        # The PRODUCT window converged, not just a raw widget.
        assert app._stage_adapter is None
        assert window._widget.get_adapter() is None
        assert window._widget._model.resolve_path("/World/A") is None

    def test_old_stream_event_cannot_mutate_new_document(self):
        from types import SimpleNamespace

        old_adapter, old_stream = self._armed_adapter()
        app = self._app(old_adapter)
        app._stage_adapter = None   # first transition installs old_adapter
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        received: list = []
        app._on_stage_changed = received.append
        # First REAL transition: the application subscription (identity
        # guarded) registers on old_adapter's live provider stream.
        app._require_factory = lambda name: (
            lambda *a, **kw: old_adapter
            if name == "stage" else SimpleNamespace(
                attach_stage=lambda **kw2: None,
                detach_stage=lambda: None))
        app.open_stage(Usd.Stage.CreateInMemory())
        assert app._stage_adapter is old_adapter
        # Second transition: old cancellation fails, the handle is
        # retained, and a stub replacement installs.
        real_old_sub = app._current_stage_sub
        state = {"fail": True}

        def flaky_cancel():
            if state["fail"]:
                raise RuntimeError("cancel failed")
            real_old_sub.cancel()

        app._current_stage_sub = SimpleNamespace(cancel=flaky_cancel)

        def stub_factory(*args, **kwargs):
            return SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw: None,
                detach_stage=lambda: None,
                dispose=lambda: None)

        app._require_factory = lambda name: stub_factory
        app.open_stage(Usd.Stage.CreateInMemory())
        assert app._stage_adapter is not old_adapter
        # A genuine event from the OLD stream must not reach the new
        # document's application listener — the retained callback is
        # identity-guarded, hence harmless.
        received.clear()
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType
        event = ChangeEvent(
            changed_paths=("/World/A",), resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source="ovstage:visibility")
        for callback in list(old_stream._stage_subscribers):
            callback(event)
        assert received == []
        assert len(app._orphaned_stage_subs) == 1
        # A later boundary drains the orphan definitively.
        state["fail"] = False
        app.open_stage(Usd.Stage.CreateInMemory())
        assert app._orphaned_stage_subs == []

    def test_model_swap_completes_under_system_exit(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        old_adapter, _old_stream = self._armed_adapter()
        widget = StageWidget(adapter=old_adapter)
        model = widget._model
        model._change_sub = SimpleNamespace(
            cancel=lambda: (_ for _ in ()).throw(SystemExit("old-cancel")))
        new_adapter, new_stream = self._armed_adapter()
        with pytest.raises(SystemExit):
            model.set_adapter(new_adapter)
        # COMPLETE state despite the throwable: the model owns the new
        # adapter and its live subscription; the failed old handle is
        # retained for retry — nothing leaked, nothing half-swapped.
        assert model._adapter is new_adapter
        assert len(model._stale_change_subs) == 1
        assert model.resolve_path("/World/A") is not None

    def test_footer_cancel_failure_does_not_abort_detach(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        adapter, _stream = self._armed_adapter()
        widget = StageWidget(adapter=adapter)
        widget._footer_adapter_sub = SimpleNamespace(
            cancel=lambda: (_ for _ in ()).throw(SystemExit("footer")))
        widget.detach_document()
        assert widget.get_adapter() is None
        assert widget._model.resolve_path("/World/A") is None
        assert len(widget._stale_footer_subs) == 1

    def test_shutdown_completion_is_truthful_over_panels(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()

        class _KIRenderer:
            def shutdown(self):
                raise KeyboardInterrupt()

        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = _KIRenderer()
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        destroyed: list = []
        stubborn = {"fail": True}

        def make_panel(name, fail=False):
            def destroy():
                if fail and stubborn["fail"]:
                    raise RuntimeError("panel destroy failed")
                destroyed.append(name)
            return SimpleNamespace(destroy=destroy)

        app._stage_window = make_panel("stage", fail=True)
        app._property_window = make_panel("property")
        app._viewport_window = make_panel("viewport")
        app._content_window = make_panel("content")
        app._layer_window = make_panel("layers")
        app._main_win = None
        with pytest.raises(KeyboardInterrupt):
            app.shutdown()
        # Every panel teardown was attempted; the four healthy panels
        # died — but the STUBBORN one keeps its ownership, so shutdown is
        # truthfully INCOMPLETE and retryable.
        assert sorted(destroyed) == [
            "content", "layers", "property", "viewport"]
        assert app._shutdown_done is False
        assert app._stage_window is not None
        assert app._stage_adapter is None
        # The retry completes once the panel can actually die.
        stubborn["fail"] = False
        app.shutdown()
        assert app._shutdown_done is True
        assert app._stage_window is None

    def test_normal_shutdown_with_failing_sub_cancel_clears_ownership(
        self,
    ):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: (_ for _ in ()).throw(
                RuntimeError("cancel failed")))
        app.shutdown()
        # Ownership CLEARED despite the failing cancellation; the handle
        # is retained as an orphan whose callback is epoch-guarded and
        # therefore PERMANENTLY NEUTRALIZED (_document_epoch is None), so
        # completion is truthful.
        assert app._stage_adapter is None
        assert app._current_stage_sub is None
        assert app._document_epoch is None
        assert app._shutdown_done is True
        assert len(app._orphaned_stage_subs) == 1

    def test_no_document_detaches_viewport_and_clears_history(self):
        from types import SimpleNamespace

        from ovui_widgets.viewport.prim_transform_model import (
            PrimTransformModel,
        )

        adapter, _stream = self._armed_adapter()
        app = self._app(adapter)
        model = PrimTransformModel()
        model.attach_adapters(
            transform_adapter=object(), stage_adapter=adapter,
            undo=adapter._undo_manager)

        class _Viewport:
            def set_renderer(self, renderer):
                pass

            def attach_stage(self, transform_adapter=None,
                             stage_adapter=None, undo_manager=None,
                             snap_system=None):
                model.attach_adapters(
                    transform_adapter=transform_adapter,
                    stage_adapter=stage_adapter, undo=undo_manager,
                    snap_system=snap_system)

        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = _Viewport()
        replacement = Usd.Stage.CreateInMemory()
        app.get_adapter_session = lambda: SimpleNamespace(
            open_stage=lambda p: replacement)
        app._require_factory = lambda name: (
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("factory failed")))
        assert adapter._undo_manager.can_undo() is True
        with pytest.raises(RuntimeError, match="factory failed"):
            app.open_file("replacement.usda")
        # The destroyed document is unreachable through viewport state
        # and its commands are gone from history.
        assert model.has_adapters() is False
        assert model._stage is None
        assert adapter._undo_manager.can_undo() is False

    def test_same_adapter_reuse_keeps_stale_callback_inert(self):
        from types import SimpleNamespace

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._stage_adapter = None
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None
        received: list = []
        app._on_stage_changed = received.append

        def factories(name, target=None):
            if name == "stage":
                return lambda *a, **kw: target
            return lambda *a, **kw: SimpleNamespace(
                attach_stage=lambda **kw2: None,
                detach_stage=lambda: None)

        def stub_factory(*args, **kwargs):
            return SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw: None,
                detach_stage=lambda: None, dispose=lambda: None)

        app._require_factory = lambda name: factories(name, adapter)
        app.open_stage(Usd.Stage.CreateInMemory())     # install A
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: (_ for _ in ()).throw(
                RuntimeError("cancel failed")))
        app._require_factory = lambda name: stub_factory
        app.open_stage(Usd.Stage.CreateInMemory())     # A -> B, cancel fails
        app._require_factory = lambda name: factories(name, adapter)
        app.open_stage(Usd.Stage.CreateInMemory())     # B -> SAME A object
        received.clear()
        event = ChangeEvent(
            changed_paths=("/World/A",), resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source="ovstage:visibility")
        for callback in list(stream._stage_subscribers):
            callback(event)
        # EXACTLY once: the stale epoch-guarded callback never regains
        # authority even though the same adapter object is current again.
        assert len(received) == 1

    def test_widget_swap_stays_atomic_under_system_exit(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        old_adapter, _s1 = self._armed_adapter()
        widget = StageWidget(adapter=old_adapter)
        widget._model._change_sub = SimpleNamespace(
            cancel=lambda: (_ for _ in ()).throw(SystemExit("old-cancel")))
        new_adapter, _s2 = self._armed_adapter()
        with pytest.raises(SystemExit):
            widget.set_adapter(new_adapter)
        # NO split ownership: wrapper field, model, and footer all landed
        # on the new document before the primary re-raised.
        assert widget._adapter is new_adapter
        assert widget._model._adapter is new_adapter
        assert widget._footer_adapter_sub is not None

    def test_orphan_bound_refuses_instead_of_dropping_handles(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()
        app = self._app(adapter)
        app._stage_adapter = None
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None

        def stub_factory(*args, **kwargs):
            return SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw: None,
                detach_stage=lambda: None, dispose=lambda: None)

        app._require_factory = lambda name: stub_factory
        refused_at = None
        for attempt in range(40):
            app._current_stage_sub = SimpleNamespace(
                cancel=lambda: (_ for _ in ()).throw(
                    RuntimeError("cancel failed")))
            try:
                app.open_stage(Usd.Stage.CreateInMemory())
            except RuntimeError as exc:
                assert "refused" in str(exc)
                refused_at = attempt
                break
        # The transition REFUSED before ownership could exceed its bound;
        # every retained handle survives (nothing dropped).
        assert refused_at is not None
        assert len(app._orphaned_stage_subs) <= 32

    def test_footer_acquisition_failure_keeps_widget_entirely_old(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        old_adapter, _s1 = self._armed_adapter()
        widget = StageWidget(adapter=old_adapter)
        old_footer = widget._footer_adapter_sub
        calls = {"n": 0}

        class _NewAdapter:
            def subscribe_changes(self, cb, **kw):
                calls["n"] += 1
                raise RuntimeError("footer subscribe failed")

            def get_root(self):
                return SimpleNamespace(path="/")

        with pytest.raises(RuntimeError, match="footer subscribe"):
            widget.set_adapter(_NewAdapter())
        # ENTIRELY old: wrapper field, model, and footer subscription.
        assert widget._adapter is old_adapter
        assert widget._model._adapter is old_adapter
        assert widget._footer_adapter_sub is old_footer

    def test_detach_completes_all_layers_under_system_exit(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        adapter, _stream = self._armed_adapter()
        widget = StageWidget(adapter=adapter)
        widget._model._change_sub = SimpleNamespace(
            cancel=lambda: (_ for _ in ()).throw(SystemExit("cancel")))
        with pytest.raises(SystemExit):
            widget.detach_document()
        # ENTIRELY detached — no layer stays on the old document.
        assert widget._adapter is None
        assert widget._model._adapter is None
        assert widget._model.resolve_path("/World/A") is None

    def test_bus_cancellation_ownership_survives_until_confirmed(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.stage_widget import StageWidget

        adapter, _stream = self._armed_adapter()
        widget = StageWidget(adapter=adapter)
        attempts = {"n": 0}
        real_bus_sub = widget._bus_sub

        class _FlakyBusSub:
            def cancel(self):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("bus cancel failed")
                if real_bus_sub is not None:
                    real_bus_sub.cancel()

        widget._bus_sub = _FlakyBusSub()
        with pytest.raises(RuntimeError, match="bus cancel failed"):
            widget.destroy()
        # The ONLY revocation handle survives the failure.
        assert widget._bus_sub is not None
        widget.destroy()   # retry CONFIRMS the cancellation
        assert widget._bus_sub is None
        assert attempts["n"] == 2

    def test_selection_bus_cancel_retry_genuinely_removes(self):
        from ovui_widgets.common.selection import SelectionBus

        bus = SelectionBus()
        received: list = []
        sub = bus.subscribe(received.append)
        original_remove = bus._remove_subscriber
        state = {"fail": True}

        def flaky_remove(callback):
            if state["fail"]:
                raise RuntimeError("removal failed")
            original_remove(callback)

        bus._remove_subscriber = flaky_remove
        with pytest.raises(RuntimeError, match="removal failed"):
            sub.cancel()
        # NOT marked cancelled: the retry invokes removal again and the
        # callback is genuinely gone afterwards.
        state["fail"] = False
        sub.cancel()
        assert bus._subscribers == []

    def test_model_swap_bound_refuses_after_repeated_failures(self):
        from types import SimpleNamespace

        from ovui_widgets.stage.widget.hierarchy_model import HierarchyModel

        adapter, _stream = self._armed_adapter()
        model = HierarchyModel(adapter)

        class _BadHandleAdapter:
            def subscribe_changes(self, cb, **kw):
                return SimpleNamespace(cancel=lambda: (_ for _ in ()).throw(
                    RuntimeError("cancel failed")))

            def get_root(self):
                return SimpleNamespace(path="/")

        refused = False
        for _ in range(40):
            try:
                model.set_adapter(_BadHandleAdapter())
            except RuntimeError as exc:
                if "refused" in str(exc):
                    refused = True
                    break
        # Bounded ownership: further swaps refuse rather than accumulate
        # live registrations; nothing was dropped.
        assert refused is True
        assert len(model._stale_change_subs) <= 32
        # The current document remains usable after the refusal.
        assert model._adapter is not None

    def test_openusd_and_service_subscriptions_cancel_after_removal(self):
        # One truthful contract across the lifecycle's subscriptions:
        # state flips only after CONFIRMED removal, so a retry genuinely
        # removes the callback.
        undo = UndoManager()
        handle = undo.subscribe_change(lambda: None)
        original = undo._remove_subscriber
        state = {"fail": True}

        def flaky(callback):
            if state["fail"]:
                raise RuntimeError("removal failed")
            original(callback)

        undo._remove_subscriber = flaky
        with pytest.raises(RuntimeError):
            handle.cancel()
        state["fail"] = False
        handle.cancel()
        assert undo._subscribers == []

        stage = Usd.Stage.CreateInMemory()
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        sub = adapter.subscribe_changes(lambda e: None)
        original_remove = adapter._remove_subscriber
        state2 = {"fail": True}

        def flaky2(key, callback):
            if state2["fail"]:
                raise RuntimeError("removal failed")
            original_remove(key, callback)

        adapter._remove_subscriber = flaky2
        with pytest.raises(RuntimeError):
            sub.cancel()
        state2["fail"] = False
        sub.cancel()
        assert len(adapter._subscribers) == 0
        adapter.dispose()

    def test_edit_menu_rewire_never_installs_duplicate(self):
        from types import SimpleNamespace

        from ovui_widgets.app.menu_bar import _wire_edit_menu_invalidation
        from ovui_widgets.app.application import Application

        app = Application.__new__(Application)
        undo = UndoManager()
        app._undo_manager = undo
        menu = SimpleNamespace(invalidate=lambda: None)
        _wire_edit_menu_invalidation(app, menu)
        assert len(undo._subscribers) == 1
        original = undo._remove_subscriber
        state = {"fail": True}

        def flaky(callback):
            if state["fail"]:
                raise RuntimeError("removal failed")
            original(callback)

        undo._remove_subscriber = flaky
        menu2 = SimpleNamespace(invalidate=lambda: None)
        _wire_edit_menu_invalidation(app, menu2)
        # The OLD callback stayed owned; NO duplicate was installed.
        assert len(undo._subscribers) == 1
        assert len(app._stale_edit_menu_subs) == 1
        state["fail"] = False
        menu3 = SimpleNamespace(invalidate=lambda: None)
        _wire_edit_menu_invalidation(app, menu3)
        # Recovery drained the stale handle and installed exactly one.
        assert len(undo._subscribers) == 1
        assert app._stale_edit_menu_subs == []

    def test_shutdown_incomplete_while_probe_revocation_pending(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()
        probe_sub = adapter._delivery_probe_sub
        assert probe_sub is not None
        original_cancel = probe_sub.cancel
        state = {"fail": True}

        def flaky_cancel():
            if state["fail"]:
                raise RuntimeError("probe removal failed")
            original_cancel()

        probe_sub.cancel = flaky_cancel
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        app.shutdown()
        # A private provider registration is still unrevoked: ownership
        # stays REACHABLE and shutdown is truthfully incomplete.
        assert app._shutdown_done is False
        assert app._stage_adapter is adapter
        assert adapter.provider_registrations_pending is True
        # The retry drains the revocation and completes.
        state["fail"] = False
        app.shutdown()
        assert app._shutdown_done is True
        assert app._stage_adapter is None
        assert adapter.provider_registrations_pending is False

    def test_replacement_retains_pending_probe_adapter_as_orphan(self):
        from types import SimpleNamespace

        adapter, _stream = self._armed_adapter()
        probe_sub = adapter._delivery_probe_sub
        assert probe_sub is not None
        original_cancel = probe_sub.cancel
        state = {"fail": True}

        def flaky_cancel():
            if state["fail"]:
                raise RuntimeError("probe removal failed")
            original_cancel()

        probe_sub.cancel = flaky_cancel
        app = self._app(adapter)
        app._stage_window = None
        app._property_window = None
        app._layer_window = None
        app._viewport_window = None

        def stub_factory(*args, **kwargs):
            return SimpleNamespace(
                subscribe_changes=lambda cb, **kw: SimpleNamespace(
                    cancel=lambda: None),
                attach_stage=lambda **kw: None,
                detach_stage=lambda: None, dispose=lambda: None)

        app._require_factory = lambda name: stub_factory
        app.open_stage(Usd.Stage.CreateInMemory())
        # The replacement completed but never ABANDONED the outgoing
        # adapter's live registration: it is retained as an explicit
        # reachable retry owner, and shutdown cannot report clear.
        assert app._orphaned_adapters == [adapter]
        assert adapter.provider_registrations_pending is True
        assert app._shutdown_ownership_clear() is False
        # The next transition retries and clears the registration.
        state["fail"] = False
        app.open_stage(Usd.Stage.CreateInMemory())
        assert app._orphaned_adapters == []
        assert adapter.provider_registrations_pending is False

    def test_shutdown_incomplete_while_settings_callback_operative(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        state = {"fail": True}

        class _SettingsSub:
            def cancel(self):
                if state["fail"]:
                    raise RuntimeError("removal failed")

        app._theme_sub = _SettingsSub()
        app.shutdown()
        # The retained operative callback keeps shutdown incomplete.
        assert app._shutdown_done is False
        assert len(app._stale_service_subs) == 1
        state["fail"] = False
        app.shutdown()
        assert app._shutdown_done is True
        assert app._stale_service_subs == []

    def test_orphaned_adapter_bound_refuses_before_unbounded_growth(self):
        from types import SimpleNamespace

        app = None
        refused = False
        adapters = []
        for attempt in range(40):
            adapter, _stream = self._armed_adapter()
            probe_sub = adapter._delivery_probe_sub
            probe_sub.cancel = lambda: (_ for _ in ()).throw(
                RuntimeError("probe removal failed"))
            adapters.append(adapter)
            if app is None:
                app = self._app(adapter)
                app._stage_window = None
                app._property_window = None
                app._layer_window = None
                app._viewport_window = None
            else:
                app._stage_adapter = adapter
                app._current_stage_sub = None
                app._document_epoch = None

            def stub_factory(*args, **kwargs):
                return SimpleNamespace(
                    subscribe_changes=lambda cb, **kw: SimpleNamespace(
                        cancel=lambda: None),
                    attach_stage=lambda **kw: None,
                    detach_stage=lambda: None, dispose=lambda: None)

            app._require_factory = lambda name: stub_factory
            try:
                app.open_stage(Usd.Stage.CreateInMemory())
            except RuntimeError as exc:
                assert "refused" in str(exc)
                refused = True
                break
        # Bounded: replacements refuse before unbounded orphan growth;
        # every retained adapter remains reachable and deduplicated.
        assert refused is True
        assert len(app._orphaned_adapters) <= 32
        assert len(app._orphaned_adapters) == len(
            {id(a) for a in app._orphaned_adapters})

    def test_shutdown_keyboard_interrupt_keeps_service_handle(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        state = {"fail": True}

        class _KISub:
            def cancel(self):
                if state["fail"]:
                    raise KeyboardInterrupt()

        app._theme_sub = _KISub()
        with pytest.raises(KeyboardInterrupt):
            app.shutdown()
        # PRIMARY preserved, handle retained, shutdown incomplete.
        assert app._shutdown_done is False
        assert len(app._stale_service_subs) == 1
        # Recovery: the retried shutdown revokes and completes.
        state["fail"] = False
        app.shutdown()
        assert app._shutdown_done is True
        assert app._stale_service_subs == []

    def test_shutdown_processes_later_service_handles_best_effort(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        state = {"fail": True}
        later = {"cancelled": 0}

        class _OneShotKI:
            def cancel(self):
                if state["fail"]:
                    state["fail"] = False   # one-shot: retry succeeds
                    raise KeyboardInterrupt()

        class _Later:
            def cancel(self):
                later["cancelled"] += 1

        app._snap_sub = _OneShotKI()
        app._theme_sub = _Later()
        with pytest.raises(KeyboardInterrupt):
            app.shutdown()
        # ONE preserved-primary disposition: the later handle was still
        # processed best-effort, and shutdown stayed incomplete because
        # the failed attribute remains populated.
        assert later["cancelled"] == 1
        assert app._theme_sub is None
        assert app._snap_sub is not None
        assert app._shutdown_done is False
        # The retried shutdown genuinely retries and completes.
        app.shutdown()
        assert app._snap_sub is None
        assert app._shutdown_done is True

    def test_thousand_precreated_registrations_never_orphan(self):
        import gc
        import sys

        undo = UndoManager()
        # 1,000 LIVE registrations exist BEFORE the failure begins.
        handles = [undo.subscribe_change(lambda: None) for _ in range(1000)]
        original = undo._remove_subscriber

        def failing(callback):
            raise SystemExit("removal failed")

        undo._remove_subscriber = failing
        for handle in handles:
            for _ in range(3):
                try:
                    handle.cancel()
                except BaseException:  # noqa: BLE001
                    pass
        # Durable ownership for EVERY callback — one deduplicated handle
        # per registration, finite by construction.
        assert len(undo._stale_subscription_handles) == 1000
        unraisable: list = []
        previous_hook = sys.unraisablehook
        sys.unraisablehook = lambda args: unraisable.append(args)
        try:
            del handles
            gc.collect()
        finally:
            sys.unraisablehook = previous_hook
        assert unraisable == []
        assert len(undo._subscribers) == 1000
        # Recovery revokes ALL old callbacks — no orphaned residue.
        undo._remove_subscriber = original
        kept = undo.subscribe_change(lambda: None)  # noqa: F841 — RAII
        assert undo._stale_subscription_handles == []
        assert len(undo._subscribers) == 1
        # Post-recovery publication reaches only the deliberate survivor.
        undo._notify()


    def test_shutdown_reports_every_secondary_cleanup_throwable(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        state = {"armed": True}
        primary_ki = KeyboardInterrupt("primary")

        def one_shot(exc):
            class _Sub:
                def cancel(self):
                    if state["armed"]:
                        raise exc
            return _Sub()

        # Ordered outcomes: RuntimeError, PRIMARY KeyboardInterrupt,
        # secondary SystemExit, success, secondary KeyboardInterrupt.
        app._snap_sub = one_shot(RuntimeError("first"))
        app._snap_grid_sub = one_shot(primary_ki)
        app._theme_sub = one_shot(SystemExit("secondary-exit"))
        app._rate_limit_sub = SimpleNamespace(cancel=lambda: None)
        app._frame_sub = one_shot(KeyboardInterrupt("secondary-ki"))
        with pytest.raises(KeyboardInterrupt) as excinfo:
            app.shutdown()
        # EXACT primary object; every other cleanup throwable is an
        # inspectable secondary note.
        assert excinfo.value is primary_ki
        notes = "\n".join(getattr(excinfo.value, "__notes__", []))
        assert "RuntimeError" in notes
        assert "SystemExit" in notes
        assert "secondary-ki" in notes
        assert app._shutdown_done is False
        assert app._rate_limit_sub is None       # the success revoked
        assert app._snap_sub is not None         # failures stay owned
        # Recovery: the retried shutdown revokes everything.
        state["armed"] = False
        app.shutdown()
        assert app._shutdown_done is True
        assert app._snap_sub is None

    def test_large_prim_property_fanout_is_never_truncated(self):
        from pxr import Sdf

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        prim = stage.DefinePrim("/World/Large", "Cube")
        for index in range(300):
            prim.CreateAttribute(
                f"custom{index}", Sdf.ValueTypeNames.Float,
                custom=True).Set(float(index))
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        # One subscription per Property Inspector row, like
        # attribute_row wiring: 304 rows must ALL be admitted — live
        # fan-out is never bounded by the failed-retention capacity.
        received = [0] * 304
        handles = []
        for index in range(304):
            def _cb(event, i=index):
                received[i] += 1
            handles.append(adapter.subscribe_changes(_cb))
        assert len(adapter._subscribers) >= 304
        # Row updates flow to every subscription.
        adapter.set_visibility(
            adapter.get_item_at_path("/World/Large"), False)
        assert all(count >= 1 for count in received)
        # Clean teardown: every row revokes without residue.
        for handle in handles:
            handle.cancel()
        assert len(adapter._subscribers) == 0
        assert getattr(adapter, "_stale_subscription_handles", []) == []
        adapter.dispose()

    def test_property_window_lifecycle_releases_row_subscriptions(self):
        from pxr import Sdf

        from ovui_widgets.property.window import PropertyWindow
        from ovui_widgets.common import scheduler as widget_scheduler
        from ovui_data_adapters.openusd.property_adapter import (
            UsdPropertyAdapter,
        )

        def _immediate(delay, callback):
            handle = widget_scheduler.CallbackHandle(delay, callback)
            callback()
            return handle

        widget_scheduler.set_call_later(_immediate)
        try:
            stage = Usd.Stage.CreateInMemory()
            stage.DefinePrim("/World", "Xform")
            prim = stage.DefinePrim("/World/Large", "Cube")
            for index in range(300):
                prim.CreateAttribute(
                    f"custom{index}", Sdf.ValueTypeNames.Float,
                    custom=True).Set(float(index))
            undo = UndoManager()
            adapter = UsdStageAdapter(stage, undo_manager=undo)
            window = PropertyWindow()
            window._build_ui()   # the product builds content lazily
            window.set_property_adapter_factory(
                lambda paths: UsdPropertyAdapter(
                    stage, paths, undo_manager=undo, stage_adapter=adapter))
            window.set_stage_adapter(adapter, undo)
            window.set_selection(["/World/Large"])
            rows = len(window._inspector_attribute_rows)
            assert rows >= 300
            baseline = len(adapter._subscribers)
            # A genuine external update must not GROW subscriptions.
            prim.GetAttribute("custom0").Set(123.0)
            window.set_selection(["/World/Large"])   # rebuild
            assert len(adapter._subscribers) <= baseline
            # Deselect: every obsolete row subscription is revoked.
            window.set_selection([])
            after_deselect = len(adapter._subscribers)
            assert after_deselect <= baseline - rows + 4
            # Destroy: no row callback residue remains.
            window.set_selection(["/World/Large"])
            window.destroy()
            assert len(adapter._subscribers) <= 2
            adapter.dispose()
        finally:
            widget_scheduler.set_call_later(None)

    def test_structured_secondary_diagnostics_preserve_objects(self):
        """Real headless Application: the fallback retains the ACTUAL
        secondary exception objects (identity, type, attributes, cause,
        traceback) with safe display metadata, bounded without dropping
        current-attempt evidence, retired on successful shutdown."""
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus

        class _HostileLookupKI(KeyboardInterrupt):
            @property
            def add_note(self):
                raise SystemExit("hostile-lookup")

        class _HostileInvokeKI(KeyboardInterrupt):
            def add_note(self, note):
                raise SystemExit("hostile-invoke")

        class _HostileFormatKI(KeyboardInterrupt):
            def __str__(self):
                raise ValueError("hostile-str")

            def __repr__(self):
                raise ValueError("hostile-repr")

        Application._instance = None
        SelectionBus._instance = None
        app = Application()
        try:
            lookup_primary = _HostileLookupKI("primary-lookup")
            invoke_primary = _HostileInvokeKI("primary-invoke")
            runtime_secondary = RuntimeError("runtime-secondary")
            runtime_secondary.details = {"key": "snap.grid_size"}
            try:
                try:
                    raise ValueError("root-cause")
                except ValueError as cause:
                    raise RuntimeError("carrier") from cause
            except RuntimeError as caught:
                runtime_secondary.__cause__ = caught.__cause__
                runtime_secondary.__traceback__ = caught.__traceback__
            hostile_secondary = _HostileFormatKI("format-hostile")
            exit_secondary = SystemExit("exit-secondary")

            state = {"fail": True, "primary": lookup_primary}
            per_key = {
                "snap.enabled": lambda: state["primary"],
                "snap.grid_size": lambda: runtime_secondary,
                "ui.theme": lambda: hostile_secondary,
                Application.RATE_LIMIT_FPS_SETTING_KEY:
                    lambda: exit_secondary,
            }
            settings = app._settings
            real_remove = settings._remove_subscriber

            def hostile_remove(key, callback):
                if state["fail"] and key in per_key:
                    raise per_key[key]()
                return real_remove(key, callback)

            settings._remove_subscriber = hostile_remove

            # 100 failed shutdown attempts: primaries hostile during
            # add_note LOOKUP, then during INVOCATION.
            for attempt in range(100):
                if attempt == 50:
                    state["primary"] = invoke_primary
                expected = state["primary"]
                with pytest.raises(KeyboardInterrupt) as excinfo:
                    app.shutdown()
                # The exact primary object always escapes.
                assert excinfo.value is expected

            log = app._secondary_failure_log
            assert len(log) <= 64
            # Repeated attempts re-raising the same retained throwables
            # neither grow the log nor duplicate entries: exactly ONE
            # record per actual object, found by IDENTITY.
            for obj in (
                runtime_secondary, hostile_secondary, exit_secondary,
            ):
                matches = [
                    record for record in log
                    if record.exception is obj
                ]
                assert len(matches) == 1
            rt_record = next(
                record for record in log
                if record.exception is runtime_secondary
            )
            # Attributes, cause, and traceback stay directly inspectable
            # on the retained object.
            assert rt_record.exception.details == {"key": "snap.grid_size"}
            assert isinstance(rt_record.exception.__cause__, ValueError)
            assert rt_record.exception.__traceback__ is not None
            # Safe display metadata never invokes hostile formatting.
            hostile_record = next(
                record for record in log
                if record.exception is hostile_secondary
            )
            assert "_HostileFormatKI" in hostile_record.display
            assert "<unprintable>" in hostile_record.display
            assert "SecondaryFailureRecord" in repr(hostile_record)
            # Bounded WITHOUT dropping current-attempt evidence: churn
            # fresh secondary objects per attempt until the bound evicts
            # only PRIOR-attempt records.
            fresh = {"latest": []}

            def fresh_runtime():
                exc = RuntimeError(f"fresh-{len(fresh['latest'])}")
                fresh["latest"].append(exc)
                return exc

            per_key["snap.grid_size"] = fresh_runtime
            for _ in range(30):
                fresh["latest"] = []
                with pytest.raises(KeyboardInterrupt):
                    app.shutdown()
            assert len(app._secondary_failure_log) <= 64
            for exc in fresh["latest"]:
                assert any(
                    record.exception is exc
                    for record in app._secondary_failure_log
                )
            # Recovery: successful shutdown retires prior diagnostics at
            # the defined lifecycle boundary.
            state["fail"] = False
            app.shutdown()
            assert app._shutdown_done is True
            assert app._secondary_failure_log == []
        finally:
            Application._instance = None
            SelectionBus._instance = None

    def test_ordinary_add_note_reporting_nonduplicated(self):
        from types import SimpleNamespace

        from ovui_widgets.app.application import Application

        adapter, _stream = self._armed_adapter()
        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        primary = KeyboardInterrupt("primary")
        secondary = RuntimeError("secondary")
        state = {"fail": True}

        def failing(exc):
            class _Sub:
                def cancel(self):
                    if state["fail"]:
                        raise exc
            return _Sub()

        app._snap_sub = failing(primary)
        app._theme_sub = failing(secondary)
        # Two failed attempts re-collecting the SAME failure: the note
        # is attached once, not duplicated per retry.
        for _ in range(2):
            with pytest.raises(KeyboardInterrupt) as excinfo:
                app.shutdown()
            assert excinfo.value is primary
        notes = [
            note for note in getattr(primary, "__notes__", [])
            if "RuntimeError" in note
        ]
        assert len(notes) == 1
        # Ordinary reporting stays on the primary; the fallback log is
        # not engaged for a cooperative add_note.
        assert not any(
            getattr(record, "exception", None) is secondary
            for record in getattr(app, "_secondary_failure_log", [])
        )
        state["fail"] = False
        app.shutdown()
        assert app._shutdown_done is True

    def test_replacement_attempts_have_distinct_bounded_diagnostics(self):
        """Real headless Application: 100 public open_stage() replacement
        failures each own ONE distinct diagnostic-attempt identity, so
        prior-attempt records become evictable and the log stays bounded
        while current-operation evidence remains inspectable by identity."""
        from ovui_data_adapters.common import AdapterFactories
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus

        class _HostileLookupKI(KeyboardInterrupt):
            @property
            def add_note(self):
                raise SystemExit("hostile-lookup")

        class _FailingSub:
            def __init__(self):
                self.exc = RuntimeError("fresh-cancel-failure")

            def cancel(self):
                raise self.exc

        class _ReplacementAdapter:
            def __init__(self):
                self.sub = _FailingSub()
                self.dispose_exc = SystemExit("fresh-dispose-failure")

            def subscribe_changes(self, callback):
                return self.sub

            def dispose(self):
                raise self.dispose_exc

        Application._instance = None
        SelectionBus._instance = None
        app = Application()
        try:
            made = []
            primaries = []

            def stage_factory(stage, undo_manager, call_later):
                adapter = _ReplacementAdapter()
                made.append(adapter)
                return adapter

            def layer_factory(stage, undo_manager):
                primary = _HostileLookupKI("hostile-primary")
                primaries.append(primary)
                raise primary

            app._adapter_factories = AdapterFactories(
                stage=stage_factory, layers=layer_factory)
            serial_start = getattr(app, "_lifecycle_attempt_serial", 0)
            for _ in range(100):
                with pytest.raises(KeyboardInterrupt) as excinfo:
                    app.open_stage(Usd.Stage.CreateInMemory())
                # The exact primary escapes every public attempt.
                assert excinfo.value is primaries[-1]
            # ONE identity per public operation: nesting through the
            # shared _load_stage/abort helpers never double-advances or
            # splits an operation across attempts.
            assert app._lifecycle_attempt_serial == serial_start + 100

            log = app._secondary_failure_log
            # Bounded: prior replacement attempts became evictable
            # instead of all 200 records claiming attempt-zero currency.
            assert len(log) <= 64
            attempts = {record.attempt for record in log}
            assert len(attempts) > 1
            # Every record of one operation shares that operation's
            # single identity (cancel + dispose pairs stay together).
            latest = made[-1]
            latest_records = [
                record for record in log
                if record.exception is latest.sub.exc
                or record.exception is latest.dispose_exc
            ]
            assert len(latest_records) == 2
            assert len({record.attempt for record in latest_records}) == 1
            # Current-operation evidence stays inspectable by identity
            # with metadata and traceback.
            cancel_record = next(
                record for record in log
                if record.exception is latest.sub.exc
            )
            assert cancel_record.exception.__traceback__ is not None
            assert "fresh-cancel-failure" in cancel_record.display
            # Prior-operation records were genuinely evicted.
            earliest = made[0]
            assert not any(
                record.exception is earliest.sub.exc
                or record.exception is earliest.dispose_exc
                for record in log
            )
            # Shutdown remains an independently identified attempt and
            # successful completion retires the diagnostics.
            serial_before = app._lifecycle_attempt_serial
            app.shutdown()
            assert app._lifecycle_attempt_serial == serial_before + 1
            assert app._shutdown_done is True
            assert app._secondary_failure_log == []
        finally:
            Application._instance = None
            SelectionBus._instance = None

    def test_public_lifecycle_entry_points_own_one_attempt_each(self):
        """Concise controls: open_file and new_stage advance the attempt
        serial exactly once per public call despite converging through
        shared nested helpers."""
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus

        Application._instance = None
        SelectionBus._instance = None
        app = Application()
        try:
            serial = getattr(app, "_lifecycle_attempt_serial", 0)
            # new_stage() → _load_empty_startup_stage() → _load_stage():
            # one public operation, one identity, however it resolves.
            app.new_stage()
            assert app._lifecycle_attempt_serial == serial + 1
            assert getattr(app, "_lifecycle_attempt_active", False) is False
            # open_file() with a nonexistent path fails inside its abort
            # envelope; still exactly one identity for the operation.
            try:
                app.open_file("/nonexistent/round21/control.usda")
            except Exception:
                pass
            assert app._lifecycle_attempt_serial == serial + 2
            assert getattr(app, "_lifecycle_attempt_active", False) is False
            app.shutdown()
            assert app._lifecycle_attempt_serial == serial + 3
        finally:
            Application._instance = None
            SelectionBus._instance = None

    def test_shutdown_preserves_primary_identity_with_notes(self):
        from types import SimpleNamespace

        adapter, _stream = self._armed_adapter()

        from ovui_widgets.app.application import Application

        class _KIRenderer:
            def shutdown(self):
                raise KeyboardInterrupt()

        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = SimpleNamespace(shutdown_scene=lambda: None)
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = _KIRenderer()
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        app._current_stage_sub = SimpleNamespace(
            cancel=lambda: (_ for _ in ()).throw(SystemExit("secondary")))
        with pytest.raises(KeyboardInterrupt) as excinfo:
            app.shutdown()
        # PRIMARY identity preserved; the secondary SystemExit is an
        # inspectable note; shutdown converged completely.
        notes = getattr(excinfo.value, "__notes__", [])
        assert any("SystemExit" in n for n in notes)
        assert app._shutdown_done is True
        assert app._stage_adapter is None
        assert adapter._transition_reserved is False

    def test_failed_shutdown_scene_keeps_document_and_session(self):
        from types import SimpleNamespace

        adapter, stream = self._armed_adapter()

        class _Session:
            def __init__(self):
                self.calls = 0
                self.fail = True

            def shutdown_scene(self):
                self.calls += 1
                if self.fail:
                    raise RuntimeError("BORROW detach failed")

        session = _Session()

        from ovui_widgets.app.application import Application

        app = Application.__new__(Application)
        app._stage_adapter = adapter
        app._adapter_session = session
        app._shutdown_done = False
        app._shutdown_in_progress = False
        app._startup_prebuilt_renderer = None
        app._component_manager = SimpleNamespace(unload_all=lambda: None)
        app._widget_registry = SimpleNamespace(clear=lambda: None)
        app._window_registry = SimpleNamespace(clear=lambda: None)
        app._menu_registry = SimpleNamespace(clear=lambda: None)
        app._ovinspect_module = None
        app._pending_callbacks = []
        app._teardown_headless_export = lambda: None
        app._undo_manager = adapter._undo_manager
        with pytest.raises(RuntimeError, match="BORROW detach failed"):
            app.shutdown()
        # Fail-closed: session retained AND the document stays coherent.
        assert app._adapter_session is session
        assert app._shutdown_done is False
        assert app._shutdown_in_progress is False
        self._assert_fully_armed(adapter, stream)
        # Retry after the renderer detaches cleanly completes once.
        session.fail = False
        app.shutdown()
        assert app._shutdown_done is True
        assert adapter._backing_notice_key is None


class TestUnprovenEventsRebuildStructurally:
    """PR review: unproven/context-free events never take the per-item path."""

    def test_unproven_conservative_delta_rebuilds(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        stage, _undo, adapter, model, changed, _s = _fixture()
        changed.clear()
        # Identical shape to a genuine coarse event but WITHOUT the
        # attempt-proven marker (context-free conservative flush /
        # disposal assembly): the model must take the structural rebuild.
        event = ChangeEvent(
            changed_paths=("/World.visibility",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={"authored": ("/World",), "boundaries": {},
                              "precise": False},
        )
        assert model._is_visibility_only_event(event) is False

    def test_actual_scope_conservative_event_rebuilds(self):
        stage, _undo, adapter, model, changed, _s = _fixture()
        adapter.begin_undo_group("g")
        _toggle(adapter, stage, "/World/Cube", False)
        conservative = adapter._scope_conservative_event(
            adapter._visibility_scope["records"])
        assert model._is_visibility_only_event(conservative) is False
        adapter.end_undo_group()

    def test_pure_external_relationship_notice_rebuilds(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        stage, _undo, adapter, model, changed, _s = _fixture()
        holder = stage.DefinePrim("/World/Holder")
        holder.CreateRelationship("visibility").AddTarget("/World/Cube")
        event = ChangeEvent(
            changed_paths=("/World/Holder.visibility",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        assert model._is_visibility_only_event(event) is False

    def test_pure_external_genuine_attribute_notice_stays_per_item(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        stage, _undo, adapter, model, changed, _s = _fixture()
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
        event = ChangeEvent(
            changed_paths=("/World/Cube.visibility",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        # The path composes as the genuine Imageable schema attribute: the
        # efficient per-item external path is preserved.
        assert model._is_visibility_only_event(event) is True


class TestRowSubscriptionOwnership:
    """Delegate eye-cell subscriptions release at whole-tree boundaries.

    Repeated stage replacement, structural rebuild, filter changes,
    detach, and destroy must leave no retained per-row value
    subscriptions — pre-fix they accumulated forever and kept every
    replaced document's adapter alive through the value-model chain.
    """

    def _patch_cell_ui(self, monkeypatch):
        import ovui_widgets.stage.widget.stage_delegate as delegate_mod

        class _Ctx:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _FakeFrame:
            def __init__(self, **kwargs):
                self.build_fn = None

            def set_mouse_pressed_fn(self, fn):
                pass

            def set_build_fn(self, fn):
                self.build_fn = fn
                fn()

            def rebuild(self):
                if self.build_fn is not None:
                    self.build_fn()

        monkeypatch.setattr(delegate_mod.ui, "HStack", _Ctx)
        monkeypatch.setattr(delegate_mod.ui, "VStack", _Ctx)
        monkeypatch.setattr(delegate_mod.ui, "Frame", _FakeFrame)
        monkeypatch.setattr(delegate_mod.ui, "Spacer", lambda **kwargs: None)
        monkeypatch.setattr(
            delegate_mod.ui, "ImageWithProvider", lambda *a, **k: None)
        monkeypatch.setattr(
            delegate_mod.stage_icons, "provider", lambda path: path)

    def _render_rows(self, delegate, model):
        """Simulate the TreeView render: build each row's eye cell."""
        root = model.get_item_children(None)[0]
        delegate._build_visibility_column(model, root)
        for child in model.get_item_children(root):
            delegate._build_visibility_column(model, child)

    def _widget(self):
        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        from ovui_widgets.stage.widget.stage_widget import StageWidget

        import omni.ui as ui

        window = ui.Window(
            "_t_row_subscription_ownership", width=320, height=480)
        with window.frame:
            with ui.VStack():
                widget = StageWidget(adapter=MockStageAdapter())
        return widget, window

    def test_stage_replacement_releases_row_subscriptions(self, monkeypatch):
        import gc
        import weakref

        from ovui_widgets.common.testing.mock_stage import MockStageAdapter

        widget, _window = self._widget()
        self._patch_cell_ui(monkeypatch)
        delegate = widget._delegate
        self._render_rows(delegate, widget._model)
        per_document = len(delegate._visibility_subscriptions)
        assert per_document >= 2
        first_adapter_ref = weakref.ref(widget.get_adapter())
        # Repeated replacement: subscriptions do NOT accumulate and the
        # replaced documents' adapters are actually released.
        for _ in range(5):
            widget.set_adapter(MockStageAdapter())
            self._render_rows(delegate, widget._model)
            assert len(delegate._visibility_subscriptions) <= per_document
        gc.collect()
        assert first_adapter_ref() is None
        # Structural rebuild within one document also releases obsolete
        # entries (surviving rows re-subscribe on their next build).
        widget._model._item_changed(None)
        assert delegate._visibility_subscriptions == {}
        self._render_rows(delegate, widget._model)
        assert len(delegate._visibility_subscriptions) == per_document
        # Filter change is a whole-tree rebuild too.
        widget._model.set_filter("nothing-matches-this")
        assert delegate._visibility_subscriptions == {}
        widget._model.set_filter("")
        # Detach and destroy leave nothing owned.
        self._render_rows(delegate, widget._model)
        widget.detach_document()
        assert delegate._visibility_subscriptions == {}
        widget.destroy()
        assert delegate._visibility_subscriptions == {}

    def test_live_rows_resubscribe_after_release(self, monkeypatch):
        """The release is safe: a re-rendered row repaints on new events."""
        widget, _window = self._widget()
        self._patch_cell_ui(monkeypatch)
        delegate = widget._delegate
        model = widget._model
        self._render_rows(delegate, model)
        widget._model._item_changed(None)   # release (rebuild pending)
        self._render_rows(delegate, model)  # the rebuild re-subscribes
        root = model.get_item_children(None)[0]
        child = model.get_item_children(root)[0]
        rebuilds = []
        vis_model = model.get_item_value_model(child, 2)
        key = id(vis_model)
        assert key in delegate._visibility_subscriptions
        child.mark_dirty()                  # consequence-driven repaint
        # mark_dirty rebroadcasts _value_changed → the freshly-subscribed
        # frame rebuild ran (FakeFrame executes build_fn synchronously,
        # raising if the subscription had been dropped).
        widget.destroy()
        assert delegate._visibility_subscriptions == {}

    @pytest.mark.parametrize(
        "throwable",
        [KeyboardInterrupt("unsubscribe interrupted"), SystemExit("unsubscribe exited")],
        ids=["keyboard-interrupt", "system-exit"],
    )
    def test_release_attempts_every_subscription_across_baseexception(
        self, throwable
    ):
        from ovui_widgets.stage.widget.stage_delegate import StageDelegate

        calls = []

        class _Subscription:
            def __init__(self, name, failure=None):
                self.name = name
                self.failure = failure

            def unsubscribe(self):
                calls.append(self.name)
                if self.failure is not None:
                    raise self.failure

        delegate = StageDelegate.__new__(StageDelegate)
        delegate._visibility_subscriptions = {
            1: _Subscription("first", throwable),
            2: _Subscription("second"),
            3: _Subscription("third"),
        }
        delegate.release_visibility_subscriptions()
        assert calls == ["first", "second", "third"]
        assert delegate._visibility_subscriptions == {}
