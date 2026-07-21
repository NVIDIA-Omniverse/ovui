# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

from types import SimpleNamespace

from ovui_data_adapters.common import ChangeEvent, ChangeEventType

from ovui_widgets.app.application import Application
from ovui_widgets.common.selection import SelectionBus


class _PathsAdapter:
    def __init__(self, paths: set[str]) -> None:
        self.paths = paths

    def get_item_at_path(self, path: str):
        return path if path in self.paths else None


def _app(paths: set[str], selected: list[str]):
    bus = SelectionBus()
    bus.publish(selected, source="test")
    return SimpleNamespace(
        _stage_adapter=_PathsAdapter(paths),
        _selection_bus=bus,
    )


def _resync(*paths: str) -> ChangeEvent:
    return ChangeEvent((), tuple(paths), ChangeEventType.RESYNC)


def test_resync_remaps_selected_rename_by_same_parent() -> None:
    app = _app({"/World/Renamed"}, ["/World/Box"])

    Application._reconcile_selection_after_resync(
        app,
        _resync("/World/Renamed"),
    )

    assert app._selection_bus.get_snapshot().paths() == ["/World/Renamed"]


def test_resync_remaps_selected_reparent_by_same_leaf_name() -> None:
    app = _app({"/World/B/Box"}, ["/World/A/Box"])

    Application._reconcile_selection_after_resync(
        app,
        _resync("/World/B/Box"),
    )

    assert app._selection_bus.get_snapshot().paths() == ["/World/B/Box"]


def test_resync_remaps_selected_descendant_when_old_and_new_roots_are_reported() -> None:
    app = _app(
        {"/World/Renamed", "/World/Renamed/Child"},
        ["/World/Group/Child"],
    )

    Application._reconcile_selection_after_resync(
        app,
        _resync("/World/Group", "/World/Renamed"),
    )

    assert app._selection_bus.get_snapshot().paths() == [
        "/World/Renamed/Child"
    ]


def test_resync_clears_deleted_selection_without_guessing() -> None:
    app = _app({"/World"}, ["/World/Deleted"])

    Application._reconcile_selection_after_resync(
        app,
        _resync("/World/Deleted"),
    )

    assert app._selection_bus.get_snapshot().paths() == []


def test_history_reconcile_restores_rename_after_tree_clears_selection() -> None:
    bus = SelectionBus()
    # This is the ordering observed from native TreeView: undo has committed,
    # but the stale selected HierarchyItem publishes [] before deferred RESYNC
    # subscribers receive the old and new namespace paths.
    bus.publish([], source="stage")
    app = SimpleNamespace(
        _stage_adapter=_PathsAdapter({"/World/Box"}),
        _selection_bus=bus,
        _history_selection_reconcile={
            "generation": 7,
            "selected": ("/World/Renamed",),
            "event_paths": [],
        },
        _stage_change_listeners=[],
        _viewport_window=None,
        _layer_window=None,
    )

    # OVStage may split the two namespace sides across separate notices.
    Application._on_stage_changed(app, _resync("/World/Box"))
    Application._on_stage_changed(app, _resync("/World/Renamed"))
    Application._finish_history_selection_reconcile(app, 7)

    assert bus.get_snapshot().paths() == ["/World/Box"]
    assert app._history_selection_reconcile is None


def test_history_reconcile_restores_reparent_by_leaf_after_tree_clear() -> None:
    bus = SelectionBus()
    bus.publish([], source="stage")
    app = SimpleNamespace(
        _stage_adapter=_PathsAdapter({"/World/A/Box"}),
        _selection_bus=bus,
        _history_selection_reconcile={
            "generation": 11,
            "selected": ("/World/B/Box",),
            "event_paths": ["/World/B/Box", "/World/A/Box"],
        },
    )

    Application._finish_history_selection_reconcile(app, 11)

    assert bus.get_snapshot().paths() == ["/World/A/Box"]


def test_split_reparent_resync_defers_clear_until_added_path_arrives() -> None:
    bus = SelectionBus()
    source = "/World/A/Box"
    target = "/World/B/Box"
    bus.publish([source], source="stage")
    callbacks = []
    app = Application.__new__(Application)
    app._stage_adapter = _PathsAdapter({target})
    app._selection_bus = bus
    app._history_selection_reconcile = None
    app._deferred_selection_reconcile = None
    app._deferred_selection_generation = 0
    app._stage_change_listeners = []
    app._viewport_window = None
    app._layer_window = None
    app.call_later = lambda _delay, callback: callbacks.append(callback)

    Application._on_stage_changed(app, _resync(source))
    assert bus.get_snapshot().paths() == [source]
    assert len(callbacks) == 1

    # Match native TreeView's stale-item callback before Application receives
    # the added half of the same namespace transaction.
    bus.publish([], source="stage")
    Application._on_stage_changed(app, _resync(target))
    callbacks.pop()()

    assert bus.get_snapshot().paths() == [target]
