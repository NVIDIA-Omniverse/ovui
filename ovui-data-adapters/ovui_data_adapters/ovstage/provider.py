# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Provider metadata and factories for the ovstage adapter scaffold."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
import struct
import sys
from typing import Any

import numpy as np

from ovui_data_adapters.common import (
    AdapterCapabilities,
    AdapterCapability,
    AdapterFactories,
    CreateRequest,
    StageCapabilities,
)
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    PROVIDER_PRIORITY as PROVIDER_PRIORITY,
)
from ovui_data_adapters.ovstage._scene import (
    OvstagePopulationFailure,
    OvstageScene,
    _add_cleanup_note,
    _native_path_exists,
    open_scene_from_file,
)
from ovui_data_adapters.ovstage._structural import NativeDeletePrimsCommand
from ovui_data_adapters.ovstage._stage_write import (
    supports_native_stage_writes,
    write_matrix_attribute,
)
from ovui_data_adapters.ovstage._errors import raise_not_ready
from ovui_data_adapters.ovstage._native import resolve_query_names
from ovui_data_adapters.ovstage.layer_stack_adapter import OvstageLayerStackAdapter
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.runtime_preflight import (
    OPTIONAL_RUNTIME_REQUIREMENTS,
    OVRTX_RUNTIME_REQUIREMENT,
    REQUIRED_RUNTIME_REQUIREMENTS,
    LoadedRuntimes,
    load_required_runtimes,
)
from ovui_data_adapters.ovstage.selection_adapter import OvstageSelectionAdapter
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter


PROVIDER_REQUIREMENTS = tuple(
    requirement.name
    for requirement in (
        *REQUIRED_RUNTIME_REQUIREMENTS,
        OVRTX_RUNTIME_REQUIREMENT,
    )
)


PHYSICS_CREATE_OPERATION = "ovphysx.create_instance"
PHYSICS_ENABLE_OPERATION = "ovphysx.enable"
PHYSICS_PLAY_OPERATION = "ovphysx.play"
PHYSICS_STEP_OPERATION = "ovphysx.step"
PHYSICS_DISABLE_OPERATION = "ovphysx.disable"
PHYSICS_FIXED_TIME_STEP_SECS = 1.0 / 60.0
PHYSICS_MAX_ACCUMULATED_TIME_SECS = 0.25
PHYSICS_MAX_SUBSTEPS_PER_TICK = 8
PHYSICS_POSE_WRITE_HISTORY_LIMIT = 512
PHYSICS_XFORM_ATTRIBUTES = ("localMatrix", "worldMatrix", "xformOp:transform")
PHYSICS_TRACE_SHUTDOWN_ENV = "OVUI_WIDGETS_TRACE_SHUTDOWN"

_OVSTAGE_STAGE_CAPABILITIES = StageCapabilities(
    create_stage=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API can construct an in-memory stage but does "
        "not expose durable new-document creation; select the OpenUSD data adapter "
        "for durable document creation"
    ),
    export_stage=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose stage export or serialization; "
        "select the OpenUSD data adapter for export"
    ),
    create_prims=AdapterCapability.supported(
        "the supplied OVStage 0.1 API supports native prim and attribute writes "
        "for representable prim kinds"
    ),
    delete_prims=AdapterCapability.supported(
        "the supplied OVStage 0.1 API supports native prim deletion"
    ),
)

_MESH_ACTION_IDS = {
    "Cone": "create.geometry.mesh.cone",
    "Cube": "create.geometry.mesh.cube",
    "Cylinder": "create.geometry.mesh.cylinder",
    "Disk": "create.geometry.mesh.disk",
    "Plane": "create.geometry.mesh.plane",
    "Sphere": "create.geometry.mesh.sphere",
    "Torus": "create.geometry.mesh.torus",
}
_SHAPE_ACTION_IDS = {
    "Capsule": "create.geometry.shape.capsule",
    "Cone": "create.geometry.shape.cone",
    "Cube": "create.geometry.shape.cube",
    "Cylinder": "create.geometry.shape.cylinder",
    "Sphere": "create.geometry.shape.sphere",
}
_LIGHT_ACTION_IDS = {
    "CylinderLight": "create.light.cylinder",
    "DiskLight": "create.light.disk",
    "DistantLight": "create.light.distant",
    "DomeLight": "create.light.dome",
    "RectLight": "create.light.rect",
    "SphereLight": "create.light.sphere",
}
@dataclass(frozen=True)
class OvstagePhysicsControlFailure:
    """Structured diagnostic for a provider-owned physics control failure."""

    provider_name: str
    entry_point_value: str
    operation: str
    scene_path: str | None
    exception_type: str
    exception_text: str


class OvstagePhysicsControlError(RuntimeError):
    """Raised when a provider-owned physics control transition fails."""

    def __init__(self, failure: OvstagePhysicsControlFailure) -> None:
        self.failure = failure
        self.module_name = failure.provider_name
        self.entry_point_value = failure.entry_point_value
        self.requirement_name = "ovphysx"
        self.exception_text = failure.exception_text
        scene_detail = f" for {failure.scene_path!r}" if failure.scene_path else ""
        super().__init__(
            f"{failure.operation} failed{scene_detail}: {failure.exception_text}"
        )


