# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Provider-owned ovphysx enable/play/stop/disable controls."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from ovui_data_adapters.ovstage.provider import (
    PHYSICS_CREATE_OPERATION,
    PHYSICS_DISABLE_OPERATION,
    PHYSICS_ENABLE_OPERATION,
    PHYSICS_PLAY_OPERATION,
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    OvstagePhysicsControlError,
    OvstagePhysicsControls,
)


class _Runtime:
    def __init__(self, physx_module: "_FakeOvphysxModule") -> None:
        self._physx_module = physx_module

    def module(self, requirement_name: str):
        if requirement_name != "ovphysx":
            raise KeyError(requirement_name)
        return self._physx_module


class _FakeOvphysxModule:
    def __init__(self) -> None:
        self.TensorType = SimpleNamespace(RIGID_BODY_POSE=1)
        self.instances: list[_FakePhysX] = []
        self.create_error: BaseException | None = None
        self.add_error: BaseException | None = None
        self.binding_error: BaseException | None = None
        self.binding_destroy_error: BaseException | None = None
        self.remove_error: BaseException | None = None
        self.release_error: BaseException | None = None

    def PhysX(self, *args, **kwargs) -> "_FakePhysX":
        if self.create_error is not None:
            raise self.create_error
        instance = _FakePhysX(self, args, kwargs)
        self.instances.append(instance)
        return instance


class _FakePhysX:
    def __init__(
        self,
        module: _FakeOvphysxModule,
        args: tuple,
        kwargs: dict,
    ) -> None:
        self._module = module
        self.calls: list[tuple] = [("create", args, kwargs)]
        self.loaded_usd_handle: int | None = None
        self.released = False

    def add_usd(self, source_path: str, path_prefix: str = "") -> tuple[int, int]:
        self.calls.append(("add_usd", source_path, path_prefix))
        if self._module.add_error is not None:
            raise self._module.add_error
        self.loaded_usd_handle = 17
        return 17, 101

    def wait_op(self, op_index: int) -> None:
        self.calls.append(("wait_op", op_index))

    def wait_all(self) -> None:
        self.calls.append(("wait_all",))

    def create_tensor_binding(
        self,
        *,
        prim_paths: list[str],
        tensor_type: int,
        raise_if_empty: bool,
    ) -> "_FakeTensorBinding":
        self.calls.append((
            "create_tensor_binding",
            tuple(prim_paths),
            tensor_type,
            raise_if_empty,
        ))
        if self._module.binding_error is not None:
            raise self._module.binding_error
        return _FakeTensorBinding(self, prim_paths)

    def remove_usd(self, usd_handle: int) -> int:
        self.calls.append(("remove_usd", usd_handle))
        if self._module.remove_error is not None:
            raise self._module.remove_error
        self.loaded_usd_handle = None
        return 202

    def release(self) -> None:
        self.calls.append(("release",))
        if self._module.release_error is not None:
            raise self._module.release_error
        self.released = True


class _FakeTensorBinding:
    def __init__(self, physx: _FakePhysX, prim_paths: list[str]) -> None:
        self._physx = physx
        self.shape = (len(prim_paths), 7)
        self.prim_paths = list(prim_paths)
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True
        self._physx.calls.append(("destroy_tensor_binding",))
        if self._physx._module.binding_destroy_error is not None:
            raise self._physx._module.binding_destroy_error


class _FakeStage:
    def __init__(self, handle: int) -> None:
        self._handle = SimpleNamespace(value=handle)
        self.current_ordinal = 1

    def query_prims(self, ordinal: int, *, applied_schemas: list[str], **kwargs):
        assert ordinal == self.current_ordinal
        assert applied_schemas == ["PhysicsRigidBodyAPI"]
        return {"groups": ({"prim_list_handle": 1},)}

    def get_prim_paths(self, prim_list_handle: int) -> list[str]:
        assert prim_list_handle == 1
        return ["/World/DynamicCube"]


class _FakeScene:
    def __init__(self, source_path: str = "/tmp/physics_scene.usda", handle: int = 1234) -> None:
        self.source_path = source_path
        self._stage = _FakeStage(handle)
        self.is_open = True

    @property
    def current_ordinal(self) -> int:
        return int(self._stage.current_ordinal)


