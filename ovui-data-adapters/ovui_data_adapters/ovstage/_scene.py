# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Provider-owned ovstage scene lifecycle."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
import math
import os
from pathlib import Path
import struct
import threading
from types import MethodType
from types import ModuleType
from typing import Any

from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.runtime_import import import_ovstage_runtime_module
from ovui_data_adapters.ovstage.runtime_preflight import LoadedRuntimes
from ovui_data_adapters.ovstage._stage_write import (
    supports_native_stage_writes,
    wait_operation,
    write_matrix_attribute,
)
from ovui_data_adapters.ovstage._structural import (
    NativeSubtreeSnapshot,
    capture_native_subtrees,
    create_native_prims,
    delete_native_paths,
    restore_native_snapshot,
)


POPULATION_OPERATION = "ovstage.populate_from_file"
_KIT_MATRIX_ALIASES = {
    "localMatrix": "omni:fabric:localMatrix",
    "worldMatrix": "omni:fabric:worldMatrix",
}
_KIT_ATTR_NAMES = (
    "usd-prim-type",
    "omni:fabric:localMatrix",
    "omni:fabric:worldMatrix",
    "extent",
    "faceVertexCounts",
    "faceVertexIndices",
    "focalLength",
    "horizontalAperture",
    "verticalAperture",
    "clippingRange",
    "points",
    "primvars:displayColor",
    "projection",
    "radius",
    "size",
    # OVStage 0.1's broad bucket-discovery query can omit relationship
    # columns. Request the standard material relationship explicitly so its
    # RELATIONSHIP_PATH_ID payload is always available to native parity and
    # Property inspection without consulting USD or OVRTX.
    "material:binding",
    "camera",
    "orderedVars",
    "resolution",
    "sourceName",
    "productName",
    "materialBindingPurposes",
    "visibility",
    "_worldVisibility",
)
# Attributes whose row bytes are down-cast to float32 in _array_row_bytes; their
# reported column dtype must match that stored representation.
_KIT_FLOAT32_CAST_ATTRS = frozenset(
    {
        "extent",
        "points",
        "primvars:displayColor",
        "focalLength",
        "horizontalAperture",
        "verticalAperture",
    }
)
# Internal native attributes never surfaced to the Property Inspector.
_KIT_INTERNAL_ATTRS = frozenset(
    {
        "_worldVisibility",
        "usd-prim-type",
    }
)
# numpy dtype kind -> DLPack type code (matches property_adapter's expectations).
_NUMPY_KIND_TO_DLPACK_CODE = {"i": 0, "u": 1, "f": 2, "b": 6}


def _kit_exposed_attr_name(stored_name: str) -> str | None:
    """Map a cached (stored) attribute name to the name surfaced to ovui.

    Returns ``None`` for native-internal attributes that must stay hidden. The
    fabric ``omni:fabric:{local,world}Matrix`` columns surface under their common
    ``localMatrix`` / ``worldMatrix`` names (the read bridge maps them back).
    """
    if stored_name in _KIT_INTERNAL_ATTRS or stored_name.startswith("_"):
        return None
    for common, fabric in _KIT_MATRIX_ALIASES.items():
        if stored_name == fabric:
            return common
    if stored_name.startswith("omni:"):
        return None
    return stored_name


def _kit_row_dtype(array: Any, data_count: int, attr_name: str) -> tuple[int, int, int] | None:
    """DLPack ``(code, bits, lanes)`` for one prim's stored row of ``attr_name``.

    Mirrors the width + float32 down-cast that :func:`_array_row_bytes` applies,
    so the dtype describes the bytes the read bridge actually returns.
    """
    try:
        flat = array.reshape(-1)
        width = int(flat.size) // max(1, int(data_count))
        if width <= 0:
            return None
        if attr_name in _KIT_FLOAT32_CAST_ATTRS:
            return (_NUMPY_KIND_TO_DLPACK_CODE["f"], 32, width)
        code = _NUMPY_KIND_TO_DLPACK_CODE.get(array.dtype.kind)
        if code is None:
            return None
        return (code, int(array.dtype.itemsize) * 8, width)
    except Exception:
        return None


@dataclass(frozen=True)
class OvstagePopulationFailure:
    """Structured diagnostic for a failed scene population attempt."""

    provider_name: str
    entry_point_value: str
    operation: str
    path: str
    ordinal: int | None
    exception_type: str
    exception_text: str


class OvstageSceneOpenError(RuntimeError):
    """Raised when the provider cannot populate an ovstage scene."""

    def __init__(self, failure: OvstagePopulationFailure) -> None:
        self.failure = failure
        self.module_name = failure.provider_name
        self.entry_point_value = failure.entry_point_value
        self.requirement_name = "ovpopulation"
        self.exception_text = failure.exception_text
        super().__init__(
            f"{failure.operation} failed for {failure.path!r} "
            f"at ordinal {failure.ordinal}: {failure.exception_text}"
        )