class OvstagePhysicsControls:
    """Provider-owned enable/play/stop/disable state for ovphysx."""

    def __init__(self, session: "OvstageProviderSession") -> None:
        self._session = session
        self._physx: Any | None = None
        self._usd_handle: int | None = None
        self._pose_binding: Any | None = None
        self._pose_buffer: np.ndarray | None = None
        self._pose_paths: tuple[str, ...] = ()
        self._pose_write_ordinals: deque[int] = deque(
            maxlen=PHYSICS_POSE_WRITE_HISTORY_LIMIT
        )
        self._attached_scene: OvstageScene | None = None
        self._playing = False
        self._accumulator_secs = 0.0
        self._simulation_time_secs = 0.0
        self._kinematic_targets: dict[str, tuple[float, ...]] = {}
        self._last_failure: OvstagePhysicsControlFailure | None = None

    @property
    def enabled(self) -> bool:
        return self._physx is not None and self._attached_scene is not None

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def has_physics_scene(self) -> bool:
        return self._usd_handle is not None

    @property
    def last_failure(self) -> OvstagePhysicsControlFailure | None:
        return self._last_failure

    @property
    def simulation_time(self) -> float:
        return self._simulation_time_secs

    def simulated_transform_paths_for_range(
        self,
        *,
        since_ordinal: int,
        current_ordinal: int,
    ) -> tuple[str, ...]:
        """Return PhysX-authored transform paths when they cover the full range."""
        if not self.enabled or not self._pose_paths:
            return ()
        try:
            since = int(since_ordinal)
            current = int(current_ordinal)
        except (TypeError, ValueError):
            return ()
        if current <= since:
            return ()

        expected_ordinals = tuple(range(since + 1, current + 1))
        if len(expected_ordinals) > len(self._pose_write_ordinals):
            return ()
        written_ordinals = tuple(
            ordinal
            for ordinal in self._pose_write_ordinals
            if since < int(ordinal) <= current
        )
        if written_ordinals != expected_ordinals:
            return ()
        return self._pose_paths

    def enable_label(self) -> str:
        return "Disable PhysX" if self.enabled else "Enable PhysX"

    def play_label(self) -> str:
        return "Stop Simulation" if self.playing else "Play Simulation"

    def can_toggle_enabled(self) -> bool:
        return self.enabled or self._active_scene() is not None

    def can_toggle_playing(self) -> bool:
        return self.playing or (self.enabled and self.has_physics_scene)

    def toggle_enabled(self) -> None:
        if self.enabled:
            self.disable()
            return
        self.enable()

    def toggle_playing(self) -> None:
        if self.playing:
            self.stop()
            return
        self.play()

    def enable(self) -> None:
        """Create/load ovphysx and bind rigid-body poses for the active scene."""
        scene = self._require_active_scene(PHYSICS_ENABLE_OPERATION)
        if self.enabled:
            if self._attached_scene is scene:
                return
            self.disable()

        self._last_failure = None
        physx = None
        usd_handle: int | None = None
        pose_binding = None
        try:
            physx_module = self._runtime_module("ovphysx")
            physx_type = getattr(physx_module, "PhysX")
            try:
                physx = physx_type(device="gpu")
            except Exception as exc:
                raise self._control_error(PHYSICS_CREATE_OPERATION, scene, exc) from exc

            usd_handle, op_index = physx.add_usd(scene.source_path)
            wait_op = getattr(physx, "wait_op", None)
            if callable(wait_op):
                wait_op(op_index)
            rigid_paths = _discover_rigid_body_paths(scene)
            pose_binding = _create_pose_binding(physx_module, physx, rigid_paths)
            pose_paths = _pose_binding_paths(pose_binding, rigid_paths)
            pose_buffer = np.zeros(tuple(pose_binding.shape), dtype=np.float32)
        except OvstagePhysicsControlError as exc:
            _add_cleanup_notes(
                exc,
                self._cleanup_partial_enable(physx, usd_handle, pose_binding),
            )
            raise
        except Exception as exc:
            error = self._control_error(PHYSICS_ENABLE_OPERATION, scene, exc)
            _add_cleanup_notes(
                error,
                self._cleanup_partial_enable(physx, usd_handle, pose_binding),
            )
            raise error from exc

        self._physx = physx
        self._usd_handle = int(usd_handle)
        self._pose_binding = pose_binding
        self._pose_buffer = pose_buffer
        self._pose_paths = tuple(pose_paths)
        self._attached_scene = scene
        self._playing = False
        self._accumulator_secs = 0.0
        self._simulation_time_secs = 0.0
        self._kinematic_targets.clear()
        self._pose_write_ordinals.clear()

    def play(self) -> None:
        """Enter the playing state; the per-frame stepping loop is Step 21."""
        scene = self._attached_scene or self._active_scene()
        if not self.enabled:
            raise self._control_error(
                PHYSICS_PLAY_OPERATION,
                scene,
                RuntimeError("physics is disabled"),
            )
        if not self.has_physics_scene:
            raise self._control_error(
                PHYSICS_PLAY_OPERATION,
                scene,
                RuntimeError("no physics scene has been loaded"),
            )
        self._last_failure = None
        self._playing = True

    def tick(self, delta_seconds: float | int | None) -> int:
        """Advance ovphysx in fixed substeps while simulation is playing.

        Each substep reads the ovphysx rigid-body pose tensor, writes the
        simulated transforms into ovstage on a new ordinal, and lets the
        renderer's existing dirty-ordinal path consume those changes.
        """
        if not self.playing:
            return 0
        if delta_seconds is None:
            return 0
        try:
            frame_dt = float(delta_seconds)
        except (TypeError, ValueError):
            return 0
        if frame_dt <= 0.0:
            return 0
        if not self.enabled:
            self._playing = False
            self._accumulator_secs = 0.0
            raise self._control_error(
                PHYSICS_STEP_OPERATION,
                self._attached_scene or self._active_scene(),
                RuntimeError("physics is disabled"),
            )

        self._accumulator_secs = min(
            self._accumulator_secs + frame_dt,
            PHYSICS_MAX_ACCUMULATED_TIME_SECS,
        )
        steps = 0
        while (
            self._accumulator_secs + 1.0e-12 >= PHYSICS_FIXED_TIME_STEP_SECS
            and steps < PHYSICS_MAX_SUBSTEPS_PER_TICK
        ):
            self._step_once()
            self._accumulator_secs -= PHYSICS_FIXED_TIME_STEP_SECS
            steps += 1

        if steps >= PHYSICS_MAX_SUBSTEPS_PER_TICK:
            self._accumulator_secs = min(
                self._accumulator_secs,
                PHYSICS_FIXED_TIME_STEP_SECS,
            )
        return steps

    def stop(self) -> None:
        """Pause fixed-step physics stepping."""
        self._playing = False

    def disable(self) -> None:
        """Stop, destroy the pose binding, and release physics resources."""
        physx = self._physx
        usd_handle = self._usd_handle
        pose_binding = self._pose_binding
        scene = self._attached_scene or self._active_scene()

        self.stop()
        self._physx = None
        self._usd_handle = None
        self._pose_binding = None
        self._pose_buffer = None
        self._pose_paths = ()
        self._attached_scene = None
        self._accumulator_secs = 0.0
        self._simulation_time_secs = 0.0
        self._kinematic_targets.clear()
        self._pose_write_ordinals.clear()

        if physx is None:
            return

        first_error: BaseException | None = None
        try:
            _wait_for_physx_idle(physx)
        except Exception as exc:
            first_error = exc

        if pose_binding is not None:
            destroy = getattr(pose_binding, "destroy", None)
            if callable(destroy):
                try:
                    destroy()
                except Exception as exc:
                    first_error = exc

        if usd_handle is not None:
            remove_usd = getattr(physx, "remove_usd", None)
            if callable(remove_usd):
                try:
                    op_index = remove_usd(usd_handle)
                    wait_op = getattr(physx, "wait_op", None)
                    if callable(wait_op):
                        wait_op(op_index)
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        try:
            _wait_for_physx_idle(physx)
        except Exception as exc:
            if first_error is None:
                first_error = exc

        release = getattr(physx, "release", None)
        if callable(release):
            try:
                release()
            except Exception as exc:
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            raise self._control_error(PHYSICS_DISABLE_OPERATION, scene, first_error)

    def can_apply_kinematic_target(self, path: str) -> bool:
        """Return true when running edits can be routed through controls."""
        return bool(path) and self.enabled and self.playing

    def set_kinematic_target(self, path: str, matrix: list[list[float]]) -> None:
        """Route a running kinematic-body edit through provider controls.

        Current ovphysx Python bindings may not expose a dedicated per-body
        target setter in every environment. The provider records the target
        and forwards it when a compatible method exists, without performing a
        raw ovstage transform write that would fight the solver.
        """
        scene = self._attached_scene or self._active_scene()
        if not self.can_apply_kinematic_target(path):
            raise self._control_error(
                PHYSICS_PLAY_OPERATION,
                scene,
                RuntimeError("kinematic target controls are unavailable"),
            )
        normalized_path = str(path)
        flat = _flatten_matrix4(matrix)
        self._kinematic_targets[normalized_path] = flat
        physx = self._physx
        if physx is None:
            return
        for method_name in (
            "set_kinematic_target",
            "set_control_target",
            "set_rigid_body_kinematic_target",
        ):
            method = getattr(physx, method_name, None)
            if callable(method):
                method(normalized_path, flat)
                break
        update_kinematic = getattr(physx, "update_articulations_kinematic", None)
        if callable(update_kinematic):
            update_kinematic()

    def get_kinematic_target(self, path: str) -> tuple[float, ...] | None:
        return self._kinematic_targets.get(str(path))

    def apply_step_bound_edit(self, edit_fn: Any) -> Any:
        """Run a reset/teleport edit at a pause boundary, then restore play."""
        was_playing = self.playing
        if was_playing:
            self.stop()
        try:
            return edit_fn()
        finally:
            if was_playing and self.enabled and self.has_physics_scene:
                self._playing = True

    def _step_once(self) -> None:
        physx = self._physx
        scene = self._attached_scene or self._active_scene()
        pose_binding = self._pose_binding
        pose_buffer = self._pose_buffer
        if (
            physx is None
            or scene is None
            or pose_binding is None
            or pose_buffer is None
            or not self._pose_paths
        ):
            self._playing = False
            self._accumulator_secs = 0.0
            raise self._control_error(
                PHYSICS_STEP_OPERATION,
                scene,
                RuntimeError("physics has no ovstage pose tensor binding"),
            )

        step_dt = PHYSICS_FIXED_TIME_STEP_SECS
        sim_time = self._simulation_time_secs
        try:
            step_sync = getattr(physx, "step_sync", None)
            if callable(step_sync):
                step_sync(step_dt, sim_time)
            else:
                step = getattr(physx, "step", None)
                if not callable(step):
                    raise RuntimeError("ovphysx runtime exposes no step method")
                op_index = step(step_dt, sim_time)
                wait_op = getattr(physx, "wait_op", None)
                if callable(wait_op):
                    wait_op(op_index)
        except Exception as exc:
            self._playing = False
            self._accumulator_secs = 0.0
            raise self._control_error(PHYSICS_STEP_OPERATION, scene, exc) from exc

        try:
            pose_binding.read(pose_buffer)
            ordinal = _write_pose_tensor_to_ovstage(
                scene,
                self._pose_paths,
                pose_buffer,
            )
            self._pose_write_ordinals.append(int(ordinal))
        except Exception as exc:
            self._playing = False
            self._accumulator_secs = 0.0
            raise self._control_error(PHYSICS_STEP_OPERATION, scene, exc) from exc

        self._simulation_time_secs = sim_time + step_dt

    def _runtime_module(self, requirement_name: str) -> Any:
        self._session.prepare_runtime_imports()
        runtime = self._session._runtime
        if runtime is None:
            raise RuntimeError("ovstage runtime preflight did not produce runtime modules")
        try:
            return runtime.module(requirement_name)
        except KeyError:
            if requirement_name != "ovphysx":
                raise
            return load_required_runtimes(
                module_name=PROVIDER_NAME,
                entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
                requirements=OPTIONAL_RUNTIME_REQUIREMENTS,
            ).module(requirement_name)

    def _active_scene(self) -> OvstageScene | None:
        scene = self._session.current_scene
        if scene is None or not scene.is_open:
            return None
        return scene

    def _require_active_scene(self, operation: str) -> OvstageScene:
        scene = self._active_scene()
        if scene is None:
            raise self._control_error(
                operation,
                None,
                RuntimeError("no active ovstage scene is open"),
            )
        return scene

    def _control_error(
        self,
        operation: str,
        scene: OvstageScene | None,
        exc: BaseException,
    ) -> OvstagePhysicsControlError:
        failure = OvstagePhysicsControlFailure(
            provider_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
            operation=operation,
            scene_path=scene.source_path if scene is not None else None,
            exception_type=type(exc).__name__,
            exception_text=f"{type(exc).__name__}: {exc}",
        )
        self._last_failure = failure
        return OvstagePhysicsControlError(failure)

    def _cleanup_partial_enable(
        self,
        physx: Any | None,
        usd_handle: int | None,
        pose_binding: Any | None,
    ) -> tuple[BaseException, ...]:
        cleanup_errors: list[BaseException] = []
        if physx is not None:
            try:
                _wait_for_physx_idle(physx)
            except Exception as exc:
                cleanup_errors.append(exc)
        if pose_binding is not None:
            try:
                destroy = getattr(pose_binding, "destroy", None)
                if callable(destroy):
                    destroy()
            except Exception as exc:
                cleanup_errors.append(exc)
        if physx is None:
            return tuple(cleanup_errors)
        if usd_handle is not None:
            try:
                remove_usd = getattr(physx, "remove_usd", None)
                if callable(remove_usd):
                    op_index = remove_usd(usd_handle)
                    wait_op = getattr(physx, "wait_op", None)
                    if callable(wait_op):
                        wait_op(op_index)
            except Exception as exc:
                cleanup_errors.append(exc)
        try:
            _wait_for_physx_idle(physx)
        except Exception as exc:
            cleanup_errors.append(exc)
        try:
            release = getattr(physx, "release", None)
            if callable(release):
                release()
        except Exception as exc:
            cleanup_errors.append(exc)
        return tuple(cleanup_errors)