def _controls(scene: _FakeScene | None = None, module: _FakeOvphysxModule | None = None):
    physx_module = module or _FakeOvphysxModule()
    session = SimpleNamespace(
        _runtime=_Runtime(physx_module),
        current_scene=scene,
        prepare_runtime_imports=lambda: None,
    )
    return OvstagePhysicsControls(session), physx_module


def test_enable_loads_same_usd_waits_and_binds_rigid_body_pose_tensor() -> None:
    scene = _FakeScene("/assets/rigid_body_scene.usda", handle=0xABC)
    controls, physx_module = _controls(scene)

    controls.enable()

    instance = physx_module.instances[0]
    assert instance.calls == [
        ("create", (), {"device": "gpu"}),
        ("add_usd", "/assets/rigid_body_scene.usda", ""),
        ("wait_op", 101),
        ("create_tensor_binding", ("/World/DynamicCube",), 1, True),
    ]
    assert instance.loaded_usd_handle == 17
    assert instance.released is False
    assert controls.enable_label() == "Disable PhysX"
    assert controls.play_label() == "Play Simulation"
    assert controls.can_toggle_playing() is True


def test_play_and_stop_pause_without_releasing_resources() -> None:
    scene = _FakeScene()
    controls, physx_module = _controls(scene)
    controls.enable()

    controls.play()
    controls.stop()

    instance = physx_module.instances[0]
    assert [call[0] for call in instance.calls] == [
        "create",
        "add_usd",
        "wait_op",
        "create_tensor_binding",
    ]
    assert instance.loaded_usd_handle == 17
    assert instance.released is False
    assert controls.play_label() == "Play Simulation"


def test_disable_stops_destroys_binding_removes_usd_waits_and_releases_resources() -> None:
    scene = _FakeScene()
    controls, physx_module = _controls(scene)
    controls.enable()
    controls.play()

    controls.disable()

    instance = physx_module.instances[0]
    assert instance.calls == [
        ("create", (), {"device": "gpu"}),
        ("add_usd", "/tmp/physics_scene.usda", ""),
        ("wait_op", 101),
        ("create_tensor_binding", ("/World/DynamicCube",), 1, True),
        ("wait_all",),
        ("destroy_tensor_binding",),
        ("remove_usd", 17),
        ("wait_op", 202),
        ("wait_all",),
        ("release",),
    ]
    assert instance.loaded_usd_handle is None
    assert instance.released is True
    assert controls.enable_label() == "Enable PhysX"
    assert controls.can_toggle_playing() is False


def test_repeated_toggles_release_prior_instance_and_create_fresh_instance() -> None:
    scene = _FakeScene()
    controls, physx_module = _controls(scene)

    controls.toggle_enabled()
    first = physx_module.instances[0]
    controls.toggle_playing()
    controls.toggle_playing()
    controls.toggle_enabled()
    controls.toggle_enabled()

    second = physx_module.instances[1]
    assert first.released is True
    assert second.released is False
    assert len(physx_module.instances) == 2
    assert [call[0] for call in first.calls] == [
        "create",
        "add_usd",
        "wait_op",
        "create_tensor_binding",
        "wait_all",
        "destroy_tensor_binding",
        "remove_usd",
        "wait_op",
        "wait_all",
        "release",
    ]


def test_play_is_blocked_when_physics_is_disabled() -> None:
    scene = _FakeScene()
    controls, physx_module = _controls(scene)

    with pytest.raises(OvstagePhysicsControlError) as exc_info:
        controls.play()

    failure = exc_info.value.failure
    assert failure.provider_name == PROVIDER_NAME
    assert failure.entry_point_value == PROVIDER_ENTRY_POINT_VALUE
    assert failure.operation == PHYSICS_PLAY_OPERATION
    assert failure.scene_path == scene.source_path
    assert failure.exception_type == "RuntimeError"
    assert "physics is disabled" in failure.exception_text
    assert physx_module.instances == []
    assert controls.last_failure == failure


def test_enable_is_blocked_without_an_active_ovstage_scene() -> None:
    controls, physx_module = _controls(None)

    with pytest.raises(OvstagePhysicsControlError) as exc_info:
        controls.enable()

    failure = exc_info.value.failure
    assert failure.operation == PHYSICS_ENABLE_OPERATION
    assert failure.scene_path is None
    assert "no active ovstage scene is open" in failure.exception_text
    assert physx_module.instances == []
    assert controls.can_toggle_enabled() is False


