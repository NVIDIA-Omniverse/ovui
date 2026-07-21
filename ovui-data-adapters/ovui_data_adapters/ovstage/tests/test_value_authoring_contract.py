# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""OVStage-native committed value-authoring contracts."""

from __future__ import annotations

import math
import contextlib
from pathlib import Path
import sys
from typing import Any, Iterator

import pytest

from ovui_data_adapters.common import (
    BindMaterialRequest,
    ChangeEventType,
    CreateRequest,
    VisibilityState,
)
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.provider import (
    create_property_adapter,
    create_provider_session,
    create_stage_adapter,
    create_transform_adapter,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.services.transforms import BatchTransformCommand
from ovui_data_adapters.services.undo import UndoManager


_SCENE = '''#usda 1.0
(
    upAxis = "Z"
)

def Xform "World"
{
    def Xform "Parent"
    {
        double3 xformOp:translate = (2, 3, 4)
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Mesh "MeshA"
        {
            bool doubleSided = false
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0, 1, 2]
            point3f[] points = [(0, 0, 0), (3, 0, 0), (0, 2, 0)]
            rel material:binding = </World/Looks/MaterialA>
        }
        def Mesh "MeshB"
        {
            bool doubleSided = true
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0, 1, 2]
            point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        }
    }
    def Scope "Looks"
    {
        def Material "MaterialA" {}
        def Material "MaterialB" {}
    }
    def Camera "CameraA"
    {
        float focalLength = 24
    }
    def Camera "CameraB"
    {
        float focalLength = 50
    }
    def RenderVar "Beauty"
    {
        token sourceName = "color"
    }
    def RenderVar "Depth"
    {
        token sourceName = "depth"
    }
    def RenderProduct "Product"
    {
        rel camera = </World/CameraA>
        rel orderedVars = [</World/Beauty>, </World/Depth>]
        int2 resolution = (640, 360)
    }
}
'''

_REPLACEMENT = '''#usda 1.0
def Xform "Replacement"
{
    def Camera "OtherCamera"
    {
        float focalLength = 18
    }
}
'''


@pytest.fixture(scope="module")
def ovstage_runtime() -> Any:
    package_parent = Path(__file__).resolve().parents[2]
    previous_paths = list(sys.path)
    loaded = sys.modules.get("ovstage")
    if loaded is not None and not callable(getattr(loaded, "Stage", None)):
        sys.modules.pop("ovstage", None)
    sys.path[:] = [
        entry
        for entry in sys.path
        if not entry or Path(entry).resolve() != package_parent
    ]
    try:
        return load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )
    finally:
        sys.path[:] = previous_paths


@pytest.fixture()
def opened(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, Any, Any, UndoManager]]:
    scene_path = tmp_path / "authoring.usda"
    scene_path.write_text(_SCENE, encoding="utf-8")
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_path))
    undo = UndoManager()
    stage = create_stage_adapter(scene, undo)
    try:
        yield session, scene, stage, undo
    finally:
        session.shutdown_scene()


def _property(
    scene: Any,
    stage: Any,
    undo: UndoManager,
    *paths: str,
) -> Any:
    return create_property_adapter(scene, list(paths), undo, stage)


def _edit(adapter: Any, name: str, value: Any) -> None:
    adapter.begin_edit(name)
    try:
        adapter.set_value(name, value)
    finally:
        adapter.end_edit(name)


def _event_tuple(event: Any) -> tuple[Any, ...]:
    return (
        event.event_type,
        event.changed_paths,
        event.resynced_paths,
        event.source,
    )