class OvstageProviderSession:
    """Provider-owned application helpers for the ovstage scaffold."""

    name = PROVIDER_NAME
    allows_renderer_fallback = False

    def __init__(
        self,
        app: Any | None = None,
        runtime: LoadedRuntimes | None = None,
    ) -> None:
        self._app = app
        self._runtime = runtime
        self._current_scene: OvstageScene | None = None
        # A replacement candidate that could not be destroyed must remain
        # session-owned even though it was never made current.  Retaining it
        # permits deterministic cleanup retry and prevents a live native Stage
        # from becoming reachable only through a propagating exception.
        self._pending_scene_cleanup: list[OvstageScene] = []
        self._population_failures: list[OvstagePopulationFailure] = []
        self.physics_controls = OvstagePhysicsControls(self)
        self.prepare_runtime_imports()

    def prepare_runtime_imports(self) -> None:
        if self._runtime is None:
            self._runtime = load_required_runtimes(
                module_name=PROVIDER_NAME,
                entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
            )

    @property
    def current_scene(self) -> OvstageScene | None:
        return self._current_scene

    def inspector_native_token_attribute(
        self,
        stage: Any,
        path: str,
        name: str,
    ) -> Any:
        """Read one native token without exposing OVStage internals to widgets."""

        from ovui_data_adapters.ovstage._native import read_token_attribute

        return read_token_attribute(stage, str(path), str(name))

    def inspector_native_query_names(
        self,
        stage: Any,
        attributes: Any,
    ) -> tuple[str, ...]:
        """Resolve native query columns behind the provider boundary."""

        from ovui_data_adapters.ovstage._native import resolve_query_names

        return tuple(resolve_query_names(stage, attributes))

    def inspector_user_facing_scene_path(self, path: str) -> bool:
        """Expose the production ownership rule to the Inspector evidence.

        Delegates to the same scene-specific rule the stage adapter uses
        (scene-registered presentation roots plus the authored-``/Render``
        exception), so Inspector evidence filtering cannot drift from
        production filtering.
        """

        from ovui_data_adapters.ovstage.stage_adapter import (
            is_user_facing_scene_path,
        )

        scene = self.current_scene
        stage = None
        if scene is not None and getattr(scene, "is_open", False):
            stage = getattr(scene, "_stage", None)
        return is_user_facing_scene_path(path, scene, stage)

    @property
    def population_failures(self) -> tuple[OvstagePopulationFailure, ...]:
        return tuple(self._population_failures)

    def open_stage(self, path: str) -> OvstageScene:
        self.prepare_runtime_imports()
        self._drain_pending_scene_cleanup()
        try:
            scene = open_scene_from_file(
                runtime=self._runtime,
                path=path,
            )
            scene.attach_physics_controls(self.physics_controls)
        except Exception as exc:
            failure = getattr(exc, "failure", None)
            if isinstance(failure, OvstagePopulationFailure):
                self._population_failures.append(failure)
            raise
        prior_scene = self._current_scene
        try:
            self.physics_controls.disable()
        except Exception as exc:
            self._cleanup_rejected_scene(
                scene,
                primary=exc,
                action="candidate cleanup after physics disable failure",
            )
            raise
        try:
            if prior_scene is not None:
                prior_scene.shutdown()
        except Exception as exc:
            self._cleanup_rejected_scene(
                scene,
                primary=exc,
                action="candidate cleanup after active-scene close failure",
            )
            raise
        self._current_scene = scene
        return scene

    def shutdown_scene(self) -> None:
        errors: list[tuple[str, BaseException]] = []
        scene = self._current_scene
        if scene is not None:
            try:
                _trace_shutdown("physics_controls.disable begin")
                self.physics_controls.disable()
            except BaseException as exc:
                errors.append(("physics controls disable failed", exc))
                _trace_shutdown("physics_controls.disable raised; scene.shutdown begin")
            else:
                _trace_shutdown("physics_controls.disable complete; scene.shutdown begin")
            try:
                scene.shutdown()
            except BaseException as exc:
                # Keep the owner reference when BORROW detach fails.  Dropping
                # it would make a still-attached native Stage unreachable from
                # the provider and permit an unsafe replacement attempt.
                errors.append(("current scene shutdown failed", exc))
            else:
                self._current_scene = None
                _trace_shutdown("scene.shutdown complete")

        try:
            self._drain_pending_scene_cleanup()
        except BaseException as exc:
            errors.append(("rejected candidate cleanup failed", exc))

        if errors:
            _primary_action, primary = errors[0]
            for action, secondary in errors[1:]:
                _add_cleanup_note(primary, action, secondary)
            raise primary

    def _cleanup_rejected_scene(
        self,
        scene: OvstageScene,
        *,
        primary: BaseException,
        action: str,
    ) -> None:
        try:
            scene.shutdown()
        except BaseException as cleanup_error:
            self._retain_scene_for_cleanup(scene)
            _add_cleanup_note(primary, action, cleanup_error)
        else:
            self._forget_pending_scene(scene)

    def _drain_pending_scene_cleanup(self) -> None:
        errors: list[BaseException] = []
        for scene in tuple(getattr(self, "_pending_scene_cleanup", ())):
            try:
                scene.shutdown()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._forget_pending_scene(scene)
        if errors:
            primary = errors[0]
            for secondary in errors[1:]:
                _add_cleanup_note(
                    primary,
                    "additional rejected candidate cleanup failure",
                    secondary,
                )
            raise primary

    def _retain_scene_for_cleanup(self, scene: OvstageScene) -> None:
        pending = getattr(self, "_pending_scene_cleanup", None)
        if not isinstance(pending, list):
            pending = []
            self._pending_scene_cleanup = pending
        if not any(candidate is scene for candidate in pending):
            pending.append(scene)

    def _forget_pending_scene(self, scene: OvstageScene) -> None:
        pending = getattr(self, "_pending_scene_cleanup", None)
        if not isinstance(pending, list):
            return
        self._pending_scene_cleanup = [
            candidate for candidate in pending if candidate is not scene
        ]

    def create_stage(self, path: str) -> OvstageScene:
        """Reject durable document creation unsupported by OVStage 0.1."""

        raise NotImplementedError(
            _OVSTAGE_STAGE_CAPABILITIES.create_stage.reason
        )

    def get_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(stage=_OVSTAGE_STAGE_CAPABILITIES)

    def can_export_stage(self) -> bool:
        return self.get_capabilities().stage.export_stage.is_supported

    def export_stage(self, stage: Any, path: str) -> None:
        """Reject stage export unsupported by OVStage 0.1."""

        raise NotImplementedError(
            _OVSTAGE_STAGE_CAPABILITIES.export_stage.reason
        )

    def can_create_prims(self) -> bool:
        return self.get_capabilities().stage.create_prims.is_supported

    def can_delete_prims(self) -> bool:
        return self.get_capabilities().stage.delete_prims.is_supported

    def make_delete_prim_command(self, stage: Any, path: str) -> Any:
        scene = self.current_scene
        if scene is None or not scene.is_open:
            raise_not_ready("native prim deletion command")
        native_stage = getattr(scene, "_stage", None)
        value = str(path)
        if stage is not native_stage:
            raise_not_ready("native prim deletion command")
        if (
            not value.startswith("/")
            or value == "/"
            or value.endswith("/")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value[1:].split("/"))
        ):
            raise ValueError(f"native prim delete path is not canonical: {value!r}")
        if (
            value.startswith("/__")
            or value == "/TempChangeTracking"
            or value.startswith("/TempChangeTracking/")
            or value == "/omni_rtx_loadingStatePrim"
            or value.startswith("/omni_rtx_loadingStatePrim/")
            or any(
                value == str(root) or value.startswith(str(root) + "/")
                for root in scene.presentation_root_paths
            )
        ):
            raise ValueError(f"protected OVStage path cannot be deleted: {value}")
        if not _native_path_exists(native_stage, value):
            raise ValueError(f"native prim delete path does not exist: {value}")
        return NativeDeletePrimsCommand(scene, (value,))

    def create_renderer(self) -> Any:
        return OvstageRendererAdapter(
            undo_manager=_undo_manager_from_app(self._app),
        )

    def renderer_available(self) -> bool:
        return self._renderer_preflight_failure() is None

    def renderer_unavailable_reason(self) -> str:
        error = self._renderer_preflight_failure()
        if error is None:
            return ""
        return f"{type(error).__name__}: {error}"

    @staticmethod
    def _renderer_preflight_failure() -> BaseException | None:
        try:
            load_required_runtimes(
                module_name=PROVIDER_NAME,
                entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
                requirements=(OVRTX_RUNTIME_REQUIREMENT,),
            )
        except Exception as exc:
            return exc
        return None

    def create_livestream_tap(self) -> Any | None:
        from ovui_data_adapters.common._livestream_tap import LivestreamTap

        return LivestreamTap.maybe_create()

    def create_mesh_prim(self, app: Any, mesh_name: str) -> Any | None:
        action_id = _MESH_ACTION_IDS.get(mesh_name)
        return self._create_prim_action(app, action_id) if action_id else None

    def create_shape_prim(self, app: Any, shape_name: str) -> Any | None:
        action_id = _SHAPE_ACTION_IDS.get(shape_name)
        return self._create_prim_action(app, action_id) if action_id else None

    def create_light_prim(self, app: Any, light_type: str) -> Any | None:
        action_id = _LIGHT_ACTION_IDS.get(light_type)
        return self._create_prim_action(app, action_id) if action_id else None

    def create_camera(self, app: Any) -> Any | None:
        return self._create_prim_action(app, "create.camera")

    def create_scope(self, app: Any) -> Any | None:
        return self._create_prim_action(app, "create.scope")

    def create_xform(self, app: Any) -> Any | None:
        return self._create_prim_action(app, "create.xform")

    def create_usd_preview_surface_material(self, app: Any) -> Any | None:
        return self._create_prim_action(
            app,
            "create.material.usd-preview-surface",
        )

    def get_geometry_standard_prim_attrs(self, stage: Any) -> dict[str, dict[Any, Any]]:
        del stage
        raise_not_ready("native geometry attribute templates")

    def get_light_prim_attrs(self, stage: Any) -> dict[str, dict[Any, Any]]:
        del stage
        raise_not_ready("native light attribute templates")

    def get_next_free_prim_path(self, stage: Any, child_name: str) -> Any:
        del stage, child_name
        raise_not_ready("native prim path allocation")

    def get_next_free_path(self, stage: Any, base_path: Any) -> Any:
        del stage, base_path
        raise_not_ready("native prim path allocation")

    def _require_authoring_scene(self) -> OvstageScene:
        scene = self.current_scene
        if scene is None or not scene.is_open:
            raise RuntimeError("no active OVStage scene is available for authoring")
        return scene

    def _stage_adapter_for_authoring(self, app: Any) -> Any:
        adapter = _stage_adapter_from_app(app)
        if adapter is not None and (
            callable(getattr(adapter, "create_prim", None))
            or callable(getattr(adapter, "create_material", None))
        ):
            return adapter

        scene = self._require_authoring_scene()
        undo_manager = _undo_manager_from_app(app)
        call_later = getattr(app, "call_later", None) if app is not None else None
        return create_stage_adapter(scene, undo_manager, call_later)

    def _create_prim_action(self, app: Any, action_id: str) -> Any | None:
        adapter = self._stage_adapter_for_authoring(app)
        result = adapter.create_prim(
            CreateRequest(
                action_id,
                selection_paths=_selection_paths_from_app(app),
            )
        )
        if not getattr(result, "accepted", False):
            return None
        return self._authoring_prim(getattr(result, "primary_path", ""))

    def _authoring_prim(self, path: str) -> Any | None:
        return str(path) if path else None

    def _authoring_stage(self, stage: Any) -> Any:
        scene = self._require_authoring_scene()
        native_stage = getattr(scene, "_stage", None)
        if stage is native_stage:
            return stage
        return native_stage