def test_ovphysx_create_failure_is_structured_and_leaves_no_instance() -> None:
    scene = _FakeScene()
    module = _FakeOvphysxModule()
    module.create_error = RuntimeError("mock create failed")
    controls, physx_module = _controls(scene, module)

    with pytest.raises(OvstagePhysicsControlError) as exc_info:
        controls.enable()

    failure = exc_info.value.failure
    assert failure.operation == PHYSICS_CREATE_OPERATION
    assert failure.provider_name == PROVIDER_NAME
    assert failure.entry_point_value == PROVIDER_ENTRY_POINT_VALUE
    assert failure.scene_path == scene.source_path
    assert failure.exception_type == "RuntimeError"
    assert "mock create failed" in failure.exception_text
    assert exc_info.value.requirement_name == "ovphysx"
    assert physx_module.instances == []
    assert controls.last_failure == failure


def test_tensor_binding_failure_releases_partially_loaded_physics_resources() -> None:
    scene = _FakeScene()
    module = _FakeOvphysxModule()
    module.binding_error = RuntimeError("mock binding failed")
    controls, physx_module = _controls(scene, module)

    with pytest.raises(OvstagePhysicsControlError) as exc_info:
        controls.enable()

    instance = physx_module.instances[0]
    assert instance.calls == [
        ("create", (), {"device": "gpu"}),
        ("add_usd", "/tmp/physics_scene.usda", ""),
        ("wait_op", 101),
        ("create_tensor_binding", ("/World/DynamicCube",), 1, True),
        ("wait_all",),
        ("remove_usd", 17),
        ("wait_op", 202),
        ("wait_all",),
        ("release",),
    ]
    assert instance.loaded_usd_handle is None
    assert instance.released is True
    assert exc_info.value.failure.operation == PHYSICS_ENABLE_OPERATION
    assert controls.enable_label() == "Enable PhysX"
    assert controls.can_toggle_playing() is False


def test_disable_cleanup_failure_is_structured_after_release_attempt() -> None:
    scene = _FakeScene()
    module = _FakeOvphysxModule()
    controls, physx_module = _controls(scene, module)
    controls.enable()
    module.binding_destroy_error = RuntimeError("mock binding destroy failed")

    with pytest.raises(OvstagePhysicsControlError) as exc_info:
        controls.disable()

    instance = physx_module.instances[0]
    assert instance.calls == [
        ("create", (), {"device": "gpu"}),
        ("add_usd", "/tmp/physics_scene.usda", ""),
        ("wait_op", 101),
        ("create_tensor_binding", ("/World/DynamicCube",), 1, True),
        ("wait_all",),
        ("destroy_tensor_binding",),
        ("remove_usd", 17),
        ("wait_op", 202),
        ("wait_all",),
        ("release",),
    ]
    assert instance.loaded_usd_handle is None
    assert instance.released is True
    failure = exc_info.value.failure
    assert failure.operation == PHYSICS_DISABLE_OPERATION
    assert failure.scene_path == scene.source_path
    assert "mock binding destroy failed" in failure.exception_text
    assert controls.enable_label() == "Enable PhysX"
    assert controls.can_toggle_playing() is False


def test_enable_reports_optional_ovphysx_import_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _FakeScene()

    class _RuntimeWithoutPhysx:
        def module(self, requirement_name: str):
            raise KeyError(requirement_name)

    def fail_lazy_physx_load(*args, **kwargs):
        raise ModuleNotFoundError("mocked missing optional ovphysx", name="ovphysx")

    provider_module = sys.modules[OvstagePhysicsControls.__module__]
    monkeypatch.setattr(provider_module, "load_required_runtimes", fail_lazy_physx_load)

    session = SimpleNamespace(
        _runtime=_RuntimeWithoutPhysx(),
        current_scene=scene,
        prepare_runtime_imports=lambda: None,
    )
    controls = OvstagePhysicsControls(session)

    with pytest.raises(OvstagePhysicsControlError) as exc_info:
        controls.enable()

    failure = exc_info.value.failure
    assert failure.operation == PHYSICS_ENABLE_OPERATION
    assert failure.provider_name == PROVIDER_NAME
    assert failure.entry_point_value == PROVIDER_ENTRY_POINT_VALUE
    assert failure.scene_path == scene.source_path
    assert failure.exception_type == "ModuleNotFoundError"
    assert "mocked missing optional ovphysx" in failure.exception_text
    assert controls.enable_label() == "Enable PhysX"
    assert controls.last_failure == failure