def test_metadata_matches_exact_native_write_support(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    mesh = _property(scene, stage, undo, "/World/Parent/MeshA")
    camera = _property(scene, stage, undo, "/World/CameraA")
    beauty = _property(scene, stage, undo, "/World/Beauty")

    for name in ("doubleSided", "points", "material:binding", "visibility"):
        assert mesh.get_attribute_metadata(name).is_locked is False
    assert camera.get_attribute_metadata("focalLength").is_locked is False
    assert camera.get_attribute_metadata("projection").is_locked is False
    assert beauty.get_attribute_metadata("sourceName").is_locked is False
    for name in ("localMatrix", "worldMatrix"):
        assert mesh.get_attribute_metadata(name).is_locked is True
    assert "usd-prim-type" not in mesh.get_attribute_names()


def test_edit_session_is_one_frame_one_event_and_exact_undo_redo(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    camera = _property(scene, stage, undo, "/World/CameraA")
    events = []
    subscription = stage.subscribe_changes(events.append)
    before_ordinal = scene.current_ordinal
    try:
        _edit(camera, "focalLength", 42.5)
        assert camera.get_value("focalLength") == pytest.approx(42.5)
        assert scene.current_ordinal == before_ordinal + 1
        assert [_event_tuple(event) for event in events] == [
            (
                ChangeEventType.INFO_CHANGE,
                ("/World/CameraA",),
                (),
                "property:set",
            )
        ]
        assert scene.change_stream.poll() == ()

        assert undo.undo() is True
        assert camera.get_value("focalLength") == pytest.approx(24.0)
        assert len(events) == 2
        assert events[-1].source == "property:set"
        assert undo.redo() is True
        assert camera.get_value("focalLength") == pytest.approx(42.5)
        assert len(events) == 3
    finally:
        subscription.cancel()


def test_bool_token_string_and_arrays_round_trip_defensively(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    mesh = _property(scene, stage, undo, "/World/Parent/MeshA")
    camera = _property(scene, stage, undo, "/World/CameraA")
    beauty = _property(scene, stage, undo, "/World/Beauty")

    _edit(mesh, "doubleSided", True)
    _edit(camera, "projection", "orthographic")
    _edit(beauty, "sourceName", "Café_Δ")
    points = ((0.0, 0.0, 0.0), (2.0, -1.0, 3.0), (4.0, 5.0, 6.0))
    _edit(mesh, "points", points)

    assert mesh.get_value("doubleSided") is True
    assert camera.get_value("projection") == "orthographic"
    assert beauty.get_value("sourceName") == "Café_Δ"
    copied = mesh.get_value("points")
    assert copied == points
    assert isinstance(copied, tuple)


def test_representative_numeric_fixed_and_token_array_layouts_round_trip(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    mesh = _property(scene, stage, undo, "/World/Parent/MeshA")
    camera = _property(scene, stage, undo, "/World/CameraA")
    product = _property(scene, stage, undo, "/World/Product")

    _edit(mesh, "refinementLevel", 3)
    _edit(mesh, "faceVertexIndices", (2, 1, 0))
    _edit(mesh, "timeVaryingAttributes", ("points", "visibility"))
    _edit(camera, "shutter:open", 0.25)
    _edit(camera, "clippingRange", (0.5, 5000.0))
    _edit(product, "resolution", (800, 450))
    _edit(product, "dataWindowNDC", (0.1, 0.2, 0.9, 0.8))

    assert mesh.get_value("refinementLevel") == 3
    assert mesh.get_value("faceVertexIndices") == (2, 1, 0)
    assert mesh.get_value("timeVaryingAttributes") == ("points", "visibility")
    assert camera.get_value("shutter:open") == pytest.approx(0.25)
    assert camera.get_value("clippingRange") == pytest.approx((0.5, 5000.0))
    assert product.get_value("resolution") == (800, 450)
    assert product.get_value("dataWindowNDC") == pytest.approx((0.1, 0.2, 0.9, 0.8))


def test_multi_selection_write_is_atomic_and_restores_mixed_values(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    cameras = _property(scene, stage, undo, "/World/CameraA", "/World/CameraB")
    events = []
    subscription = stage.subscribe_changes(events.append)
    before = scene.current_ordinal
    try:
        assert cameras.is_ambiguous("focalLength") is True
        _edit(cameras, "focalLength", 35.0)
        assert cameras.get_value("focalLength") == pytest.approx(35.0)
        assert scene.current_ordinal == before + 1
        assert len(events) == 1
        assert events[0].changed_paths == ("/World/CameraA", "/World/CameraB")
        assert undo.undo() is True
        first = _property(scene, stage, undo, "/World/CameraA")
        second = _property(scene, stage, undo, "/World/CameraB")
        assert first.get_value("focalLength") == pytest.approx(24.0)
        assert second.get_value("focalLength") == pytest.approx(50.0)
    finally:
        subscription.cancel()


def test_relationship_set_reorder_clear_and_validation(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    product = _property(scene, stage, undo, "/World/Product")
    mesh = _property(scene, stage, undo, "/World/Parent/MeshA")

    _edit(product, "orderedVars", ("/World/Depth", "/World/Beauty"))
    assert product.get_value("orderedVars") == ("/World/Depth", "/World/Beauty")
    _edit(mesh, "material:binding", ("/World/Looks/MaterialB",))
    assert mesh.get_value("material:binding") == ("/World/Looks/MaterialB",)
    _edit(product, "orderedVars", ())
    assert product.get_value("orderedVars") == ()

    before = (scene.current_ordinal, undo.can_undo(), mesh.get_value("material:binding"))
    with pytest.raises(ValueError, match="current native target"):
        _edit(mesh, "material:binding", ("/World/Looks/Missing",))
    assert (scene.current_ordinal, undo.can_undo(), mesh.get_value("material:binding")) == before
    with pytest.raises(ValueError, match="duplicate"):
        _edit(product, "orderedVars", ("/World/Beauty", "/World/Beauty"))
    with pytest.raises(ValueError, match="must be native Material"):
        _edit(mesh, "material:binding", ("/World/CameraA",))


def test_material_binding_surface_and_create_bind_action_are_real(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    mesh_path = "/World/Parent/MeshA"
    unbound_path = "/World/Parent/MeshB"
    result = stage.bind_material(
        BindMaterialRequest(
            material_path="/World/Looks/MaterialB",
            selection_paths=(mesh_path, unbound_path),
        )
    )
    assert result.accepted is True
    assert result.bound_prim_paths == (mesh_path, unbound_path)
    assert _property(scene, stage, undo, mesh_path).get_value("material:binding") == (
        "/World/Looks/MaterialB",
    )
    assert _property(scene, stage, undo, unbound_path).get_value("material:binding") == (
        "/World/Looks/MaterialB",
    )
    before_noop = scene.current_ordinal
    repeated = stage.bind_material(
        BindMaterialRequest(
            material_path="/World/Looks/MaterialB",
            selection_paths=(mesh_path, unbound_path),
        )
    )
    assert repeated.accepted is True
    assert scene.current_ordinal == before_noop

    action = stage.list_create_actions(selection_paths=(mesh_path,)).action(
        "create.material.usd-preview-surface.bind"
    )
    assert action is not None and action.is_available
    created = stage.create_prim(
        CreateRequest(
            action.action_id,
            selection_paths=(mesh_path,),
            requested_name="BoundMaterial",
        )
    )
    assert created.accepted is True
    assert created.binding_applied is True
    assert created.metadata["native_relationship_binding"] is True
    assert _property(scene, stage, undo, mesh_path).get_value("material:binding") == (
        created.primary_path,
    )
    assert undo.undo() is True
    assert stage.get_item_at_path(created.primary_path) is None
    assert _property(scene, stage, undo, mesh_path).get_value("material:binding") == (
        "/World/Looks/MaterialB",
    )
    assert undo.undo() is True
    assert _property(scene, stage, undo, mesh_path).get_value("material:binding") == (
        "/World/Looks/MaterialA",
    )
    assert _property(scene, stage, undo, unbound_path).get_value(
        "material:binding"
    ) == ()
    assert undo.redo() is True
    assert undo.redo() is True
    assert stage.get_item_at_path(created.primary_path) is not None


def test_visibility_property_and_stage_surface_share_exact_semantics(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    path = "/World/Parent/MeshA"
    item = stage.get_item_at_path(path)
    prop = _property(scene, stage, undo, path)
    assert item is not None
    events = []
    subscription = stage.subscribe_changes(events.append)
    try:
        _edit(prop, "visibility", "invisible")
        assert prop.get_value("visibility") == "invisible"
        assert stage.compute_visibility(item) is VisibilityState.INVISIBLE
        assert len(events) == 1
        assert events[-1].source == "property:set"
        assert scene.change_stream.poll() == ()

        stage.set_visibility(item, True)
        assert stage.compute_visibility(item) is VisibilityState.VISIBLE
        assert len(events) == 2
        assert events[-1].source == "ovstage:visibility"
        assert undo.undo() is True
        assert stage.compute_visibility(item) is VisibilityState.INVISIBLE
        assert len(events) == 3
        state = (scene.current_ordinal, len(events), undo.can_undo())
        with pytest.raises(ValueError, match="visibility expects"):
            prop.set_value("visibility", "visible")
        assert (scene.current_ordinal, len(events), undo.can_undo()) == state
    finally:
        subscription.cancel()


def test_multi_selection_visibility_is_one_frame_history_and_event(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    first = stage.get_item_at_path("/World/Parent/MeshA")
    second = stage.get_item_at_path("/World/Parent/MeshB")
    assert first is not None and second is not None
    events = []
    subscription = stage.subscribe_changes(events.append)
    before = scene.current_ordinal
    try:
        stage.begin_undo_group("Hide selected")
        stage.set_visibility(first, False)
        stage.set_visibility(second, False)
        stage.end_undo_group()
        assert scene.current_ordinal == before + 1
        assert stage.compute_visibility(first) is VisibilityState.INVISIBLE
        assert stage.compute_visibility(second) is VisibilityState.INVISIBLE
        assert len(events) == 1
        assert events[0].changed_paths == (
            "/World/Parent/MeshA",
            "/World/Parent/MeshB",
        )
        assert undo.undo() is True
        assert stage.compute_visibility(first) is VisibilityState.VISIBLE
        assert stage.compute_visibility(second) is VisibilityState.VISIBLE
        assert len(events) == 2
        assert undo.redo() is True
        assert len(events) == 3
    finally:
        subscription.cancel()


def test_failed_grouped_member_aborts_without_write_history_or_event(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    first = stage.get_item_at_path("/World/Parent/MeshA")
    assert first is not None
    events = []
    subscription = stage.subscribe_changes(events.append)
    before = (scene.current_ordinal, undo.can_undo())
    try:
        stage.begin_undo_group("Hide selected")
        stage.set_visibility(first, False)
        try:
            # The root item is not visibility-editable: the member fails.
            stage.set_visibility(stage.get_root(), False)
        except NotImplementedError:
            stage.abort_undo_group()
        else:  # pragma: no cover - the member must fail
            raise AssertionError("root visibility write must be rejected")
        assert (scene.current_ordinal, undo.can_undo()) == before
        assert events == []
        assert stage.compute_visibility(first) is VisibilityState.VISIBLE
        # The group token is fully closed: a fresh group works normally.
        stage.begin_undo_group("Hide selected retry")
        stage.set_visibility(first, False)
        stage.end_undo_group()
        assert stage.compute_visibility(first) is VisibilityState.INVISIBLE
        assert len(events) == 1
        assert undo.undo() is True
        assert stage.compute_visibility(first) is VisibilityState.VISIBLE
    finally:
        subscription.cancel()


def test_faulty_observer_keeps_visibility_committed_and_undoable(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    item = stage.get_item_at_path("/World/Parent/MeshA")
    assert item is not None
    events = []
    subscriptions = (
        stage.subscribe_changes(
            lambda _event: (_ for _ in ()).throw(RuntimeError("observer"))
        ),
        stage.subscribe_changes(events.append),
    )
    try:
        # A failing semantic observer must not fail the committed write,
        # starve later observers, or leave the edit unundoable.
        stage.set_visibility(item, False)
        assert stage.compute_visibility(item) is VisibilityState.INVISIBLE
        assert len(events) == 1
        failures = getattr(scene.change_stream, "delivery_failures", [])
        assert failures and isinstance(failures[-1], RuntimeError)
        assert undo.can_undo() is True
        assert undo.undo() is True
        assert stage.compute_visibility(item) is VisibilityState.VISIBLE
        assert len(events) == 2
        assert undo.redo() is True
        assert stage.compute_visibility(item) is VisibilityState.INVISIBLE
        assert len(events) == 3
    finally:
        for subscription in subscriptions:
            subscription.cancel()


def test_interrupting_observer_stays_caller_visible_with_consistent_history(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    item = stage.get_item_at_path("/World/Parent/MeshA")
    assert item is not None
    events = []
    subscriptions = (
        stage.subscribe_changes(
            lambda _event: (_ for _ in ()).throw(KeyboardInterrupt("observer"))
        ),
        stage.subscribe_changes(events.append),
    )
    try:
        # PUSH edge: the interrupt defers past the history recording (the
        # committed write gets its entry, later observers were attempted)
        # and then reaches the caller — with the edge-internal mark
        # already consumed, so the received object can be reused freely.
        with pytest.raises(KeyboardInterrupt) as push_interrupt:
            stage.set_visibility(item, False)
        assert not getattr(
            push_interrupt.value, "_ovui_history_consistent", False
        )
        assert stage.compute_visibility(item) is VisibilityState.INVISIBLE
        assert len(events) == 1
        failures = getattr(scene.change_stream, "delivery_failures", [])
        assert failures and isinstance(failures[-1], KeyboardInterrupt)
        assert undo.can_undo() is True
        # UNDO edge: the entry moves to the redo stack BEFORE the
        # interrupt surfaces — never a committed edge without history.
        with pytest.raises(KeyboardInterrupt):
            undo.undo()
        assert stage.compute_visibility(item) is VisibilityState.VISIBLE
        assert len(events) == 2
        assert undo.can_undo() is False
        assert undo.can_redo() is True
        # REDO edge likewise.
        with pytest.raises(KeyboardInterrupt):
            undo.redo()
        assert stage.compute_visibility(item) is VisibilityState.INVISIBLE
        assert len(events) == 3
        assert undo.can_undo() is True
    finally:
        for subscription in subscriptions:
            subscription.cancel()
    # With the interrupting observer gone, the recorded history replays.
    assert undo.undo() is True
    assert stage.compute_visibility(item) is VisibilityState.VISIBLE


def test_interrupting_observer_grouped_finalization_records_history(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    first = stage.get_item_at_path("/World/Parent/MeshA")
    second = stage.get_item_at_path("/World/Parent/MeshB")
    assert first is not None and second is not None
    events = []
    subscriptions = (
        stage.subscribe_changes(
            lambda _event: (_ for _ in ()).throw(KeyboardInterrupt("observer"))
        ),
        stage.subscribe_changes(events.append),
    )
    try:
        stage.begin_undo_group("Hide selected")
        stage.set_visibility(first, False)
        stage.set_visibility(second, False)
        # Grouped finalization: the group commits (state applied, one
        # recorded entry, one event) and the interrupt stays visible —
        # unmarked, since the adapter consumed the edge-internal mark.
        with pytest.raises(KeyboardInterrupt) as interrupt:
            stage.end_undo_group()
        assert not getattr(interrupt.value, "_ovui_history_consistent", False)
        assert stage.compute_visibility(first) is VisibilityState.INVISIBLE
        assert stage.compute_visibility(second) is VisibilityState.INVISIBLE
        assert len(events) == 1
        assert undo.can_undo() is True
    finally:
        for subscription in subscriptions:
            subscription.cancel()
    assert undo.undo() is True
    assert stage.compute_visibility(first) is VisibilityState.VISIBLE
    assert stage.compute_visibility(second) is VisibilityState.VISIBLE


def test_property_visibility_write_keeps_canonical_classification(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    path = "/World/Parent/MeshA"
    prop = _property(scene, stage, undo, path)
    events = []
    subscription = stage.subscribe_changes(events.append)
    try:
        _edit(prop, "visibility", "invisible")
        assert len(events) == 1
        event = events[-1]
        # Provenance is preserved verbatim...
        assert event.source == "property:set"
        # ...while the canonical visibility classification travels in the
        # adapter-owned delta consumers route on (proven + precise, with
        # the committed prim as the authored root).
        delta = event.visibility_delta
        assert delta is not None
        assert delta.get("proven") is True
        assert delta.get("precise") is True
        assert tuple(delta.get("authored") or ()) == (path,)
        # History edges republish with the same classification.
        assert undo.undo() is True
        assert events[-1].visibility_delta is not None
        assert tuple(events[-1].visibility_delta.get("authored") or ()) == (
            path,
        )
    finally:
        subscription.cancel()


def test_reused_shared_interrupt_instance_never_creates_false_history(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    """The history-consistent mark is scoped to one edge, never a reusable object.

    An observer that raises one SHARED interrupt instance during a
    committed edit must not get that instance tagged: the caller receives
    a fresh per-edge copy (chained to the original), and re-raising the
    very same shared object later from a command that failed BEFORE
    applying anything behaves like any ordinary interrupt — no false
    history entry.
    """
    _session, scene, stage, undo = opened
    item = stage.get_item_at_path("/World/Parent/MeshA")
    assert item is not None
    shared = KeyboardInterrupt("shared observer interrupt")

    def observer(_event):
        raise shared

    subscription = stage.subscribe_changes(observer)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            stage.set_visibility(item, False)
        # Fresh per-edge copy: the shared instance is never contaminated.
        assert caught.value is not shared
        assert caught.value.__cause__ is shared
        assert not getattr(shared, "_ovui_history_consistent", False)
        assert not getattr(caught.value, "_ovui_history_consistent", False)
        # The committed edge itself recorded normally.
        assert stage.compute_visibility(item) is VisibilityState.INVISIBLE
        assert undo.can_undo() is True
    finally:
        subscription.cancel()

    class _AbortsBeforeApplying:
        non_undoable = False

        def do(self) -> None:
            raise shared

        def undo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("undo of an unapplied command")

        def redo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("redo of an unapplied command")

    state = (undo.can_undo(), undo.can_redo())
    with pytest.raises(KeyboardInterrupt):
        undo.push(_AbortsBeforeApplying())
    # Nothing was applied, so nothing may be recorded.
    assert (undo.can_undo(), undo.can_redo()) == state
    assert undo.undo() is True  # the real entry, not the unapplied one
    assert stage.compute_visibility(item) is VisibilityState.VISIBLE


def test_delivered_interrupt_from_direct_service_paths_is_reusable(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    """No internal per-edge state on app-delivered exceptions, any entry path.

    A real transform edit pushed DIRECTLY on the command service (the
    widget path, no adapter wrapper) commits, records, and delivers the
    interrupt to the application — and the exact delivered object must
    carry no internal history state: raising that same object later from
    a command that applies nothing must never record it. The same holds
    for direct grouped execution through an application-owned manager
    group.
    """
    _session, scene, stage, undo = opened
    transform = create_transform_adapter(scene)
    path = "/World/Parent"
    initial = transform.get_local_transform(path)
    final = [row[:] for row in initial]
    final[3][0] = 11.0

    def interrupting(_event):
        raise KeyboardInterrupt("transform observer")

    class _AbortsBeforeApplying:
        non_undoable = False

        def __init__(self, exc: BaseException) -> None:
            self._exc = exc

        def do(self) -> None:
            raise self._exc

        def undo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("undo of an unapplied command")

        def redo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("redo of an unapplied command")

    # Direct top-level service push (normal widget transform flow).
    subscription = stage.subscribe_changes(interrupting)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            undo.push(BatchTransformCommand(transform, path, initial, final))
    finally:
        subscription.cancel()
    delivered = caught.value
    assert transform.get_local_transform(path) == final
    assert undo.can_undo() is True
    assert not getattr(delivered, "_ovui_history_consistent", False)
    state = (undo.can_undo(), undo.can_redo(), len(undo._undo_stack))
    with pytest.raises(KeyboardInterrupt):
        undo.push(_AbortsBeforeApplying(delivered))
    assert (undo.can_undo(), undo.can_redo(), len(undo._undo_stack)) == state

    # Direct grouped execution through an application-owned group.
    final2 = [row[:] for row in initial]
    final2[3][0] = 22.0
    subscription = stage.subscribe_changes(interrupting)
    undo.begin_group("app-owned group")
    try:
        with pytest.raises(KeyboardInterrupt) as caught_grouped:
            undo.push(
                BatchTransformCommand(
                    transform, path, [row[:] for row in final], final2
                )
            )
    finally:
        undo.end_group()
        subscription.cancel()
    delivered_grouped = caught_grouped.value
    assert transform.get_local_transform(path) == final2
    assert undo.can_undo() is True
    assert not getattr(delivered_grouped, "_ovui_history_consistent", False)
    state = (undo.can_undo(), undo.can_redo(), len(undo._undo_stack))
    with pytest.raises(KeyboardInterrupt):
        undo.push(_AbortsBeforeApplying(delivered_grouped))
    assert (undo.can_undo(), undo.can_redo(), len(undo._undo_stack)) == state
    # The genuinely recorded edges replay normally.
    assert undo.undo() is True
    assert transform.get_local_transform(path) == final
    assert undo.undo() is True
    assert transform.get_local_transform(path) == initial


def test_direct_transform_write_delivers_clean_reusable_interrupt(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    """The public direct transform-write contract leaks no per-edge state.

    ``set_local_transform`` supports caller-managed undo with no command
    service in the chain. The write commits and the observer interrupt
    stays caller-visible — but the delivered object (and the observer's
    original) must carry no internal history state: raising the exact
    delivered object later from a command that applies nothing must not
    record it.
    """
    _session, scene, stage, undo = opened
    transform = create_transform_adapter(scene)
    path = "/World/Parent"
    initial = transform.get_local_transform(path)
    final = [row[:] for row in initial]
    final[3][0] = 33.0
    shared = KeyboardInterrupt("direct transform observer")

    def observer(_event):
        raise shared

    subscription = stage.subscribe_changes(observer)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            transform.set_local_transform(path, final)
    finally:
        subscription.cancel()
    delivered = caught.value
    # Committed and caller-visible, exactly as the direct contract requires.
    assert transform.get_local_transform(path) == final
    assert delivered is not shared
    assert delivered.__cause__ is shared
    # No internal per-edge state on either object.
    assert not getattr(delivered, "_ovui_history_consistent", False)
    assert not getattr(shared, "_ovui_history_consistent", False)

    class _AbortsBeforeApplying:
        non_undoable = False

        def __init__(self, exc: BaseException) -> None:
            self._exc = exc

        def do(self) -> None:
            raise self._exc

        def undo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("undo of an unapplied command")

        def redo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("redo of an unapplied command")

    for reused in (delivered, shared):
        state = (undo.can_undo(), undo.can_redo(), len(undo._undo_stack))
        with pytest.raises(KeyboardInterrupt):
            undo.push(_AbortsBeforeApplying(reused))
        assert (undo.can_undo(), undo.can_redo(), len(undo._undo_stack)) == state
    # Caller-managed undo remains the caller's: nothing was recorded.
    assert undo.can_undo() is False
    transform.set_local_transform(path, initial)
    assert transform.get_local_transform(path) == initial


def test_observer_spawned_async_child_write_delivers_clean_interrupt(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    """Async child work never inherits a finished edge's history state.

    During a manager-mediated transform edit, an observer schedules an
    asynchronous child task (which snapshots the in-edge context). The
    child runs after the originating edge completed and performs a
    public direct transform write. Its write must commit with a clean,
    caller-visible interrupt: reusing either the child observer's
    exception or the exact delivered object must never record an
    unapplied command.
    """
    import asyncio

    _session, scene, stage, undo = opened
    transform = create_transform_adapter(scene)
    path = "/World/Parent"
    initial = transform.get_local_transform(path)
    final = [row[:] for row in initial]
    final[3][0] = 11.0
    child_final = [row[:] for row in initial]
    child_final[3][0] = 55.0

    loop = asyncio.new_event_loop()
    child_shared = KeyboardInterrupt("child observer interrupt")
    child_delivered: list = []

    def child_direct_write() -> None:
        def interrupting(_event):
            raise child_shared

        subscription = stage.subscribe_changes(interrupting)
        try:
            transform.set_local_transform(path, child_final)
        except KeyboardInterrupt as exc:
            child_delivered.append(exc)
        finally:
            subscription.cancel()

    def edge_observer(_event) -> None:
        loop.call_soon(child_direct_write)

    subscription = stage.subscribe_changes(edge_observer)
    try:
        undo.push(BatchTransformCommand(transform, path, initial, final))
    finally:
        subscription.cancel()
    assert undo.can_undo() is True
    try:
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()
    # The child committed and its interrupt is caller-visible and CLEAN.
    assert transform.get_local_transform(path) == child_final
    assert len(child_delivered) == 1
    delivered = child_delivered[0]
    assert delivered is not child_shared
    assert not getattr(delivered, "_ovui_history_consistent", False)
    assert not getattr(child_shared, "_ovui_history_consistent", False)

    class _AbortsBeforeApplying:
        non_undoable = False

        def __init__(self, exc: BaseException) -> None:
            self._exc = exc

        def do(self) -> None:
            raise self._exc

        def undo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("undo of an unapplied command")

        def redo(self) -> None:  # pragma: no cover - must never run
            raise AssertionError("redo of an unapplied command")

    for reused in (delivered, child_shared):
        state = (undo.can_undo(), undo.can_redo(), len(undo._undo_stack))
        with pytest.raises(KeyboardInterrupt):
            undo.push(_AbortsBeforeApplying(reused))
        assert (undo.can_undo(), undo.can_redo(), len(undo._undo_stack)) == state
    # The genuinely recorded mediated edge still replays.
    assert undo.undo() is True
    assert transform.get_local_transform(path) == initial


def test_interrupted_abort_compensates_once_and_records_nothing(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    """Interrupt during aborted-group compensation stays terminal and coherent.

    A Property Inspector edit pushed inside a widget-owned group is
    compensated exactly once when the group aborts — even when an
    observer raises an interrupt during the compensation publication.
    Nothing about the aborted edit may remain in history (no redo
    resurrection), the manager returns to its pre-scope depth, and the
    interrupt stays observable on the member error.
    """
    _session, scene, stage, undo = opened
    path = "/World/Parent/MeshA"
    prop = _property(scene, stage, undo, path)
    events = []
    counter = stage.subscribe_changes(events.append)
    interrupting = None
    try:
        stage.begin_undo_group("Edit selection")
        _edit(prop, "visibility", "invisible")
        assert prop.get_value("visibility") == "invisible"
        interrupting = stage.subscribe_changes(
            lambda _event: (_ for _ in ()).throw(
                KeyboardInterrupt("compensation observer")
            )
        )
        published_before = len(events)

        class _MemberError(Exception):
            pass

        member_error = _MemberError("member failed")
        try:
            raise member_error
        except _MemberError:
            stage.abort_undo_group()
        # Exactly ONE compensation publication; the value is restored.
        assert len(events) - published_before == 1
        assert prop.get_value("visibility") == "inherited"
        # Terminal state: no group, nothing recorded, nothing to redo —
        # an aborted edit must never resurrect.
        assert undo.open_group_depth == 0
        assert undo.can_undo() is False
        assert undo.can_redo() is False
        # The interrupt remains observable as cleanup context.
        notes = getattr(member_error, "__notes__", [])
        assert any("KeyboardInterrupt" in note for note in notes)
    finally:
        counter.cancel()
        if interrupting is not None:
            interrupting.cancel()


_LOOKALIKE_SCENE = '''#usda 1.0
def Xform "World"
{
    def Mesh "MeshA"
    {
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    }
    def RenderVar "Lookalike"
    {
        custom token visibility = "invisible"
        token sourceName = "color"
    }
}
'''


def test_lookalike_visibility_property_is_not_scene_visibility(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> None:
    """A non-Imageable prim's custom ``visibility`` token routes as attribute.

    RenderVar is not Imageable (no scene visibility), yet its custom token
    property named ``visibility`` is cataloged and editable through the
    real Property Inspector path. That edit must NOT carry the proven
    visibility classification consumers trust for visibility-only
    invalidation — neither alone nor merged into a mixed selection —
    while the genuine Imageable edit keeps it.
    """
    scene_path = tmp_path / "lookalike.usda"
    scene_path.write_text(_LOOKALIKE_SCENE, encoding="utf-8")
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_path))
    undo = UndoManager()
    stage = create_stage_adapter(scene, undo)
    events = []
    subscription = stage.subscribe_changes(events.append)
    try:
        lookalike_item = stage.get_item_at_path("/World/Lookalike")
        assert lookalike_item is not None
        assert stage.can_edit_visibility(lookalike_item) is False

        prop = _property(scene, stage, undo, "/World/Lookalike")
        assert prop.get_value("visibility") == "invisible"
        _edit(prop, "visibility", "inherited")
        assert len(events) == 1
        assert events[-1].source == "property:set"
        assert events[-1].visibility_delta is None

        # Mixed selection stays conservative: one ineligible prim keeps
        # the whole write out of the proven visibility classification.
        mixed = _property(scene, stage, undo, "/World/MeshA", "/World/Lookalike")
        _edit(mixed, "visibility", "invisible")
        assert len(events) == 2
        assert events[-1].visibility_delta is None

        # The genuine Imageable edit keeps per-item invalidation truth.
        genuine = _property(scene, stage, undo, "/World/MeshA")
        _edit(genuine, "visibility", "inherited")
        assert len(events) == 3
        delta = events[-1].visibility_delta
        assert delta is not None and delta.get("proven") is True
        assert tuple(delta.get("authored") or ()) == ("/World/MeshA",)
    finally:
        subscription.cancel()
        session.shutdown_scene()


def test_native_purpose_value_refreshes_bounds_and_undo(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    path = "/World/Parent/MeshA"
    prop = _property(scene, stage, undo, path)
    initial = prop.get_value("purpose")
    initial_bounds = stage.compute_world_aabb([path])
    assert initial == "geometry"
    assert initial_bounds is not None

    _edit(prop, "purpose", "proxy")
    assert prop.get_value("purpose") == "proxy"
    assert stage.compute_world_aabb([path]) is None

    assert undo.undo() is True
    assert prop.get_value("purpose") == initial
    assert stage.compute_world_aabb([path]) == initial_bounds
    assert undo.redo() is True
    assert prop.get_value("purpose") == "proxy"
    assert stage.compute_world_aabb([path]) is None


def test_transform_command_is_exact_notified_and_rejects_nonfinite(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    path = "/World/Parent"
    transform = create_transform_adapter(scene)
    initial = transform.get_local_transform(path)
    final = [row[:] for row in initial]
    final[3][0] = 11.0
    events = []
    subscription = stage.subscribe_changes(events.append)
    before = scene.current_ordinal
    try:
        undo.push(BatchTransformCommand(transform, path, initial, final))
        assert transform.get_local_transform(path) == final
        assert scene.current_ordinal == before + 1
        assert len(events) == 1
        assert events[-1].source == "transform:set"
        assert scene.change_stream.poll() == ()
        assert undo.undo() is True
        assert transform.get_local_transform(path) == initial
        assert len(events) == 2
        assert undo.redo() is True
        assert transform.get_local_transform(path) == final
        assert len(events) == 3

        invalid = [row[:] for row in final]
        invalid[0][0] = math.nan
        state = (scene.current_ordinal, len(events), undo.can_undo())
        with pytest.raises(ValueError, match="finite"):
            transform.set_local_transform(path, invalid)
        assert (scene.current_ordinal, len(events), undo.can_undo()) == state
        singular = [row[:] for row in final]
        singular[2][2] = 0.0
        with pytest.raises(ValueError, match="non-singular"):
            transform.set_local_transform(path, singular)
        assert (scene.current_ordinal, len(events), undo.can_undo()) == state
    finally:
        subscription.cancel()


def test_failed_and_noop_edits_are_silent_and_clear_stays_unsupported(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    camera = _property(scene, stage, undo, "/World/CameraA")
    mesh = _property(scene, stage, undo, "/World/Parent/MeshA")
    events = []
    subscription = stage.subscribe_changes(events.append)
    try:
        before = (scene.current_ordinal, undo.can_undo())
        _edit(camera, "focalLength", camera.get_value("focalLength"))
        assert (scene.current_ordinal, undo.can_undo(), events) == (*before, [])
        with pytest.raises(NotImplementedError, match="authored-opinion"):
            camera.clear_value("focalLength")
        with pytest.raises(NotImplementedError):
            mesh.set_value("localMatrix", tuple(range(16)))
        with pytest.raises(ValueError, match="integer"):
            mesh.set_value("refinementLevel", 1.5)
        assert mesh.get_value("refinementLevel") == -1
        assert (scene.current_ordinal, undo.can_undo(), events) == (*before, [])
    finally:
        subscription.cancel()


def test_value_and_structural_commands_share_history_and_clear_redo(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    camera = _property(scene, stage, undo, "/World/CameraA")
    _edit(camera, "focalLength", 37.0)
    created = stage.create_prim(
        CreateRequest(
            "create.geometry.shape.cube",
            requested_parent_path="/World",
            requested_name="HistoryCube",
        )
    )
    assert created.accepted is True
    assert undo.undo() is True
    assert stage.get_item_at_path(created.primary_path) is None
    assert undo.undo() is True
    assert camera.get_value("focalLength") == pytest.approx(24.0)
    assert undo.redo() is True
    assert camera.get_value("focalLength") == pytest.approx(37.0)
    _edit(camera, "focalLength", 39.0)
    assert undo.can_redo() is False


def test_replacement_and_close_reject_stale_history(
    tmp_path: Path,
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    session, scene, stage, undo = opened
    camera = _property(scene, stage, undo, "/World/CameraA")
    _edit(camera, "focalLength", 41.0)
    replacement_path = tmp_path / "replacement.usda"
    replacement_path.write_text(_REPLACEMENT, encoding="utf-8")
    replacement = session.open_stage(str(replacement_path))
    replacement_stage = create_stage_adapter(replacement)
    other = create_property_adapter(replacement, ["/Replacement/OtherCamera"])
    assert other.get_value("focalLength") == pytest.approx(18.0)
    with pytest.raises(RuntimeError, match="closed or replaced"):
        undo.undo()
    assert replacement_stage.get_item_at_path("/World/CameraA") is None
    assert other.get_value("focalLength") == pytest.approx(18.0)
    assert scene.is_open is False


def test_partial_native_write_failure_rolls_back_releases_and_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ovui_data_adapters.ovstage import _authoring

    class Operation:
        def __init__(self, callback: Any = None) -> None:
            self._callback = callback

        def wait(self) -> None:
            if self._callback is not None:
                self._callback()

    class Tensor:
        def __init__(self, array: Any) -> None:
            self.array = list(array)

    class WriteDesc:
        def __init__(
            self,
            name: str,
            tensor: Any,
            *,
            is_array: bool,
            semantic: int,
        ) -> None:
            self.name = name
            self.tensor = tensor
            self.is_array = is_array
            self.semantic = semantic

    class PathDictionary:
        def __init__(self, stage: Any) -> None:
            self.stage = stage

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def create_path_list_from_strings(self, paths: Any) -> tuple[str, ...]:
            return tuple(paths)

        def destroy_path_list(self, _paths: Any) -> None:
            self.stage.destroyed += 1

    class Module:
        class PrimMode:
            UPSERT = 2

        class DLDataType:
            def __init__(self, *, code: int, bits: int, lanes: int) -> None:
                self.code, self.bits, self.lanes = code, bits, lanes

        @staticmethod
        def make_dltensor(array: Any, **_options: Any) -> Tensor:
            return Tensor(array)

    Module.PathDictionary = PathDictionary
    Module.WriteDesc = WriteDesc

    class Query:
        def __init__(self, stage: Any, paths: tuple[str, ...]) -> None:
            self.stage, self.paths = stage, paths

        def release(self) -> Operation:
            return Operation(lambda: setattr(self.stage, "released", self.stage.released + 1))

    class Stage:
        def __init__(self) -> None:
            self.current_ordinal = 7
            self.values = {"/World/A": 1.0, "/World/B": 2.0}
            self.write_count = 0
            self.released = 0
            self.destroyed = 0
            self.aborted: list[int] = []

        def get_child_paths(self, parent: str) -> tuple[str, ...]:
            return tuple(self.values) if parent == "/World" else ()

        def begin_frame(self) -> int:
            return 8

        def end_frame(self, ordinal: int) -> None:
            self.current_ordinal = ordinal

        def abort_frame(self, ordinal: int) -> None:
            self.aborted.append(ordinal)

        def query_from_path_list(self, paths: tuple[str, ...]) -> Query:
            return Query(self, paths)

        def write_attributes(
            self,
            query: Query,
            writes: tuple[WriteDesc, ...],
            _ordinal: int,
            **_options: Any,
        ) -> Operation:
            self.write_count += 1
            values = tuple(float(value) for value in writes[0].tensor.array)

            def finish() -> None:
                if self.write_count == 1:
                    self.values[query.paths[0]] = values[0]
                    raise RuntimeError("injected partial scatter failure")
                for path, value in zip(query.paths, values):
                    self.values[path] = value

            return Operation(finish)

    class Stream:
        def __init__(self) -> None:
            self.events: list[Any] = []

        @contextlib.contextmanager
        def suppress_notifications(self) -> Iterator[None]:
            yield

        def publish_attribute_change(self, *args: Any, **options: Any) -> None:
            self.events.append((args, options))

    stage = Stage()
    scene = type("Scene", (), {})()
    scene._stage = stage
    scene.is_open = True
    scene.change_stream = Stream()
    scene.current_ordinal = stage.current_ordinal
    monkeypatch.setattr(_authoring, "import_ovstage_runtime_module", lambda _name: Module)
    descriptor = _authoring.NativeValueDescriptor(
        "value", (2, 32, 1), 0, False, False
    )
    command = _authoring.NativeValueEditCommand(
        scene,
        ("/World/A", "/World/B"),
        descriptor,
        (1.0, 2.0),
        (10.0, 20.0),
    )
    with pytest.raises(RuntimeError, match="failed to author"):
        command.do()
    assert stage.values == {"/World/A": 1.0, "/World/B": 2.0}
    assert stage.current_ordinal == 7
    assert stage.aborted == [8]
    assert stage.released == 2
    assert stage.destroyed == 2
    assert scene.change_stream.events == []


def test_native_end_frame_failure_compensates_before_aborting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ovui_data_adapters.ovstage import _authoring

    class Operation:
        def __init__(self, callback: Any = None) -> None:
            self._callback = callback

        def wait(self) -> None:
            if self._callback is not None:
                self._callback()

    class Tensor:
        def __init__(self, array: Any) -> None:
            self.array = list(array)

    class WriteDesc:
        def __init__(
            self,
            name: str,
            tensor: Any,
            *,
            is_array: bool,
            semantic: int,
        ) -> None:
            self.name = name
            self.tensor = tensor
            self.is_array = is_array
            self.semantic = semantic

    class PathDictionary:
        def __init__(self, stage: Any) -> None:
            self.stage = stage

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def create_path_list_from_strings(self, paths: Any) -> tuple[str, ...]:
            return tuple(paths)

        def destroy_path_list(self, _paths: Any) -> None:
            self.stage.destroyed += 1

    class Module:
        class PrimMode:
            UPSERT = 2

        class DLDataType:
            def __init__(self, *, code: int, bits: int, lanes: int) -> None:
                self.code, self.bits, self.lanes = code, bits, lanes

        @staticmethod
        def make_dltensor(array: Any, **_options: Any) -> Tensor:
            return Tensor(array)

    Module.PathDictionary = PathDictionary
    Module.WriteDesc = WriteDesc

    class Query:
        def __init__(self, stage: Any, paths: tuple[str, ...]) -> None:
            self.stage, self.paths = stage, paths

        def release(self) -> Operation:
            return Operation(lambda: setattr(self.stage, "released", self.stage.released + 1))

    class Stage:
        def __init__(self) -> None:
            self.current_ordinal = 11
            self.values = {"/World/A": 1.0}
            self.released = 0
            self.destroyed = 0
            self.aborted: list[int] = []
            self.writes: list[float] = []

        def get_child_paths(self, parent: str) -> tuple[str, ...]:
            return tuple(self.values) if parent == "/World" else ()

        def begin_frame(self) -> int:
            return 12

        def end_frame(self, _ordinal: int) -> Operation:
            return Operation(lambda: (_ for _ in ()).throw(RuntimeError("injected end failure")))

        def abort_frame(self, ordinal: int) -> None:
            self.aborted.append(ordinal)

        def query_from_path_list(self, paths: tuple[str, ...]) -> Query:
            return Query(self, paths)

        def write_attributes(
            self,
            query: Query,
            writes: tuple[WriteDesc, ...],
            _ordinal: int,
            **_options: Any,
        ) -> Operation:
            value = float(writes[0].tensor.array[0])

            def finish() -> None:
                self.values[query.paths[0]] = value
                self.writes.append(value)

            return Operation(finish)

    class Stream:
        def __init__(self) -> None:
            self.events: list[Any] = []

        @contextlib.contextmanager
        def suppress_notifications(self) -> Iterator[None]:
            yield

        def publish_attribute_change(self, *args: Any, **options: Any) -> None:
            self.events.append((args, options))

    stage = Stage()
    scene = type("Scene", (), {})()
    scene._stage = stage
    scene.is_open = True
    scene.change_stream = Stream()
    monkeypatch.setattr(_authoring, "import_ovstage_runtime_module", lambda _name: Module)
    command = _authoring.NativeValueEditCommand(
        scene,
        ("/World/A",),
        _authoring.NativeValueDescriptor("value", (2, 32, 1), 0, False, False),
        (1.0,),
        (9.0,),
    )
    with pytest.raises(RuntimeError, match="could not commit"):
        command.do()
    assert stage.values == {"/World/A": 1.0}
    assert stage.writes == [9.0, 1.0]
    assert stage.current_ordinal == 11
    assert stage.aborted == [12]
    assert stage.released == 2
    assert stage.destroyed == 2
    assert scene.change_stream.events == []


def test_no_renderer_or_forbidden_adapter_is_loaded(
    opened: tuple[Any, Any, Any, UndoManager],
) -> None:
    _session, scene, stage, undo = opened
    camera = _property(scene, stage, undo, "/World/CameraA")
    _edit(camera, "focalLength", 33.0)
    assert not any(name == "pxr" or name.startswith("pxr.") for name in sys.modules)
    assert not any(
        name == "ovui_data_adapters.openusd"
        or name.startswith("ovui_data_adapters.openusd.")
        for name in sys.modules
    )
    assert not any(name == "ovrtx" or name.startswith("ovrtx.") for name in sys.modules)
    assert getattr(scene, "_attached_renderers", set()) == set()