def create_stage_adapter(
    scene: Any | None = None,
    undo_manager: Any | None = None,
    call_later: Any | None = None,
) -> OvstageStageAdapter:
    return OvstageStageAdapter(scene, undo_manager, call_later)


def create_property_adapter(
    scene: Any | None = None,
    paths: list[str] | None = None,
    undo_manager: Any | None = None,
    stage_adapter: Any | None = None,
) -> OvstagePropertyAdapter:
    return OvstagePropertyAdapter(scene, paths, undo_manager, stage_adapter)


def create_transform_adapter(scene: Any | None = None) -> OvstageTransformAdapter:
    return OvstageTransformAdapter(scene)


def create_layer_stack_adapter(
    scene: Any | None = None,
    undo_manager: Any | None = None,
) -> OvstageLayerStackAdapter:
    return OvstageLayerStackAdapter(scene, undo_manager)


def create_renderer_adapter(
    scene: Any | None = None,
    undo_manager: Any | None = None,
) -> OvstageRendererAdapter:
    return OvstageRendererAdapter(scene, undo_manager)


def create_selection_adapter(
    scene: Any | None = None,
    stage_adapter: Any | None = None,
) -> OvstageSelectionAdapter:
    return OvstageSelectionAdapter(scene, stage_adapter)


def create_provider_session(
    app: Any | None = None,
    runtime: LoadedRuntimes | None = None,
) -> OvstageProviderSession:
    return OvstageProviderSession(app, runtime)