class OvstageScene:
    """Live provider scene shared by concrete ovstage adapters."""

    def __init__(
        self,
        *,
        stage: Any,
        source_path: str,
        initial_ordinal: int,
        root_paths: tuple[str, ...],
        native_dirty_worker: Any = None,
    ) -> None:
        self._stage = stage
        self._source_path = source_path
        self._initial_ordinal = int(initial_ordinal)
        self._root_paths = tuple(str(path) for path in root_paths)
        self._native_dirty_worker = native_dirty_worker
        self._change_stream = None
        self._hierarchy = None
        self._physics_controls = None
        # ``Stage.get_topology_version()`` is not guaranteed to advance for
        # every population-side namespace removal in OVStage 0.1.  Keep an
        # adapter-owned revision as a second cache key so edits made through
        # provider commands (rather than a particular StageAdapter instance)
        # invalidate every hierarchy view of this scene.
        self._topology_revision = 0
        # The Stage owner must retain every native borrower until that borrower
        # confirms detach.  A weak set lets a failed-detach renderer disappear
        # while OVRTX may still hold the Stage pointer.
        self._attached_renderers: set[Any] = set()
        # Presentation population can outlive a renderer object when native
        # reference removal fails after a successful OVRTX detach. Keep roots
        # scene-owned until removal itself succeeds so export never serializes
        # stranded private content.
        self._presentation_root_paths: set[str] = set()

    @property
    def source_path(self) -> str:
        return self._source_path

    @property
    def initial_ordinal(self) -> int:
        return self._initial_ordinal

    @property
    def current_ordinal(self) -> int | None:
        stage = self._stage
        if stage is None:
            return None
        return _reconcile_native_write_floor(stage)

    @property
    def topology_revision(self) -> int:
        """Monotonic revision for local or polled hierarchy/type/schema changes."""

        return self._topology_revision

    @property
    def root_paths(self) -> tuple[str, ...]:
        return self._root_paths

    @property
    def native_stage(self) -> Any:
        """Live caller-borrowed native Stage; invalid after scene shutdown."""

        stage = self._stage
        if stage is None or not self.is_open:
            raise RuntimeError("the OVStage scene is closed")
        return stage

    def stored_render_settings(self) -> dict[str, Any]:
        """The scene's stored ``customLayerData['renderSettings']``.

        Read from the stage metadata that population put on ``/``, keyed as
        Kit serializes them (``rtx:post:tonemap:op``). Empty when the scene
        stores none or this ovstage cannot populate stage metadata.
        """

        from ovui_data_adapters.ovstage._native import read_path_attribute_records

        records = read_path_attribute_records(self.native_stage, "/")
        prefix = STORED_RENDER_SETTINGS_PREFIX
        return {
            name[len(prefix):]: record.value
            for name, record in records.items()
            if name.startswith(prefix) and len(name) > len(prefix)
        }

    @property
    def is_open(self) -> bool:
        stage = self._stage
        if stage is None:
            return False
        handle = getattr(stage, "_handle", None)
        if handle is not None:
            return True
        instance = getattr(stage, "_inst", None)
        if instance is not None:
            return bool(instance)
        return True

    @property
    def change_stream(self):
        stream = self._change_stream
        if stream is None:
            from ovui_data_adapters.ovstage.change_stream import OvstageChangeStream
            stream = OvstageChangeStream(self)
            self._change_stream = stream
        return stream

    @property
    def hierarchy(self):
        hierarchy = self._hierarchy
        if hierarchy is None:
            if not self.is_open:
                raise RuntimeError("ovstage scene is not open")
            hierarchy_module = import_ovstage_runtime_module(
                "ovhierarchy",
                import_module_fn=import_module,
            )
            Hierarchy = getattr(hierarchy_module, "Hierarchy")
            hierarchy = Hierarchy(self._stage)
            self._hierarchy = hierarchy
        return hierarchy

    @property
    def physics_controls(self):
        return self._physics_controls

    def attach_physics_controls(self, controls: Any | None) -> None:
        self._physics_controls = controls

    def prepare_native_topology(
        self,
        removed_paths: Iterable[str],
        added_prims: Iterable[tuple[str, str]],
    ) -> int | None:
        """Seed or remove topology through OVStage's native write surface."""

        native_stage = self._require_open_native_stage_for_sync()
        delete_paths = tuple(dict.fromkeys(str(path) for path in removed_paths))
        create_by_type: dict[str, list[str]] = defaultdict(list)
        for path, type_name in added_prims:
            create_by_type[str(type_name) or "Xform"].append(str(path))
        if not delete_paths and not create_by_type:
            return None

        create_rows = tuple(
            (path, type_name)
            for type_name, prim_paths in create_by_type.items()
            for path in prim_paths
        )
        create_paths = tuple(path for path, _type_name in create_rows)
        if len(set(create_paths)) != len(create_paths):
            raise ValueError("duplicate OVStage create targets are not allowed")
        invalid_paths = tuple(
            path
            for path in (*delete_paths, *create_paths)
            if not _is_canonical_native_prim_path(path)
        )
        if invalid_paths:
            raise ValueError(
                "OVStage topology paths must be canonical: "
                + ", ".join(invalid_paths)
            )
        if set(delete_paths) & set(create_paths):
            raise ValueError("an OVStage topology batch cannot delete and create one path")
        missing_deletes = tuple(
            path for path in delete_paths if not _native_path_exists(native_stage, path)
        )
        if missing_deletes:
            raise ValueError(
                "OVStage delete target(s) do not exist: "
                + ", ".join(missing_deletes)
            )
        missing_parents = []
        create_path_set = set(create_paths)
        for path in create_paths:
            parent = path.rsplit("/", 1)[0] or "/"
            if parent != "/" and parent not in create_path_set and not _native_path_exists(
                native_stage,
                parent,
            ):
                missing_parents.append(parent)
        if missing_parents:
            raise ValueError(
                "OVStage create parent(s) do not exist: "
                + ", ".join(dict.fromkeys(missing_parents))
            )
        collisions = tuple(
            path for path, _type_name in create_rows
            if _native_path_exists(native_stage, path)
        )
        if collisions:
            raise RuntimeError(
                "OVStage already contains create target(s): "
                + ", ".join(collisions)
            )
        delete_snapshot = (
            capture_native_subtrees(
                native_stage,
                _outermost_paths(delete_paths),
                ordinal=int(native_stage.current_ordinal),
            )
            if delete_paths
            else None
        )

        ordinal = self._begin_native_topology_frame(native_stage)
        try:
            create_prims = getattr(native_stage, "create_prims")
            delete_prims = getattr(native_stage, "delete_prims")
            for type_name, prim_paths in create_by_type.items():
                create_prims(ordinal, tuple(prim_paths), type_name)
            if delete_paths:
                delete_prims(ordinal, tuple(delete_paths))
        except Exception as exc:
            cleanup_errors: list[BaseException] = []
            if create_rows:
                try:
                    delete_native_paths(
                        native_stage,
                        (path for path, _type_name in create_rows),
                        ordinal=ordinal,
                    )
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if delete_snapshot is not None:
                try:
                    restore_native_snapshot(
                        native_stage,
                        delete_snapshot,
                        ordinal=ordinal,
                    )
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            for cleanup_error in cleanup_errors:
                _add_cleanup_note(exc, "native topology rollback failed", cleanup_error)
            self._finish_failed_native_topology_frame(native_stage, ordinal, exc)
            raise RuntimeError(
                "failed to prepare OVStage native topology"
            ) from exc
        self._finish_native_topology_frame(native_stage, ordinal)
        _record_created_paths(native_stage, create_rows, ordinal)
        _record_deleted_paths(native_stage, delete_paths)
        self._topology_revision += 1
        return ordinal

    def capture_native_subtrees(
        self,
        roots: Iterable[str],
    ) -> NativeSubtreeSnapshot:
        """Capture a Python-owned inverse for current native subtrees."""

        native_stage = self._require_open_native_stage_for_sync()
        return capture_native_subtrees(
            native_stage,
            tuple(str(root) for root in roots),
            ordinal=int(native_stage.current_ordinal),
        )

    def delete_native_subtrees(
        self,
        roots: Iterable[str],
        *,
        snapshot: NativeSubtreeSnapshot | None = None,
    ) -> NativeSubtreeSnapshot:
        """Delete native subtrees and return their immutable undo snapshot."""

        native_stage = self._require_open_native_stage_for_sync()
        root_paths = tuple(dict.fromkeys(str(root) for root in roots))
        owned_snapshot = snapshot or capture_native_subtrees(
            native_stage,
            root_paths,
            ordinal=int(native_stage.current_ordinal),
        )
        if not owned_snapshot.prims:
            raise RuntimeError("the native delete snapshot is empty")
        ordinal = self._begin_native_topology_frame(native_stage)
        try:
            delete_native_paths(
                native_stage,
                tuple(reversed(owned_snapshot.paths)),
                ordinal=ordinal,
            )
        except BaseException as operation_error:
            try:
                restore_native_snapshot(
                    native_stage,
                    owned_snapshot,
                    ordinal=ordinal,
                )
            except BaseException as rollback_error:
                _add_cleanup_note(
                    operation_error,
                    "native delete rollback failed",
                    rollback_error,
                )
            self._finish_failed_native_topology_frame(
                native_stage,
                ordinal,
                operation_error,
            )
            raise
        self._finish_native_topology_frame(native_stage, ordinal)
        _record_deleted_paths(native_stage, owned_snapshot.paths)
        self._topology_revision += 1
        return owned_snapshot

    def restore_native_subtrees(
        self,
        snapshot: NativeSubtreeSnapshot,
    ) -> int:
        """Restore a prior same-stage snapshot as one semantic edit."""

        native_stage = self._require_open_native_stage_for_sync()
        if snapshot.stage_identity != id(native_stage):
            raise RuntimeError("native structural snapshot belongs to another scene")
        collisions = tuple(
            path for path in snapshot.paths if _native_path_exists(native_stage, path)
        )
        if collisions:
            raise RuntimeError(
                "OVStage already contains restore target(s): "
                + ", ".join(collisions)
            )
        ordinal = self._begin_native_topology_frame(native_stage)
        try:
            restore_native_snapshot(native_stage, snapshot, ordinal=ordinal)
        except BaseException as operation_error:
            try:
                delete_native_paths(
                    native_stage,
                    tuple(reversed(snapshot.paths)),
                    ordinal=ordinal,
                )
            except BaseException as rollback_error:
                _add_cleanup_note(
                    operation_error,
                    "native restore rollback failed",
                    rollback_error,
                )
            self._finish_failed_native_topology_frame(
                native_stage,
                ordinal,
                operation_error,
            )
            raise
        self._finish_native_topology_frame(native_stage, ordinal)
        _record_created_paths(
            native_stage,
            (
                (prim.path, _snapshot_type_name(prim))
                for prim in snapshot.prims
            ),
            ordinal,
        )
        self._topology_revision += 1
        return ordinal

    def move_native_paths(
        self,
        edits: Iterable[tuple[Any, Any]],
        source_subtrees: dict[str, tuple[str, ...]],
    ) -> int | None:
        """Clone then delete native subtrees for a namespace edit."""

        native_stage = self._require_open_native_stage_for_sync()
        normalized = tuple(
            (str(old_path), str(new_path))
            for old_path, new_path in edits
            if str(old_path) != str(new_path)
        )
        if not normalized:
            return None

        self.validate_native_namespace_targets(normalized)

        source_roots = tuple(old_path for old_path, _new_path in normalized)
        if _has_nested_roots(source_roots):
            raise RuntimeError(
                "nested namespace selections cannot be moved as independent subtrees"
            )
        for old_path, _new_path in normalized:
            if not source_subtrees.get(old_path):
                raise RuntimeError(
                    f"the native snapshot has no source subtree at {old_path!r}"
                )

        # Some composed USD prims (inactive prims, classes, and pure overs) are
        # intentionally absent from OVStage's rendering population.  They still
        # participate in the USD namespace edit, but require no native clone.
        native_edits: list[tuple[str, str, tuple[str, ...]]] = []
        delete_paths: list[str] = []
        for old_path, new_path in normalized:
            native_subtree = tuple(
                path
                for path in source_subtrees[old_path]
                if _native_path_exists(native_stage, path)
            )
            if not native_subtree:
                continue
            native_edits.append((old_path, new_path, native_subtree))
            delete_paths.extend(native_subtree)
        if not native_edits:
            return None
        delete_paths.sort(
            key=lambda path: (path.count("/"), path),
            reverse=True,
        )

        source_snapshot = capture_native_subtrees(
            native_stage,
            source_roots,
            ordinal=int(native_stage.current_ordinal),
        )
        ordinal = self._begin_native_topology_frame(native_stage, require_clone=True)
        cloned_subtrees: list[tuple[str, str, tuple[str, ...]]] = []
        try:
            clone = getattr(native_stage, "clone")
            for old_path, new_path, native_subtree in native_edits:
                clone(old_path, (new_path,), ordinal)
                cloned_subtrees.append((old_path, new_path, native_subtree))
            getattr(native_stage, "delete_prims")(
                ordinal,
                tuple(dict.fromkeys(delete_paths)),
            )
        except Exception as exc:
            error = RuntimeError(
                "failed to stage an OVStage native namespace move"
            )
            try:
                _delete_cloned_native_subtrees(
                    native_stage,
                    ordinal,
                    cloned_subtrees,
                )
            except Exception as rollback_error:
                add_note = getattr(error, "add_note", None)
                if callable(add_note):
                    add_note(
                        "native namespace rollback also failed: "
                        f"{type(rollback_error).__name__}: {rollback_error}"
                    )
            try:
                restore_native_snapshot(
                    native_stage,
                    source_snapshot,
                    ordinal=ordinal,
                )
            except Exception as rollback_error:
                _add_cleanup_note(
                    error,
                    "native namespace source rollback failed",
                    rollback_error,
                )
            self._finish_failed_native_topology_frame(native_stage, ordinal, error)
            raise error from exc
        self._finish_native_topology_frame(native_stage, ordinal)
        _record_deleted_paths(native_stage, source_snapshot.paths)
        moved_rows = []
        for old_root, new_root, source_paths in native_edits:
            for source_path in source_paths:
                suffix = source_path[len(old_root):]
                target_path = new_root + suffix
                source_prim = next(
                    prim for prim in source_snapshot.prims
                    if prim.path == source_path
                )
                moved_rows.append((target_path, _snapshot_type_name(source_prim)))
        _record_created_paths(native_stage, moved_rows, ordinal)
        self._topology_revision += 1
        return ordinal

    def validate_native_namespace_targets(
        self,
        edits: Iterable[tuple[Any, Any]],
    ) -> None:
        """Reject target collisions before a native namespace edit."""

        native_stage = self._require_open_native_stage_for_sync()
        collisions = tuple(
            str(new_path)
            for old_path, new_path in edits
            if str(old_path) != str(new_path)
            and _native_path_exists(native_stage, str(new_path))
        )
        if collisions:
            raise RuntimeError(
                "OVStage already contains namespace target(s): "
                + ", ".join(collisions)
            )

    def _require_open_native_stage_for_sync(self) -> Any:
        native_stage = self._stage
        if native_stage is None:
            raise RuntimeError(
                "cannot reconcile topology after the OVStage scene was closed"
            )
        return native_stage

    @staticmethod
    def _begin_native_topology_frame(
        native_stage: Any,
        *,
        require_clone: bool = False,
    ) -> int:
        required_names = ["begin_frame", "create_prims", "delete_prims", "end_frame"]
        if require_clone:
            required_names.append("clone")
        if not all(callable(getattr(native_stage, name, None)) for name in required_names):
            raise RuntimeError(
                "the loaded OVStage runtime lacks its required public topology API"
            )
        try:
            return int(native_stage.begin_frame())
        except Exception as exc:
            raise RuntimeError(
                "failed to begin an OVStage topology synchronization frame"
            ) from exc

    @staticmethod
    def _finish_failed_native_topology_frame(
        native_stage: Any,
        ordinal: int,
        operation_error: BaseException,
    ) -> None:
        try:
            abort_frame = getattr(native_stage, "abort_frame", None)
            if callable(abort_frame):
                abort_frame(ordinal)
            else:
                native_stage.end_frame(ordinal)
        except Exception as end_error:
            add_note = getattr(operation_error, "add_note", None)
            if callable(add_note):
                add_note(
                    "OVStage end_frame also failed after topology preparation: "
                    f"{type(end_error).__name__}: {end_error}"
                )

    @staticmethod
    def _finish_native_topology_frame(native_stage: Any, ordinal: int) -> None:
        try:
            native_stage.end_frame(ordinal)
        except Exception as exc:
            raise RuntimeError(
                "OVStage topology was prepared but its frame could not be committed "
                f"at ordinal {ordinal}"
            ) from exc

    def attach_renderer(self, renderer: Any) -> None:
        """Track a renderer borrowing this scene's native Stage."""

        self._attached_renderers.add(renderer)

    def profile_ovui_call(
        self,
        function_name: str,
        function: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a call inside the attached renderer's OVUI development scope."""

        for renderer in tuple(self._attached_renderers):
            start_scope = getattr(
                renderer,
                "start_ovui_performance_scope",
                None,
            )
            end_scope = getattr(
                renderer,
                "end_ovui_performance_scope",
                None,
            )
            if not callable(start_scope) or not callable(end_scope):
                continue
            metric_uid = start_scope(function_name)
            try:
                return function(*args, **kwargs)
            finally:
                end_scope(metric_uid)
        return function(*args, **kwargs)

    @property
    def presentation_root_paths(self) -> tuple[str, ...]:
        """Private population prefixes still composed into this scene."""

        return tuple(sorted(self._presentation_root_paths))

    def register_presentation_root(self, path: str) -> None:
        value = str(path).strip()
        if not value.startswith("/"):
            raise ValueError(f"presentation root must be absolute: {value!r}")
        self._presentation_root_paths.add(value)

    def unregister_presentation_root(self, path: str) -> None:
        self._presentation_root_paths.discard(str(path))

    def detach_renderer(self, renderer: Any) -> None:
        """Forget a renderer after it has detached from the native Stage."""

        self._attached_renderers.discard(renderer)

    def shutdown(self) -> None:
        # OVRTX BORROW requires detach before either side is destroyed.  The
        # provider owns the Stage, so enforce that ordering here even when an
        # application replaces a scene before swapping its viewport renderer.
        renderer_errors: list[BaseException] = []
        for renderer in tuple(self._attached_renderers):
            shutdown = getattr(renderer, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except BaseException as exc:
                    renderer_errors.append(exc)
        if self._attached_renderers or renderer_errors:
            if not renderer_errors:
                renderer_errors.append(
                    RuntimeError(
                        "an OVRTX renderer remained attached after shutdown"
                    )
                )
            _raise_primary_with_cleanup_notes(
                renderer_errors,
                "additional renderer detach failure",
            )

        resource_errors: list[BaseException] = []
        stream = self._change_stream
        if stream is not None:
            try:
                stream.close()
            except BaseException as exc:
                resource_errors.append(exc)
            else:
                self._change_stream = None
        hierarchy = self._hierarchy
        if hierarchy is not None:
            try:
                _release_scene_resource(hierarchy, "OVStage hierarchy")
            except BaseException as exc:
                resource_errors.append(exc)
            else:
                self._hierarchy = None
        if resource_errors:
            _raise_primary_with_cleanup_notes(
                resource_errors,
                "additional native scene-resource cleanup failure",
            )

        stage = self._stage
        if stage is None:
            self._presentation_root_paths.clear()
            self._physics_controls = None
            return
        self._stage = None
        try:
            _destroy_stage(stage)
        except Exception:
            # Native teardown did not complete. Restore ownership and permit a
            # later shutdown retry.
            self._stage = stage
            raise
        self._presentation_root_paths.clear()
        self._physics_controls = None


def open_scene_from_file(
    *,
    runtime: LoadedRuntimes,
    path: str | os.PathLike[str],
    population_domains: int | None = None,
    native_dirty_worker: Any = None,
) -> OvstageScene:
    """Create an ovstage scene from a local path or HTTP(S) identifier."""
    scene_path = str(path)
    if not scene_path.lower().startswith(("http://", "https://")):
        scene_path = str(Path(scene_path).expanduser().resolve())
    stage_module = runtime.module("ovstage")
    population_module = _load_population_module(stage_module)
    stage = None
    ordinal: int | None = None
    frame_open = False
    try:
        try:
            stage = stage_module.Stage(name="ovui ovstage provider")
        except TypeError:
            stage = stage_module.Stage()
        _install_frame_lifecycle_compat(stage)
        ordinal = int(stage.begin_frame())
        frame_open = True
        _populate_from_file(
            population_module,
            stage,
            scene_path,
            ordinal,
            population_domains=population_domains,
        )
        # Mark the frame consumed before calling end_frame: the compatibility
        # implementation releases its frame lock in a finally block even when
        # advancing the public write floor raises, so a second end attempt would
        # be both incorrect and potentially non-idempotent.
        frame_open = False
        stage.end_frame(ordinal)
        if _is_kit_stage_api(stage) or _has_kit_stage_bridge(stage):
            stage._ovui_hierarchy_child_paths_ordinal = int(
                getattr(stage, "current_ordinal", ordinal)
            )
        root_paths = _root_paths_from_stage(stage)
    except Exception as exc:
        cleanup_errors: list[tuple[str, BaseException]] = []
        if frame_open and stage is not None and ordinal is not None:
            frame_open = False
            try:
                stage.end_frame(ordinal)
            except BaseException as cleanup_error:
                cleanup_errors.append(("end failed population frame", cleanup_error))
        try:
            _destroy_stage(stage)
        except BaseException as cleanup_error:
            cleanup_errors.append(("destroy failed candidate stage", cleanup_error))
        error = OvstageSceneOpenError(
            _population_failure(scene_path, ordinal, exc)
        )
        for action, cleanup_error in cleanup_errors:
            _add_cleanup_note(error, action, cleanup_error)
        raise error from exc
    return OvstageScene(
        stage=stage,
        source_path=scene_path,
        initial_ordinal=ordinal,
        root_paths=root_paths,
        native_dirty_worker=native_dirty_worker,
    )


def _load_population_module(stage_module: ModuleType | None = None) -> ModuleType:
    population = getattr(stage_module, "population", None)
    if isinstance(population, ModuleType):
        return population
    try:
        return import_ovstage_runtime_module(
            "ovpopulation",
            import_module_fn=import_module,
        )
    except ImportError:
        if stage_module is None:
            stage_module = import_ovstage_runtime_module(
                "ovstage",
                import_module_fn=import_module,
            )
        population = getattr(stage_module, "population", None)
        if isinstance(population, ModuleType):
            return population
        raise


def _populate_from_file(
    population_module: ModuleType,
    stage: Any,
    scene_path: str,
    ordinal: int,
    *,
    population_domains: int | None = None,
) -> None:
    if _populate_with_stage_metadata(
        population_module,
        stage,
        scene_path,
        ordinal,
        population_domains=population_domains,
    ):
        return
    if population_domains is not None:
        domains = int(population_domains)
        open_usd_async = getattr(population_module, "open_usd_async", None)
        if callable(open_usd_async):
            wait_operation(
                open_usd_async(
                    stage,
                    scene_path,
                    ordinal,
                    domains=domains,
                )
            )
            return
        open_usd = getattr(population_module, "open_usd", None)
        if callable(open_usd):
            open_usd(stage, scene_path, ordinal, domains=domains)
            return
        raise RuntimeError(
            "explicit population domains require ovstage population "
            "open_usd_async or open_usd"
        )

    populate_from_file_async = getattr(
        population_module,
        "populate_from_file_async",
        None,
    )
    if callable(populate_from_file_async):
        wait_operation(populate_from_file_async(stage, scene_path, ordinal))
        return
    open_usd_async = getattr(population_module, "open_usd_async", None)
    if callable(open_usd_async):
        wait_operation(open_usd_async(stage, scene_path, ordinal))
        return
    populate_from_file = getattr(population_module, "populate_from_file", None)
    if callable(populate_from_file):
        populate_from_file(stage, scene_path, ordinal)
        return
    open_usd = getattr(population_module, "open_usd", None)
    if callable(open_usd):
        open_usd(stage, scene_path, ordinal)
        return
    raise RuntimeError("ovstage population module exposes no supported open function")


#: Stage metadata populated onto the root prim ``/`` with the scene. A scene
#: saved by Kit stores its render settings here, and Kit applies them when it
#: opens the scene. ovstage publishes each value as
#: ``usd-metadata:customLayerData:renderSettings:<key>``.
POPULATED_STAGE_METADATA_PATHS: tuple[str, ...] = ("customLayerData:renderSettings",)
STORED_RENDER_SETTINGS_PREFIX = "usd-metadata:customLayerData:renderSettings:"


def _populate_with_stage_metadata(
    population_module: ModuleType,
    stage: Any,
    scene_path: str,
    ordinal: int,
    *,
    population_domains: int | None = None,
) -> bool:
    """Populate through a description that also asks for the stage metadata.

    A description carrying only ``domains`` is exactly ``open_usd``, so the
    domains stay the ones the plain call would use. Returns ``False`` without
    touching the stage when this ovstage has no description API.
    """

    desc_type = getattr(population_module, "Desc", None)
    open_with_desc = getattr(population_module, "open_usd_with_desc_async", None)
    descs_available = getattr(population_module, "descs_available", None)
    domain_type = getattr(population_module, "PopulationDomain", None)
    if not (callable(desc_type) and callable(open_with_desc)):
        return False
    if callable(descs_available) and not descs_available():
        return False
    if population_domains is not None:
        domains = int(population_domains)
    elif domain_type is not None and hasattr(domain_type, "RENDERING"):
        domains = int(domain_type.RENDERING)
    else:
        return False
    desc = desc_type(
        domains=domains,
        stage_metadata_paths=POPULATED_STAGE_METADATA_PATHS,
    )
    wait_operation(open_with_desc(stage, scene_path, ordinal, math.nan, [desc]))
    return True


def _release_scene_resource(resource: Any, label: str) -> None:
    """Release one scene-owned native resource through its public API."""

    release = getattr(resource, "release", None)
    if callable(release):
        wait_operation(release())
        return
    close = getattr(resource, "close", None)
    if callable(close):
        wait_operation(close())
        return
    destroy = getattr(resource, "destroy", None)
    if callable(destroy):
        wait_operation(destroy())
        return
    raise RuntimeError(f"{label} exposes no public release, close, or destroy API")


def _add_cleanup_note(
    primary: BaseException,
    action: str,
    cleanup_error: BaseException,
) -> None:
    add_note = getattr(primary, "add_note", None)
    if callable(add_note):
        add_note(
            f"{action}: {type(cleanup_error).__name__}: {cleanup_error}"
        )


def _raise_primary_with_cleanup_notes(
    errors: Iterable[BaseException],
    secondary_action: str,
) -> None:
    collected = tuple(errors)
    if not collected:
        return
    primary = collected[0]
    for secondary in collected[1:]:
        _add_cleanup_note(primary, secondary_action, secondary)
    raise primary


def _install_frame_lifecycle_compat(stage: Any) -> None:
    """Add v1-style frame helpers when running against ovstage api_v2."""
    update_write_floor = getattr(stage, "update_write_floor", None)
    advance_write_floor = getattr(stage, "advance_write_floor", None)
    render_flow_mode = os.environ.get(
        "OMNIUI_RENDER_FLOW_MODE", "nativePacing"
    )

    if not hasattr(stage, "current_ordinal"):
        stage.current_ordinal = 0

    if not callable(getattr(stage, "begin_frame", None)) and (
        callable(update_write_floor) or callable(advance_write_floor)
    ):
        stage._ovui_frame_lock = threading.RLock()
        stage._ovui_next_ordinal = int(getattr(stage, "current_ordinal", 0) or 0)

        def begin_frame(self: Any) -> int:
            frame_lock = self._ovui_frame_lock
            frame_lock.acquire()
            try:
                before_publication = None
                if render_flow_mode == "nativePacing":
                    before_publication = getattr(
                        self,
                        "_ovui_before_frame_publication",
                        None,
                    )
                    if callable(before_publication):
                        before_publication()
                current = int(getattr(self, "current_ordinal", 0) or 0)
                write_floor = _native_write_floor(self)
                ordinal = max(
                    1,
                    current + 1,
                    int(getattr(self, "_ovui_next_ordinal", 0) or 0) + 1,
                    write_floor + 1,
                )
                self._ovui_next_ordinal = ordinal
                if render_flow_mode == "nativePacing":
                    snapshots = getattr(
                        self,
                        "_ovui_frame_path_metadata_snapshots",
                        None,
                    )
                    if not isinstance(snapshots, dict):
                        snapshots = {}
                        self._ovui_frame_path_metadata_snapshots = snapshots
                    snapshots[ordinal] = _snapshot_recorded_path_metadata(self)
                return ordinal
            except BaseException:
                frame_lock.release()
                raise

        stage.begin_frame = MethodType(begin_frame, stage)
        # The attached-stage frame-pacing adapter may install a pre-frame
        # ownership callback only when this exact compatibility wrapper is
        # the sequencer that invokes it. Native/foreign begin_frame variants
        # fail closed until they provide an equivalent handoff seam.
        if render_flow_mode == "nativePacing":
            stage._ovui_before_frame_publication_supported = True

    if not callable(getattr(stage, "abort_frame", None)) and hasattr(
        stage,
        "_ovui_frame_lock",
    ):
        def abort_frame(self: Any, ordinal: int) -> None:
            try:
                if render_flow_mode == "nativePacing":
                    snapshot = _pop_recorded_path_metadata_snapshot(
                        self,
                        int(ordinal),
                    )
                    if snapshot is not None:
                        _restore_recorded_path_metadata(self, snapshot)
            finally:
                frame_lock = getattr(self, "_ovui_frame_lock", None)
                if frame_lock is not None:
                    try:
                        frame_lock.release()
                    except RuntimeError:
                        pass

        stage.abort_frame = MethodType(abort_frame, stage)

    if not callable(getattr(stage, "end_frame", None)) and (
        callable(update_write_floor) or callable(advance_write_floor)
    ):
        def end_frame(self: Any, ordinal: int) -> None:
            ordinal = int(ordinal)
            committed = False
            try:
                update = getattr(self, "update_write_floor", None)
                if callable(update):
                    update(ordinal)
                else:
                    advance = getattr(self, "advance_write_floor")
                    op = advance(ordinal)
                    wait = getattr(op, "wait", None)
                    if callable(wait):
                        wait()
                committed = True
                try:
                    self.current_ordinal = max(
                        ordinal,
                        int(getattr(self, "current_ordinal", 0) or 0),
                    )
                except AttributeError:
                    pass
            finally:
                if render_flow_mode == "nativePacing":
                    snapshot = _pop_recorded_path_metadata_snapshot(self, ordinal)
                    if not committed and snapshot is not None:
                        _restore_recorded_path_metadata(self, snapshot)
                frame_lock = getattr(self, "_ovui_frame_lock", None)
                if frame_lock is not None:
                    try:
                        frame_lock.release()
                    except RuntimeError:
                        pass

        stage.end_frame = MethodType(end_frame, stage)

    if not callable(getattr(stage, "create_prims", None)):
        def create_prims(
            self: Any,
            ordinal: int,
            paths: list[str] | tuple[str, ...],
            prim_type: str,
        ) -> None:
            prim_paths = tuple(str(path) for path in paths)
            create_native_prims(
                self,
                tuple((prim_path, str(prim_type)) for prim_path in prim_paths),
                ordinal=int(ordinal),
            )
            _ensure_recorded_path_metadata_snapshot(self, int(ordinal))
            _record_created_paths(
                self,
                tuple((prim_path, str(prim_type)) for prim_path in prim_paths),
                int(ordinal),
            )

        stage.create_prims = MethodType(create_prims, stage)

    if not callable(getattr(stage, "delete_prims", None)):
        def delete_prims(
            self: Any,
            ordinal: int,
            paths: list[str] | tuple[str, ...],
        ) -> None:
            delete_native_paths(
                self,
                tuple(str(path) for path in paths),
                ordinal=int(ordinal),
            )
            _ensure_recorded_path_metadata_snapshot(self, int(ordinal))
            _record_deleted_paths(self, tuple(str(path) for path in paths))

        stage.delete_prims = MethodType(delete_prims, stage)

    if not callable(getattr(stage, "get_child_paths", None)):
        def get_child_paths(self: Any, parent_path: str) -> tuple[str, ...]:
            return _native_child_paths(self, parent_path)

        stage.get_child_paths = MethodType(get_child_paths, stage)
        stage._ovui_get_child_paths_source = (
            "native hierarchy(children)/query(usd-parent)"
            if _is_kit_stage_api(stage)
            else "native query(parent_in)"
        )

    if not callable(getattr(stage, "get_parent_path", None)):
        def get_parent_path(self: Any, path: str) -> str:
            value = str(path or "").rstrip("/")
            if value in ("", "/"):
                raise KeyError(path)
            parent = value.rsplit("/", 1)[0]
            return parent or ""

        stage.get_parent_path = MethodType(get_parent_path, stage)
        stage._ovui_get_parent_path_source = "syntactic path parent"

    if not callable(getattr(stage, "get_topology_version", None)):
        def get_topology_version(self: Any) -> int:
            try:
                return _reconcile_native_write_floor(self)
            except Exception:
                return 0

        stage.get_topology_version = MethodType(get_topology_version, stage)
        stage._ovui_get_topology_version_source = "native current_ordinal"

    if _is_kit_stage_api(stage):
        _install_kit_stage_bridge_compat(stage)


def _native_write_floor(stage: Any) -> int:
    """Return Kit OVStage's committed global floor when that API is present."""

    getter = getattr(stage, "get_attribute_write_floor", None)
    if not callable(getter):
        return int(getattr(stage, "current_ordinal", 0) or 0)
    query = None
    try:
        query = getter()
        wait = getattr(query, "wait", None)
        if callable(wait):
            wait()
        fetch = getattr(query, "fetch", None)
        if not callable(fetch):
            return int(getattr(stage, "current_ordinal", 0) or 0)
        return int(fetch())
    except Exception:
        return int(getattr(stage, "current_ordinal", 0) or 0)
    finally:
        release = getattr(query, "release", None)
        if callable(release):
            try:
                operation = release()
                wait = getattr(operation, "wait", None)
                if callable(wait):
                    wait()
            except Exception:
                pass


def _reconcile_native_write_floor(stage: Any) -> int:
    current = int(getattr(stage, "current_ordinal", 0) or 0)
    committed = max(current, _native_write_floor(stage))
    if committed > current:
        stage.current_ordinal = committed
    return committed


def _native_child_paths(stage: Any, parent_path: str) -> tuple[str, ...]:
    if _is_kit_stage_api(stage) or _has_kit_stage_bridge(stage):
        return _kit_child_paths(stage, parent_path)
    parent = str(parent_path or "")
    if parent == "/":
        parent = ""
    query = getattr(stage, "query")
    release_query = getattr(stage, "release_query", None)
    qh, result = query(parent_in=[parent])
    try:
        handle = int(result.get("all_handle") or 0)
        if not handle:
            return ()
        return tuple(str(path) for path in stage.get_prim_paths(handle))
    finally:
        if callable(release_query):
            try:
                release_query(qh)
            except Exception:
                pass


def _is_kit_stage_api(stage: Any) -> bool:
    return (
        callable(getattr(stage, "query", None))
        and callable(getattr(stage, "fetch_query_result", None))
        and callable(getattr(stage, "read_attributes", None))
        and not callable(getattr(stage, "query_prims", None))
    )


def _has_kit_stage_bridge(stage: Any) -> bool:
    return (
        getattr(stage, "_ovui_query_prims_source", None)
        == "native Kit query/read_attributes"
    )


def _install_kit_stage_bridge_compat(stage: Any) -> None:
    """Expose the small v1 surface used by the legacy renderer bridge."""
    if not callable(getattr(stage, "query_prims", None)):
        def query_prims(
            self: Any,
            ordinal: int,
            *,
            require_all: list[str] | tuple[str, ...] | None = None,
            **_kwargs: Any,
        ) -> dict[str, object]:
            return _kit_query_prims(self, int(ordinal), require_all=require_all)

        stage.query_prims = MethodType(query_prims, stage)
        stage._ovui_query_prims_source = "native Kit query/read_attributes"

    if not callable(getattr(stage, "get_prim_paths", None)):
        def get_prim_paths(self: Any, handle: int) -> tuple[str, ...]:
            cache = _kit_stage_cache(self, int(getattr(self, "current_ordinal", 0)))
            return cache.paths_for_handle(handle)

        stage.get_prim_paths = MethodType(get_prim_paths, stage)
        stage._ovui_get_prim_paths_source = "native Kit query/read_attributes"

    if not callable(getattr(stage, "read_attribute", None)):
        def read_attribute(
            self: Any,
            ordinal: int,
            paths: list[str] | tuple[str, ...],
            attr_name: str,
        ) -> bytes:
            path = str(paths[0]) if paths else ""
            cache = _kit_stage_cache(self, int(ordinal))
            return cache.read_attribute(path, str(attr_name))

        stage.read_attribute = MethodType(read_attribute, stage)
        stage._ovui_read_attribute_source = "native Kit read_attributes"

    if not callable(getattr(stage, "read_column", None)):
        def read_column(
            self: Any,
            ordinal: int,
            prim_list_handle: int,
            attr_name: str,
        ) -> tuple[tuple, tuple[int, int, int] | None]:
            cache = _kit_stage_cache(self, int(ordinal))
            dtype = cache.column_dtype(int(prim_list_handle), str(attr_name))
            # The Property Inspector only consumes the dtype; per-prim values are
            # fetched separately via read_attribute.
            return ((), dtype)

        stage.read_column = MethodType(read_column, stage)
        stage._ovui_read_column_source = "native Kit cached column dtype"

    if not callable(getattr(stage, "read_path_targets", None)):
        def read_path_targets(
            self: Any,
            ordinal: int,
            path: str,
            attr_name: str,
        ) -> tuple[str, ...] | None:
            cache = _kit_stage_cache(self, int(ordinal))
            path_dictionary_type = getattr(
                import_module("ovstage"),
                "PathDictionary",
            )
            with path_dictionary_type(self) as paths:
                return cache.read_path_targets(path, attr_name, paths)

        stage.read_path_targets = MethodType(read_path_targets, stage)
        stage._ovui_read_path_targets_source = (
            "native Kit relationship/connection semantics"
        )

    if not callable(getattr(stage, "read_attribute_info", None)):
        def read_attribute_info(
            self: Any,
            ordinal: int,
            path: str,
            attr_name: str,
        ) -> dict[str, object] | None:
            cache = _kit_stage_cache(self, int(ordinal))
            return cache.attribute_info(str(path), str(attr_name))

        stage.read_attribute_info = MethodType(read_attribute_info, stage)
        stage._ovui_read_attribute_info_source = (
            "native Kit read-group dtype/semantic/array metadata"
        )


def stage_supports_kit_matrix_write(stage: Any) -> bool:
    """True when ``stage`` exposes the Kit copy-in write surface needed to set a
    local matrix without the legacy ``ovhierarchy`` runtime."""
    return supports_native_stage_writes(stage)


def kit_write_local_matrix(stage: Any, path: str, flat_matrix: "list[float]") -> None:
    """Write a prim's canonical ``omni:xform`` through Kit OVStage.

    Kit's BORROW rendering tests use the MATRIX semantic on ``omni:xform``.
    Authoring that canonical input lets OVStage update the derived local/world
    Fabric transforms consumed by the attached renderer.
    """
    import numpy as np

    flat = np.ascontiguousarray(np.asarray(flat_matrix, dtype=np.float64).reshape(-1))
    if flat.size != 16:
        raise ValueError("local matrix must have 16 elements")
    write_matrix_attribute(stage, [str(path)], "omni:xform", flat)


class _KitStageBridgeCache:
    def __init__(
        self,
        *,
        ordinal: int,
        path_order: tuple[str, ...],
        attrs: dict[tuple[str, str], bytes],
        types: dict[str, str],
        dtypes: dict[tuple[str, str], tuple[int, int, int]] | None = None,
        semantics: dict[tuple[str, str], int] | None = None,
        arrays: dict[tuple[str, str], bool] | None = None,
    ) -> None:
        self.ordinal = int(ordinal)
        self.path_order = path_order
        self._path_set = frozenset(self.path_order)
        self.attrs = attrs
        self.types = types
        # (path, exposed_attr_name) -> DLPack (code, bits, lanes). Only attrs we
        # can describe are present, so query_prims / read_column stay aligned
        # with what the Property Inspector can actually decode.
        self.dtypes = dtypes or {}
        attribute_names_by_path: dict[str, list[str]] = defaultdict(list)
        for path, name in self.dtypes:
            attribute_names_by_path[path].append(name)
        self._attribute_names_by_path = {
            path: tuple(sorted(names))
            for path, names in attribute_names_by_path.items()
        }
        child_paths_by_parent: dict[str, list[str]] = defaultdict(list)
        for raw_path in self.path_order:
            path = str(raw_path).rstrip("/")
            if not path.startswith("/") or path == "/":
                continue
            parent = path.rsplit("/", 1)[0] or "/"
            child_paths_by_parent[parent].append(path)
        self._child_paths_by_parent = {
            parent: tuple(sorted(dict.fromkeys(paths)))
            for parent, paths in child_paths_by_parent.items()
        }
        # Required to distinguish ordinary uint64 columns from token,
        # relationship-path, and connection-path identifier columns.
        self.semantics = semantics or {}
        # ``ReadGroup.is_array`` is the public API's sole fixed-vs-ragged
        # authority.  Keep it independently from payload width so empty and
        # one-element arrays retain their logical kind.
        self.arrays = arrays or {}
        self._handles: dict[int, tuple[str, ...]] = {}
        self._next_handle = 1

    def register_paths(self, paths: tuple[str, ...]) -> int:
        handle = self._next_handle
        self._next_handle += 1
        self._handles[handle] = paths
        return handle

    def paths_for_handle(self, handle: int) -> tuple[str, ...]:
        return self._handles.get(int(handle), ())

    def attribute_names_for_path(self, path: str) -> tuple[str, ...]:
        return self._attribute_names_by_path.get(path, ())

    def child_paths_for_parent(self, parent_path: str) -> tuple[str, ...]:
        parent = str(parent_path or "").rstrip("/") or "/"
        return tuple(
            path
            for path in self._child_paths_by_parent.get(parent, ())
            if _is_user_scene_path(path)
        )

    def column_dtype(self, handle: int, attr_name: str) -> tuple[int, int, int] | None:
        for path in self.paths_for_handle(handle):
            dtype = self.dtypes.get((path, str(attr_name)))
            if dtype is not None:
                return dtype
        return None

    def read_attribute(self, path: str, attr_name: str) -> bytes:
        if attr_name == "usd-prim-type":
            type_name = self.types.get(path)
            return type_name.encode("utf-8") if type_name else b""
        key_name = _KIT_MATRIX_ALIASES.get(attr_name, attr_name)
        value = self.attrs.get((path, key_name))
        if value is not None:
            return value
        if attr_name == "visibility":
            world = self.attrs.get((path, "_worldVisibility"))
            if world == b"\x00":
                return b"invisible"
            if world == b"\x01":
                return b"inherited"
        return b""

    def read_path_targets(
        self,
        path: str,
        attr_name: str,
        path_dictionary: Any,
    ) -> tuple[str, ...] | None:
        """Decode OVStage relationship/connection IDs without using OVRTX.

        ``None`` means the column is not path-bearing. An empty tuple is a
        valid path-bearing column with no targets.
        """

        key = (str(path), str(attr_name))
        semantic = self.semantics.get(key)
        if semantic not in (4, 12):
            return None
        payload = self.attrs.get(key, b"")
        if not payload:
            return ()
        if semantic == 4:
            if len(payload) % 8:
                raise ValueError(
                    f"relationship payload has invalid byte count: {len(payload)}"
                )
            identifiers = struct.unpack(f"<{len(payload) // 8}Q", payload)
            return tuple(
                str(path_dictionary.path_to_string(identifier))
                for identifier in identifiers
            )
        if len(payload) % 16:
            raise ValueError(
                f"connection payload has invalid byte count: {len(payload)}"
            )
        identifiers = struct.unpack(f"<{len(payload) // 8}Q", payload)
        targets: list[str] = []
        for index in range(0, len(identifiers), 2):
            prim_path = str(path_dictionary.path_to_string(identifiers[index]))
            property_name = str(
                path_dictionary.token_to_string(identifiers[index + 1])
            )
            targets.append(
                f"{prim_path}.{property_name}" if property_name else prim_path
            )
        return tuple(targets)

    def attribute_info(
        self,
        path: str,
        attr_name: str,
    ) -> dict[str, object] | None:
        key_name = _KIT_MATRIX_ALIASES.get(str(attr_name), str(attr_name))
        dtype = self.dtypes.get((str(path), str(attr_name)))
        if dtype is None:
            return None
        key = (str(path), key_name)
        return {
            "dtype": dtype,
            "semantic": int(self.semantics.get(key, 0)),
            "is_array": bool(self.arrays.get(key, False)),
        }


class _KitTopologySnapshot:
    def __init__(
        self,
        ordinal: int,
        path_order: tuple[str, ...],
        *,
        readable: bool = True,
    ) -> None:
        self.ordinal = int(ordinal)
        # ``False`` means no whole-stage surface answered, so ``path_order``
        # is the last topology that did read rather than this ordinal's.
        # Consumers must not mistake it for a stage that became empty.
        self.readable = bool(readable)
        self.path_order = tuple(path_order)
        self._path_set = frozenset(self.path_order)
        children: dict[str, list[str]] = defaultdict(list)
        for path in self.path_order:
            parent = path.rsplit("/", 1)[0] or "/"
            children[parent].append(path)
        self._children = {
            parent: tuple(sorted(dict.fromkeys(paths)))
            for parent, paths in children.items()
        }

    def child_paths_for_parent(self, parent: str) -> tuple[str, ...]:
        return self._children.get(str(parent).rstrip("/") or "/", ())


@dataclass(frozen=True)
class _KitTypeRecordsSnapshot:
    ordinal: int
    records: dict[str, tuple[str, tuple[str, ...]]]


def _kit_topology_snapshot(stage: Any, ordinal: int) -> _KitTopologySnapshot:
    cached = getattr(stage, "_ovui_kit_topology_snapshot", None)
    if isinstance(cached, _KitTopologySnapshot) and cached.ordinal == int(ordinal):
        return cached
    # This ordinal has already been probed and no whole-stage surface answered.
    # Probing again for every consumer repeats that same failed whole-stage
    # read once per expanded parent — thousands of times for one tree — so hand
    # back what the failed probe concluded.  The poll owns the retry and drops
    # this held result before asking again.
    held = getattr(stage, "_ovui_kit_topology_unreadable", None)
    if isinstance(held, _KitTopologySnapshot) and held.ordinal == int(ordinal):
        return held

    ovstage_module = import_module("ovstage")
    path_dictionary_type = getattr(ovstage_module, "PathDictionary")
    ordinal_range_type = getattr(ovstage_module, "OrdinalRange")
    query = None
    read = None
    path_order: list[str] = []
    seen_paths: set[str] = set()
    with path_dictionary_type(stage) as paths:
        path_token = paths.intern_token("usd-path")
        try:
            query = stage.query(None, [path_token])
            wait_operation(query)
            read = stage.read_attributes(
                query,
                [path_token],
                ordinal_range_type.latest(int(ordinal)),
            )
            wait_operation(read)
            while True:
                group = stage.fetch_read_next(read)
                if group is None:
                    break
                try:
                    group_paths = tuple(
                        str(path)
                        for path in paths.get_path_strings(group.prim_list)
                    )
                    _remember_paths(path_order, seen_paths, group_paths)
                finally:
                    try:
                        stage.release_group(group)
                    except Exception:
                        pass
        finally:
            if read is not None:
                try:
                    release_read = getattr(read, "release", None)
                    if callable(release_read):
                        wait_operation(release_read())
                    else:
                        wait_operation(stage.release_read(read))
                except Exception:
                    pass
            if query is not None:
                try:
                    release_query = getattr(query, "release", None)
                    if callable(release_query):
                        wait_operation(release_query())
                    else:
                        wait_operation(stage.release_query(query))
                except Exception:
                    pass

    if not path_order:
        # OVStage 0.1 builds before 0.1.0.346039 advertise ``usd-path`` on the
        # unfiltered query but materialize no rows for it, so an empty read is
        # not proof of an empty stage.  At the population ordinal the native
        # hierarchy walk is both authoritative and cheap, and unlike any
        # attribute column it also reports typeless, attributeless prims.
        # Past that ordinal it no longer reflects committed edits, so the
        # bridge cache — this adapter's pre-``usd-path`` topology source — is
        # the only remaining whole-stage authority.
        walked = None
        if int(ordinal) == int(
            getattr(stage, "_ovui_hierarchy_child_paths_ordinal", -1)
        ):
            walked = _hierarchy_kit_path_order(stage, int(ordinal))
        if walked is None:
            walked = list(_kit_stage_cache(stage, int(ordinal)).path_order)
        if not walked:
            # An empty whole-stage read is only an empty stage if the
            # hierarchy surface agrees.  It tracks deletions, so it reports no
            # root once the prims really are gone; a root it still reports
            # (or no answer at all) means a source is down, not that the
            # stage emptied.  Publishing that would cache "no prims" as the
            # authoritative topology, so consumers would report every prim
            # removed and nothing would re-read at this ordinal.  Carry the
            # last topology that did read, marked unreadable and left
            # unpublished, so the Stage keeps its hierarchy and this ordinal
            # is retried.
            roots = _hierarchy_kit_child_paths(stage, "/", int(ordinal))
            if roots is None or roots:
                # The per-parent filter is a different query and can answer
                # while this one does not, so ask it once about a parent the
                # hierarchy just said has children.  Saying nothing about a
                # populated parent is the one reading that means the surface
                # itself is down; anything else leaves it serving every parent.
                # Only the poll reaches this point, so this is one read per
                # poll, and it is retaken there rather than held for an ordinal.
                stage._ovui_kit_parent_filter_silent_ordinal = (
                    int(ordinal)
                    if roots and not _filtered_kit_child_paths(stage, "/", int(ordinal))
                    else -1
                )
                published = getattr(stage, "_ovui_kit_topology_snapshot", None)
                unreadable = _KitTopologySnapshot(
                    int(ordinal),
                    published.path_order
                    if isinstance(published, _KitTopologySnapshot)
                    else (),
                    readable=False,
                )
                stage._ovui_kit_topology_unreadable = unreadable
                return unreadable
        path_order = walked

    snapshot = _KitTopologySnapshot(
        int(ordinal),
        tuple(path for path in path_order if _is_user_scene_path(path)),
    )
    stage._ovui_kit_topology_snapshot = snapshot
    stage._ovui_kit_topology_unreadable = None
    stage._ovui_kit_child_paths_cache = None
    return snapshot


def _kit_type_records(
    stage: Any,
    ordinal: int,
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Copy only hierarchy type/schema metadata from a Kit OVStage."""

    cached = getattr(stage, "_ovui_kit_type_records_snapshot", None)
    if isinstance(cached, _KitTypeRecordsSnapshot) and cached.ordinal == int(ordinal):
        return dict(cached.records)

    ovstage_module = import_module("ovstage")
    path_dictionary_type = getattr(ovstage_module, "PathDictionary")
    ordinal_range_type = getattr(ovstage_module, "OrdinalRange")
    attrs: dict[tuple[str, str], bytes] = {}
    path_order: list[str] = []
    seen_paths: set[str] = set()
    with path_dictionary_type(stage) as paths:
        attr_tokens = {
            name: paths.intern_token(name)
            for name in ("usd-path", "usd-prim-type", "usd-schemas")
        }
        _merge_kit_read_groups(
            stage,
            paths,
            attr_tokens=list(attr_tokens.values()),
            ordinal_range=ordinal_range_type.latest(int(ordinal)),
            attrs=attrs,
            dtypes={},
            semantics={},
            arrays={},
            path_order=path_order,
            seen_paths=seen_paths,
        )
        types = _copy_kit_prim_types(paths, path_order, attrs)
        schemas = _copy_kit_applied_schemas(paths, path_order, attrs)

    records = {
        path: (types.get(path, ""), schemas.get(path, ()))
        for path in path_order
        if _is_user_scene_path(path)
    }
    stage._ovui_kit_type_records_snapshot = _KitTypeRecordsSnapshot(
        int(ordinal),
        records,
    )
    return dict(records)


def _kit_stage_cache(stage: Any, ordinal: int) -> _KitStageBridgeCache:
    cache = getattr(stage, "_ovui_kit_stage_bridge_cache", None)
    if isinstance(cache, _KitStageBridgeCache) and cache.ordinal == int(ordinal):
        return cache
    cache = _build_kit_stage_cache(stage, int(ordinal))
    # A build that found no prim is either an empty stage or a read that did
    # not answer, and the two are indistinguishable here.  Memoizing it would
    # make the second reading stick for the whole ordinal, so only a cache
    # that actually saw the stage is kept.
    if cache.path_order:
        stage._ovui_kit_stage_bridge_cache = cache
    return cache


def _merge_kit_read_groups(
    stage: Any,
    paths: Any,
    *,
    attr_tokens: list[int],
    ordinal_range: Any,
    attrs: dict[tuple[str, str], bytes],
    dtypes: dict[tuple[str, str], tuple[int, int, int]],
    semantics: dict[tuple[str, str], int],
    arrays: dict[tuple[str, str], bool],
    path_order: list[str],
    seen_paths: set[str],
    prim_paths: tuple[str, ...] | None = None,
) -> None:
    """Merge one public OVStage query/read pass into the bridge cache."""

    path_list = None
    query = None
    read = None
    try:
        if prim_paths is None:
            query = stage.query(None, attr_tokens)
        else:
            path_list = paths.create_path_list_from_strings(prim_paths)
            query = stage.query_from_path_list(path_list)
        wait_operation(query)
        read = stage.read_attributes(query, attr_tokens, ordinal_range)
        wait_operation(read)
        while True:
            group = stage.fetch_read_next(read)
            if group is None:
                break
            try:
                attr_name = paths.token_to_string(int(group.attribute))
                group_paths = tuple(
                    str(path)
                    for path in paths.get_path_strings(group.prim_list)
                )
                _remember_paths(path_order, seen_paths, group_paths)
                _copy_group_values(
                    attrs,
                    group,
                    group_paths,
                    attr_name,
                    dtypes,
                    semantics,
                    arrays,
                )
            finally:
                try:
                    stage.release_group(group)
                except Exception:
                    pass
    finally:
        if read is not None:
            try:
                release = getattr(read, "release", None)
                wait_operation(
                    release() if callable(release) else stage.release_read(read)
                )
            except Exception:
                pass
        if query is not None:
            release_query = getattr(query, "release", None)
            try:
                if callable(release_query):
                    wait_operation(release_query())
                else:
                    wait_operation(stage.release_query(query))
            except Exception:
                pass
        if path_list is not None:
            paths.destroy_path_list(path_list)


def _build_kit_stage_cache(
    stage: Any,
    ordinal: int,
    prim_paths: tuple[str, ...] | None = None,
) -> _KitStageBridgeCache:
    ovstage_module = import_module("ovstage")
    path_dictionary_type = getattr(ovstage_module, "PathDictionary")
    ordinal_range_type = getattr(ovstage_module, "OrdinalRange")
    attrs: dict[tuple[str, str], bytes] = {}
    dtypes: dict[tuple[str, str], tuple[int, int, int]] = {}
    semantics: dict[tuple[str, str], int] = {}
    arrays: dict[tuple[str, str], bool] = {}
    path_order: list[str] = []
    seen_paths: set[str] = set()
    # Read selected prims one at a time: one path-list read over prims with
    # different attribute sets can return no values for any of them.
    path_groups = (
        [None] if prim_paths is None else [(path,) for path in prim_paths]
    )

    native_types: dict[str, str] = {}
    with path_dictionary_type(stage) as paths:
        ordinal_range = ordinal_range_type.latest(ordinal)
        for group_paths in path_groups:
            attr_tokens = {
                name: paths.intern_token(name)
                for name in _requested_kit_attr_names(stage, group_paths)
            }
            _merge_kit_read_groups(
                stage,
                paths,
                attr_tokens=list(attr_tokens.values()),
                ordinal_range=ordinal_range,
                attrs=attrs,
                dtypes=dtypes,
                semantics=semantics,
                arrays=arrays,
                path_order=path_order,
                seen_paths=seen_paths,
                prim_paths=group_paths,
            )

            # Kit OVStage 0.1 can omit eRelationship groups when
            # ``material:binding`` shares one read with the bridge's broad
            # value set, even though the same public query/read succeeds when
            # the relationship is the only requested attribute. Merge that
            # narrow pass unconditionally: it covers every bound prim and
            # harmlessly replaces identical cache entries when a runtime
            # returns the group in both reads.
            material_binding_token = attr_tokens.get("material:binding")
            if material_binding_token is not None:
                _merge_kit_read_groups(
                    stage,
                    paths,
                    attr_tokens=[material_binding_token],
                    ordinal_range=ordinal_range,
                    attrs=attrs,
                    dtypes=dtypes,
                    semantics=semantics,
                    arrays=arrays,
                    path_order=path_order,
                    seen_paths=seen_paths,
                    prim_paths=group_paths,
                )

        native_types = _copy_kit_prim_types(paths, path_order, attrs)

    selected_paths = None if prim_paths is None else frozenset(prim_paths)
    visible_paths = tuple(
        path for path in path_order
        if _is_user_scene_path(path)
        and (selected_paths is None or path in selected_paths)
    )
    types = {path: native_types.get(path, "") for path in visible_paths}
    visible_dtypes = {
        key: dtype for key, dtype in dtypes.items() if _is_user_scene_path(key[0])
    }
    visible_semantics = {
        key: semantic
        for key, semantic in semantics.items()
        if _is_user_scene_path(key[0])
    }
    visible_arrays = {
        key: is_array
        for key, is_array in arrays.items()
        if _is_user_scene_path(key[0])
    }
    return _KitStageBridgeCache(
        ordinal=ordinal,
        path_order=visible_paths,
        attrs=attrs,
        types=types,
        dtypes=visible_dtypes,
        semantics=visible_semantics,
        arrays=visible_arrays,
    )


def _requested_kit_attr_names(
    stage: Any, prim_paths: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    discovered = (
        _discover_kit_attr_names(stage)
        if prim_paths is None
        else _discover_kit_attr_names(stage, prim_paths)
    )
    names = list(_KIT_ATTR_NAMES)
    for name in discovered:
        if name not in names:
            names.append(name)
    return tuple(names)


def _copy_kit_prim_types(
    paths: Any,
    path_order: Iterable[str],
    attrs: dict[tuple[str, str], bytes],
) -> dict[str, str]:
    """Copy authoritative public ``usd-prim-type`` token values to Python."""

    result: dict[str, str] = {}
    for path in path_order:
        payload = attrs.get((path, "usd-prim-type"), b"")
        if len(payload) != 8:
            continue
        token_id = struct.unpack("<Q", payload)[0]
        if token_id == 0:
            result[path] = ""
            continue
        try:
            result[path] = str(paths.token_to_string(token_id))
        except Exception:
            # Missing/malformed native metadata has a truthful unknown type;
            # do not guess from its path or incidental property columns.
            result[path] = ""
    return result


def _copy_kit_applied_schemas(
    paths: Any,
    path_order: Iterable[str],
    attrs: dict[tuple[str, str], bytes],
) -> dict[str, tuple[str, ...]]:
    """Copy public ``usd-schemas`` token arrays to Python-owned strings."""

    result: dict[str, tuple[str, ...]] = {}
    for path in path_order:
        payload = attrs.get((path, "usd-schemas"), b"")
        if not payload or len(payload) % 8:
            continue
        schemas: list[str] = []
        for token_id in struct.unpack(f"<{len(payload) // 8}Q", payload):
            if token_id == 0:
                continue
            try:
                schema = str(paths.token_to_string(token_id))
            except Exception:
                continue
            if schema and schema not in schemas:
                schemas.append(schema)
        if schemas:
            result[path] = tuple(schemas)
    return result


def _discover_kit_attr_names(
    stage: Any, prim_paths: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    path_dictionary_type = getattr(import_module("ovstage"), "PathDictionary")
    with path_dictionary_type(stage) as paths:
        path_list = None
        query = None
        try:
            if prim_paths is None:
                query = stage.query(None, None)
            else:
                path_list = paths.create_path_list_from_strings(prim_paths)
                query = stage.query_from_path_list(path_list)
            wait_operation(query)
            result = query.result()
            return tuple(
                paths.token_to_string(int(token))
                for token in getattr(result, "attributes", ())
            )
        finally:
            release_query = getattr(query, "release", None)
            if callable(release_query):
                try:
                    wait_operation(release_query())
                except Exception:
                    pass
            if path_list is not None:
                paths.destroy_path_list(path_list)


def _remember_paths(
    path_order: list[str],
    seen_paths: set[str],
    paths: tuple[str, ...],
) -> None:
    for path in paths:
        for candidate in _path_with_ancestors(path):
            if candidate in seen_paths:
                continue
            seen_paths.add(candidate)
            path_order.append(candidate)


def _path_with_ancestors(path: str) -> tuple[str, ...]:
    value = str(path or "").rstrip("/")
    if not value.startswith("/") or value == "/":
        return ()
    parts = [part for part in value.split("/") if part]
    current = ""
    paths = []
    for part in parts:
        current = f"{current}/{part}" if current else f"/{part}"
        paths.append(current)
    return tuple(paths)


def _copy_group_values(
    attrs: dict[tuple[str, str], bytes],
    group: Any,
    group_paths: tuple[str, ...],
    attr_name: str,
    dtypes: dict[tuple[str, str], tuple[int, int, int]] | None = None,
    semantics: dict[tuple[str, str], int] | None = None,
    array_kinds: dict[tuple[str, str], bool] | None = None,
) -> None:
    if not group_paths:
        return
    data_count = int(getattr(group, "data_count", 0) or 0)
    prim_count = int(getattr(group, "prim_count", 0) or 0)
    tensor_count = int(getattr(group, "tensor_count", 0) or 0)
    if data_count <= 0 or prim_count <= 0 or tensor_count <= 0:
        return
    tensors = []
    for tensor_index in range(tensor_count):
        try:
            tensors.append(group.array(tensor_index))
        except Exception:
            return
    is_array = bool(getattr(getattr(group, "raw", None), "is_array", False))
    semantic = int(getattr(getattr(group, "raw", None), "semantic", 0) or 0)
    if is_array:
        exposed = _kit_exposed_attr_name(attr_name)
        for local_index in range(prim_count):
            try:
                prim_index = int(group.prim_index(local_index))
                tensor_index = int(group.data_row_index(local_index))
                path = group_paths[prim_index]
                array = tensors[tensor_index]
            except Exception:
                continue
            if not _is_user_scene_path(path):
                continue
            payload = _array_tensor_bytes(array, attr_name)
            if payload is None:
                continue
            attrs[(path, attr_name)] = payload
            if semantics is not None:
                semantics[(path, attr_name)] = semantic
            if array_kinds is not None:
                array_kinds[(path, attr_name)] = True
            if dtypes is not None and exposed is not None:
                dtype = _read_group_tensor_dtype(group, tensor_index, attr_name)
                if dtype is not None:
                    dtypes[(path, exposed)] = dtype
        return
    # Single-tensor columns have an unambiguous element dtype we can surface to
    # the Property Inspector; skip dtype capture for multi-tensor concatenations.
    exposed = _kit_exposed_attr_name(attr_name)
    column_dtype = (
        _kit_row_dtype(tensors[0], data_count, attr_name)
        if dtypes is not None and exposed is not None and tensor_count == 1
        else None
    )
    for local_index in range(prim_count):
        try:
            prim_index = int(group.prim_index(local_index))
            data_index = int(group.data_row_index(local_index))
            path = group_paths[prim_index]
        except Exception:
            continue
        if not _is_user_scene_path(path):
            continue
        payload = b"".join(
            _array_row_bytes(array, data_count, data_index, attr_name)
            for array in tensors
        )
        if payload:
            attrs[(path, attr_name)] = payload
            if semantics is not None:
                semantics[(path, attr_name)] = semantic
            if array_kinds is not None:
                array_kinds[(path, attr_name)] = False
            if column_dtype is not None and dtypes is not None:
                dtypes[(path, exposed)] = column_dtype


def _array_row_bytes(
    array: Any,
    data_count: int,
    data_index: int,
    attr_name: str,
) -> bytes:
    try:
        flat = array.reshape(-1)
        width = int(flat.size) // int(data_count)
        if width <= 0:
            return b""
        start = int(data_index) * width
        row = flat[start:start + width]
        if attr_name in {
            "extent",
            "points",
            "primvars:displayColor",
            "focalLength",
            "horizontalAperture",
            "verticalAperture",
        }:
            row = row.astype("float32", copy=False)
        return row.tobytes()
    except Exception:
        return b""


def _array_tensor_bytes(array: Any, attr_name: str) -> bytes | None:
    try:
        flat = array.reshape(-1)
        if attr_name in _KIT_FLOAT32_CAST_ATTRS:
            flat = flat.astype("float32", copy=False)
        return flat.tobytes()
    except Exception:
        return None


def _read_group_tensor_dtype(
    group: Any,
    tensor_index: int,
    attr_name: str,
) -> tuple[int, int, int] | None:
    try:
        dtype = group.tensor(int(tensor_index)).dtype
        code = int(dtype.code)
        bits = int(dtype.bits)
        lanes = int(dtype.lanes)
        if attr_name in _KIT_FLOAT32_CAST_ATTRS:
            code = _NUMPY_KIND_TO_DLPACK_CODE["f"]
            bits = 32
        return (code, bits, lanes)
    except Exception:
        return None


def _is_user_scene_path(path: str) -> bool:
    value = str(path or "")
    if not value.startswith("/"):
        return False
    if value == "/Render/OmniverseGlobalRenderSettings" or value.startswith(
        "/Render/OmniverseGlobalRenderSettings/"
    ):
        return False
    root = value.split("/", 2)[1] if len(value) > 1 else ""
    if root.startswith("__") or root == "TempChangeTracking":
        return False
    return True


def _kit_query_prims(
    stage: Any,
    ordinal: int,
    *,
    require_all: list[str] | tuple[str, ...] | None,
) -> dict[str, object]:
    cache = _kit_stage_cache(stage, ordinal)
    required = {str(value) for value in (require_all or ())}
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in cache.path_order:
        type_name = cache.types.get(path, "")
        if required and not _kit_type_matches(type_name, required):
            continue
        grouped[type_name].append(path)
    groups = []
    for type_name, paths in grouped.items():
        handle = cache.register_paths(tuple(paths))
        # Union of describable attribute names across the group's prims so the
        # Property Inspector can enumerate them; per-path absent attrs are
        # dropped later when their bytes/dtype come back empty.
        attribute_names: list[str] = []
        seen: set[str] = set()
        for path in paths:
            for name in cache.attribute_names_for_path(path):
                if name not in seen:
                    seen.add(name)
                    attribute_names.append(name)
        groups.append(
            {
                "prim_type": type_name,
                "prim_list_handle": handle,
                "attributes": tuple(sorted(attribute_names)),
            }
        )
    return {
        "groups": groups,
        "total_prim_count": sum(len(paths) for paths in grouped.values()),
    }


def _kit_type_matches(type_name: str, required: set[str]) -> bool:
    if type_name in required:
        return True
    usd_name = f"UsdGeom{type_name}"
    return usd_name in required


def _hierarchy_kit_child_paths(
    stage: Any,
    parent_path: str,
    ordinal: int,
) -> tuple[str, ...] | None:
    """Read direct children through OVStage's native hierarchy API."""

    ovstage_module = import_module("ovstage")
    relation_type = getattr(ovstage_module, "HierarchyRelation", None)
    path_dictionary_type = getattr(ovstage_module, "PathDictionary", None)
    get_hierarchy = getattr(stage, "get_hierarchy", None)
    if (
        relation_type is None
        or path_dictionary_type is None
        or not callable(get_hierarchy)
    ):
        return None

    parent = str(parent_path or "").rstrip("/") or "/"
    with path_dictionary_type(stage) as paths:
        path_list = paths.create_path_list_from_strings([parent])
        try:
            result = get_hierarchy(
                path_list,
                int(ordinal),
                relation_type.CHILDREN,
            )
            items = tuple(getattr(result, "items", ()))
            if len(items) != 1 or not bool(getattr(items[0], "ok", False)):
                return None

            children: list[str] = []
            for raw_path in getattr(items[0], "paths", ()):
                if isinstance(raw_path, str):
                    value = raw_path
                else:
                    value = str(paths.path_to_string(int(raw_path)))
                if _is_user_scene_path(value):
                    children.append(value)
            return tuple(sorted(dict.fromkeys(children)))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
        finally:
            paths.destroy_path_list(path_list)


def _hierarchy_kit_path_order(stage: Any, ordinal: int) -> list[str] | None:
    """Enumerate the whole stage through OVStage's native hierarchy API.

    ``None`` means at least one read did not answer, so the walk is unusable.
    That is distinct from a childless parent and from a stage with no user
    prims, which both report an empty child tuple.  A partial walk is never
    returned: it would hide the unread subtree behind a complete-looking
    result that the caller would then publish as authoritative.
    """

    root_children = _hierarchy_kit_child_paths(stage, "/", ordinal)
    if root_children is None:
        return None

    path_order: list[str] = []
    seen: set[str] = set()
    pending = list(root_children)
    while pending:
        path = pending.pop(0)
        if path in seen:
            continue
        seen.add(path)
        path_order.append(path)
        children = _hierarchy_kit_child_paths(stage, path, ordinal)
        if children is None:
            return None
        pending.extend(children)
    return path_order


def _filtered_kit_child_paths(
    stage: Any,
    parent_path: str,
    ordinal: int,
) -> tuple[str, ...] | None:
    """Read direct children through OVStage's native ``usd-parent`` filter."""

    ovstage_module = import_module("ovstage")
    filter_type = getattr(ovstage_module, "Filter", None)
    filter_op_type = getattr(ovstage_module, "FilterOp", None)
    ordinal_range_type = getattr(ovstage_module, "OrdinalRange", None)
    path_dictionary_type = getattr(ovstage_module, "PathDictionary", None)
    predicate_type = getattr(ovstage_module, "Predicate", None)
    if not all(
        value is not None
        for value in (
            filter_type,
            filter_op_type,
            ordinal_range_type,
            path_dictionary_type,
            predicate_type,
        )
    ):
        return None

    parent = str(parent_path or "").rstrip("/") or "/"
    query = None
    read = None
    children: list[str] = []
    with path_dictionary_type(stage) as paths:
        path_token = paths.intern_token("usd-path")
        filter_value = filter_type(
            [predicate_type("usd-parent", filter_op_type.IN, [parent])]
        )
        try:
            query = stage.query(filter_value, [path_token])
            wait_operation(query)
            read = stage.read_attributes(
                query,
                [path_token],
                ordinal_range_type.latest(int(ordinal)),
            )
            wait_operation(read)
            while True:
                group = stage.fetch_read_next(read)
                if group is None:
                    break
                try:
                    children.extend(
                        str(path)
                        for path in paths.get_path_strings(group.prim_list)
                        if _is_user_scene_path(str(path))
                    )
                finally:
                    try:
                        stage.release_group(group)
                    except Exception:
                        pass
        finally:
            if read is not None:
                try:
                    release_read = getattr(read, "release", None)
                    if callable(release_read):
                        wait_operation(release_read())
                    else:
                        wait_operation(stage.release_read(read))
                except Exception:
                    pass
            if query is not None:
                try:
                    release_query = getattr(query, "release", None)
                    if callable(release_query):
                        wait_operation(release_query())
                    else:
                        wait_operation(stage.release_query(query))
                except Exception:
                    pass
    return tuple(sorted(dict.fromkeys(children)))


def _merge_authored_kit_child_paths(
    stage: Any,
    parent_path: str,
    native_children: Iterable[str],
    *,
    authoritative_paths: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Overlay adapter-authored children missing from OVStage 0.1 metadata."""

    parent = str(parent_path or "").rstrip("/") or "/"
    children = {
        str(path)
        for path in native_children
        if _is_user_scene_path(str(path))
    }
    authored_types = getattr(stage, "_ovui_authored_prim_types", None)
    if isinstance(authored_types, dict):
        for raw_path in authored_types:
            path = str(raw_path)
            authored_parent = path.rsplit("/", 1)[0] or "/"
            if (
                authored_parent == parent
                and _is_user_scene_path(path)
                and (
                    authoritative_paths is None
                    or path in authoritative_paths
                )
            ):
                children.add(path)
    return tuple(sorted(children))


def _kit_child_paths(stage: Any, parent_path: str) -> tuple[str, ...]:
    # The poll/topology-version boundary owns native-floor reconciliation.
    # Parent expansion must remain a cache lookup, not a blocking floor read.
    ordinal = int(getattr(stage, "current_ordinal", 0) or 0)
    parent = str(parent_path or "").rstrip("/")
    topology = getattr(stage, "_ovui_kit_topology_snapshot", None)
    bridge_cache = getattr(stage, "_ovui_kit_stage_bridge_cache", None)
    child_cache = getattr(stage, "_ovui_kit_child_paths_cache", None)
    if not (
        isinstance(child_cache, tuple)
        and len(child_cache) == 2
        and child_cache[0] == ordinal
        and isinstance(child_cache[1], dict)
    ):
        child_cache = (ordinal, {})
        stage._ovui_kit_child_paths_cache = child_cache

    if isinstance(topology, _KitTopologySnapshot) and topology.ordinal == ordinal:
        result = _merge_authored_kit_child_paths(
            stage,
            parent,
            topology.child_paths_for_parent(parent),
            authoritative_paths=topology._path_set,
        )
        child_cache[1][parent] = result
        return result

    if (
        isinstance(bridge_cache, _KitStageBridgeCache)
        and bridge_cache.ordinal == ordinal
    ):
        result = _merge_authored_kit_child_paths(
            stage,
            parent,
            bridge_cache.child_paths_for_parent(parent),
            authoritative_paths=bridge_cache._path_set,
        )
        child_cache[1][parent] = result
        return result

    if parent in child_cache[1]:
        return child_cache[1][parent]

    hierarchy_ordinal = int(
        getattr(stage, "_ovui_hierarchy_child_paths_ordinal", ordinal)
    )
    native_lookups = (
        (_hierarchy_kit_child_paths, _filtered_kit_child_paths)
        if ordinal == hierarchy_ordinal
        else (_filtered_kit_child_paths, _hierarchy_kit_child_paths)
    )
    if int(getattr(stage, "_ovui_kit_parent_filter_silent_ordinal", -1)) == ordinal:
        # The poll found this surface saying nothing about a parent that has
        # children, so asking it here would repeat that failed read once per
        # row of the tree, and settle at the same held topology the loop below
        # falls through to anyway.  The poll retakes that reading, so a surface
        # that comes back is used again without waiting for anything else.
        native_lookups = ()
    for lookup in native_lookups:
        native_children = lookup(stage, parent, ordinal)
        if native_children is None:
            continue
        if not native_children:
            # An OVStage 0.1 build that does not implement this native surface
            # answers successfully with zero rows, which is indistinguishable
            # from a genuinely childless parent.  Neither reading is proof, so
            # settle it against the whole-stage snapshot rather than publishing
            # an empty hierarchy or trusting the other lookup, which this
            # ordinal ordering already ranks lower.
            break
        result = _merge_authored_kit_child_paths(
            stage,
            parent,
            native_children,
        )
        child_cache[1][parent] = result
        return result

    # Publishing the snapshot clears the per-parent cache, so do not memoize
    # here: the next expansion takes the snapshot branch above and caches there.
    topology = _kit_topology_snapshot(stage, ordinal)
    return _merge_authored_kit_child_paths(
        stage,
        parent,
        topology.child_paths_for_parent(parent),
        authoritative_paths=topology._path_set,
    )


def _native_path_exists(stage: Any, path: str) -> bool:
    """Return whether ``path`` is present in the committed native topology."""

    value = str(path or "").rstrip("/")
    if not value.startswith("/") or value == "/":
        return value == "/"
    parent = value.rsplit("/", 1)[0]
    query_parent = parent or ""
    get_child_paths = getattr(stage, "get_child_paths", None)
    if not callable(get_child_paths):
        return False
    try:
        return value in {str(child) for child in get_child_paths(query_parent)}
    except KeyError:
        return False
    except Exception as exc:
        raise RuntimeError(
            f"failed to inspect OVStage namespace path {value!r}"
        ) from exc


def _is_canonical_native_prim_path(path: str) -> bool:
    value = str(path)
    return bool(
        value.startswith("/")
        and value != "/"
        and not value.endswith("/")
        and "//" not in value
        and all(part not in {"", ".", ".."} for part in value[1:].split("/"))
    )


def _delete_cloned_native_subtrees(
    stage: Any,
    ordinal: int,
    cloned_subtrees: Iterable[tuple[str, str, tuple[str, ...]]],
) -> None:
    """Remove every successful clone after a later clone/delete failure."""

    target_paths: list[str] = []
    for old_root, new_root, source_paths in cloned_subtrees:
        for source_path in source_paths:
            suffix = source_path[len(old_root):]
            target_paths.append(new_root + suffix)
    target_paths.sort(
        key=lambda path: (path.count("/"), path),
        reverse=True,
    )
    if target_paths:
        getattr(stage, "delete_prims")(
            int(ordinal),
            tuple(dict.fromkeys(target_paths)),
        )


def _has_nested_roots(paths: Iterable[str]) -> bool:
    values = tuple(dict.fromkeys(str(path).rstrip("/") for path in paths))
    for index, path in enumerate(values):
        prefix = path + "/"
        if any(
            other.startswith(prefix)
            for other_index, other in enumerate(values)
            if other_index != index
        ):
            return True
    return False


def _outermost_paths(paths: Iterable[str]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(str(path).rstrip("/") for path in paths))
    return tuple(
        path
        for path in values
        if not any(
            path.startswith(other + "/")
            for other in values
            if other != path
        )
    )


def _record_created_paths(
    stage: Any,
    rows: Iterable[tuple[str, str]],
    ordinal: int,
) -> None:
    authored_types = getattr(stage, "_ovui_authored_prim_types", None)
    if not isinstance(authored_types, dict):
        authored_types = {}
        stage._ovui_authored_prim_types = authored_types
    births = getattr(stage, "_ovui_path_birth_ordinals", None)
    if not isinstance(births, dict):
        births = {}
        stage._ovui_path_birth_ordinals = births
    for raw_path, raw_type_name in rows:
        path = str(raw_path)
        authored_types[path] = str(raw_type_name)
        births[path] = int(ordinal)


def _snapshot_recorded_path_metadata(
    stage: Any,
) -> tuple[dict[str, str] | None, dict[str, int] | None]:
    authored_types = getattr(stage, "_ovui_authored_prim_types", None)
    births = getattr(stage, "_ovui_path_birth_ordinals", None)
    return (
        dict(authored_types) if isinstance(authored_types, dict) else None,
        dict(births) if isinstance(births, dict) else None,
    )


def _ensure_recorded_path_metadata_snapshot(stage: Any, ordinal: int) -> None:
    """Capture topology metadata only before its first mutation in a frame."""

    snapshots = getattr(stage, "_ovui_frame_path_metadata_snapshots", None)
    if not isinstance(snapshots, dict):
        snapshots = {}
        stage._ovui_frame_path_metadata_snapshots = snapshots
    key = int(ordinal)
    if key not in snapshots:
        snapshots[key] = _snapshot_recorded_path_metadata(stage)


def _pop_recorded_path_metadata_snapshot(
    stage: Any,
    ordinal: int,
) -> tuple[dict[str, str] | None, dict[str, int] | None] | None:
    snapshots = getattr(stage, "_ovui_frame_path_metadata_snapshots", None)
    if not isinstance(snapshots, dict):
        return None
    return snapshots.pop(int(ordinal), None)


def _restore_recorded_path_metadata(
    stage: Any,
    snapshot: tuple[dict[str, str] | None, dict[str, int] | None],
) -> None:
    for attribute_name, saved in zip(
        ("_ovui_authored_prim_types", "_ovui_path_birth_ordinals"),
        snapshot,
        strict=True,
    ):
        current = getattr(stage, attribute_name, None)
        if isinstance(current, dict):
            current.clear()
            if saved is not None:
                current.update(saved)
        elif saved is not None:
            setattr(stage, attribute_name, dict(saved))


def _record_deleted_paths(stage: Any, paths: Iterable[str]) -> None:
    roots = frozenset(str(path) for path in paths)
    if not roots:
        return
    authored_types = getattr(stage, "_ovui_authored_prim_types", None)
    births = getattr(stage, "_ovui_path_birth_ordinals", None)
    for mapping in (authored_types, births):
        if not isinstance(mapping, dict):
            continue
        for existing in tuple(mapping):
            # A hash lookup for each syntactic ancestor preserves root-subtree
            # deletion without comparing every metadata key to every root.
            candidate = str(existing)
            remove = candidate in roots
            while not remove:
                separator = candidate.rfind("/")
                if separator <= 0:
                    break
                candidate = candidate[:separator]
                remove = candidate in roots
            if not remove and "" in roots and str(existing).startswith("/"):
                remove = True
            if remove:
                mapping.pop(existing, None)


def _snapshot_type_name(prim: Any) -> str:
    return str(getattr(prim, "type_name", "") or "")


def _root_paths_from_stage(stage: Any) -> tuple[str, ...]:
    get_child_paths = getattr(stage, "get_child_paths", None)
    if not callable(get_child_paths):
        return ()
    try:
        return tuple(str(path) for path in get_child_paths(""))
    except TypeError:
        return ()


def _population_failure(
    path: str,
    ordinal: int | None,
    exc: BaseException,
) -> OvstagePopulationFailure:
    return OvstagePopulationFailure(
        provider_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        operation=POPULATION_OPERATION,
        path=path,
        ordinal=ordinal,
        exception_type=type(exc).__name__,
        exception_text=f"{type(exc).__name__}: {exc}",
    )


def _destroy_stage(stage: Any | None) -> None:
    if stage is None:
        return
    destroy = getattr(stage, "destroy", None)
    if callable(destroy):
        destroy()
        return
    handle = getattr(stage, "_handle", None)
    if handle is None:
        return
    bindings = getattr(stage, "_bindings", None)
    if bindings is not None:
        bindings.destroy_instance(handle)
    stage._handle = None