def _discover_rigid_body_paths(scene: OvstageScene) -> tuple[str, ...]:
    stage = getattr(scene, "_stage", None)
    if stage is None:
        raise RuntimeError("ovstage scene has no native stage")
    current_ordinal = getattr(scene, "current_ordinal", None)
    if current_ordinal is None:
        raise RuntimeError("ovstage scene has no committed ordinal")
    query = stage.query_prims(
        int(current_ordinal),
        applied_schemas=["PhysicsRigidBodyAPI"],
    )
    paths: list[str] = []
    for group in query.get("groups", ()):
        schemas = resolve_query_names(stage, group.get("applied_schemas", ()))
        # The exact API-v2 compatibility helper accepts ``applied_schemas``
        # but currently returns an unfiltered result.  Require its native
        # schema evidence.  Older public-shaped providers that do not expose
        # the native attribute-info surface own the filtering contract and
        # may omit redundant group metadata.
        if (
            "PhysicsRigidBodyAPI" not in schemas
            and callable(getattr(stage, "read_attribute_info", None))
        ):
            continue
        handle = group.get("prim_list_handle")
        if handle is None:
            continue
        for path in stage.get_prim_paths(int(handle)):
            text = str(path)
            if text and text not in paths:
                paths.append(text)
    if not paths:
        raise RuntimeError("no PhysicsRigidBodyAPI prims were discovered in ovstage")
    return tuple(paths)


def _create_pose_binding(
    physx_module: Any,
    physx: Any,
    rigid_paths: tuple[str, ...],
) -> Any:
    tensor_type_owner = getattr(physx_module, "TensorType", None)
    tensor_type = getattr(tensor_type_owner, "RIGID_BODY_POSE", 1)
    create = getattr(physx, "create_tensor_binding", None)
    if not callable(create):
        raise RuntimeError("ovphysx runtime exposes no create_tensor_binding method")
    return create(
        prim_paths=list(rigid_paths),
        tensor_type=tensor_type,
        raise_if_empty=True,
    )


def _pose_binding_paths(
    pose_binding: Any,
    fallback_paths: tuple[str, ...],
) -> tuple[str, ...]:
    paths = tuple(str(path) for path in getattr(pose_binding, "prim_paths", ()) if str(path))
    if paths:
        return paths
    return fallback_paths


def _wait_for_physx_idle(physx: Any | None) -> None:
    if physx is None:
        return
    wait_all = getattr(physx, "wait_all", None)
    if callable(wait_all):
        wait_all()


def _write_pose_tensor_to_ovstage(
    scene: OvstageScene,
    prim_paths: tuple[str, ...],
    poses: np.ndarray,
) -> int:
    stage = getattr(scene, "_stage", None)
    if stage is None:
        raise RuntimeError("ovstage scene has no native stage")
    pose_array = np.asarray(poses, dtype=np.float32)
    if pose_array.ndim != 2 or pose_array.shape[1] < 7:
        raise RuntimeError(f"unexpected rigid-body pose tensor shape {pose_array.shape}")
    if pose_array.shape[0] != len(prim_paths):
        raise RuntimeError(
            "rigid-body pose tensor row count does not match prim path count "
            f"({pose_array.shape[0]} != {len(prim_paths)})"
        )

    matrices = [_matrix_from_pose_row(pose_array[index]) for index in range(len(prim_paths))]
    if supports_native_stage_writes(stage):
        ordinal = write_matrix_attribute(
            stage,
            prim_paths,
            "omni:xform",
            np.asarray(matrices, dtype=np.float64),
        )
        _update_hierarchy_world_xforms(scene, ordinal)
        return ordinal
    payload = b"".join(struct.pack("<16d", *matrix) for matrix in matrices)
    ordinal = int(stage.begin_frame())
    try:
        for attr_name in PHYSICS_XFORM_ATTRIBUTES:
            stage.write_attribute(ordinal, list(prim_paths), attr_name, payload)
        _update_hierarchy_world_xforms(scene, ordinal)
    except Exception:
        try:
            stage.end_frame(ordinal)
        finally:
            pass
        raise
    stage.end_frame(ordinal)
    return ordinal


def _matrix_from_pose_row(row: Any) -> tuple[float, ...]:
    px, py, pz, qx, qy, qz, qw = (float(row[index]) for index in range(7))
    xx = 2.0 * qx * qx
    yy = 2.0 * qy * qy
    zz = 2.0 * qz * qz
    xy = 2.0 * qx * qy
    xz = 2.0 * qx * qz
    yz = 2.0 * qy * qz
    wx = 2.0 * qw * qx
    wy = 2.0 * qw * qy
    wz = 2.0 * qw * qz
    return (
        1.0 - yy - zz,
        xy + wz,
        xz - wy,
        0.0,
        xy - wz,
        1.0 - xx - zz,
        yz + wx,
        0.0,
        xz + wy,
        yz - wx,
        1.0 - xx - yy,
        0.0,
        px,
        py,
        pz,
        1.0,
    )


def _update_hierarchy_world_xforms(
    scene: OvstageScene,
    ordinal: int,
) -> None:
    try:
        hierarchy = scene.hierarchy
        hierarchy.update_world_xforms(ordinal)
    except Exception:
        # The falling-cube proof scene has identity parent transforms. If the
        # hierarchy runtime is unavailable, keep worldMatrix in sync with the
        # solver pose so viewport picking/property reads still observe motion.
        # _write_pose_tensor_to_ovstage already wrote worldMatrix directly.
        return


def _add_cleanup_notes(
    error: BaseException,
    cleanup_errors: tuple[BaseException, ...],
) -> None:
    add_note = getattr(error, "add_note", None)
    if not callable(add_note):
        return
    for cleanup_error in cleanup_errors:
        add_note(
            "partial physics cleanup failed: "
            f"{type(cleanup_error).__name__}: {cleanup_error}"
        )


def _selection_paths_from_app(app: Any | None) -> tuple[str, ...]:
    if app is None:
        return ()
    getter = getattr(app, "get_selection_bus", None)
    bus = getter() if callable(getter) else None
    if bus is None:
        bus = getattr(app, "selection_bus", None)
    if bus is None:
        bus = getattr(app, "_selection_bus", None)
    snapshot_getter = getattr(bus, "get_snapshot", None)
    if not callable(snapshot_getter):
        return ()
    try:
        snapshot = snapshot_getter()
        paths = getattr(snapshot, "paths", None)
        return tuple(str(path) for path in paths()) if callable(paths) else ()
    except Exception:
        return ()


def _stage_adapter_from_app(app: Any | None) -> Any | None:
    if app is None:
        return None
    getter = getattr(app, "get_stage_adapter", None)
    if callable(getter):
        adapter = getter()
        if adapter is not None:
            return adapter
    adapter = getattr(app, "stage_adapter", None)
    if adapter is not None:
        return adapter
    legacy_getter = getattr(app, "_get_stage_adapter", None)
    if callable(legacy_getter):
        adapter = legacy_getter()
        if adapter is not None:
            return adapter
    return getattr(app, "_stage_adapter", None)


def _undo_manager_from_app(app: Any | None) -> Any | None:
    if app is None:
        return None
    getter = getattr(app, "get_undo_manager", None)
    if callable(getter):
        undo_manager = getter()
        if undo_manager is not None:
            return undo_manager
    undo_manager = getattr(app, "undo_manager", None)
    if undo_manager is not None:
        return undo_manager
    return getattr(app, "_undo_manager", None)


def _trace_shutdown(message: str) -> None:
    if os.environ.get(PHYSICS_TRACE_SHUTDOWN_ENV) != "1":
        return
    print(
        f"[OvstageProviderSession] shutdown_scene {message}",
        file=sys.stderr,
        flush=True,
    )


def _flatten_matrix4(matrix: Any) -> tuple[float, ...]:
    rows = [list(row) for row in matrix]
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise ValueError("kinematic target matrix must be 4x4")
    return tuple(float(value) for row in rows for value in row)


def build_factories(runtime: LoadedRuntimes | None = None) -> AdapterFactories:
    loaded_runtime = runtime
    if loaded_runtime is None:
        loaded_runtime = load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )

    return AdapterFactories(
        stage=create_stage_adapter,
        properties=create_property_adapter,
        transforms=create_transform_adapter,
        renderer=create_renderer_adapter,
        selection=create_selection_adapter,
        layers=create_layer_stack_adapter,
        session=lambda app=None: create_provider_session(app, loaded_runtime),
    )
