# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""Native OVStage scene construction, replacement, and ownership contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from ovui_data_adapters.ovstage import _scene, provider
from ovui_data_adapters.ovstage._scene import OvstageScene, OvstageSceneOpenError
from ovui_data_adapters.ovstage.provider import OvstageProviderSession
from ovui_data_adapters.ovstage.runtime_preflight import (
    LoadedRuntime,
    LoadedRuntimes,
    REQUIRED_RUNTIME_REQUIREMENTS,
)


def _runtime(stage_type, population_module: ModuleType) -> LoadedRuntimes:
    stage_module = ModuleType("ovstage_lifecycle_test")
    stage_module.Stage = stage_type
    stage_module.population = population_module
    return LoadedRuntimes(
        (LoadedRuntime(REQUIRED_RUNTIME_REQUIREMENTS[0], stage_module),)
    )


class _PopulationOperation:
    def __init__(self, events: list[str], error: BaseException | None = None) -> None:
        self._events = events
        self._error = error
        self.wait_calls = 0

    def wait(self):
        self.wait_calls += 1
        self._events.append("population.wait")
        if self._error is not None:
            raise self._error
        return True


def test_population_waits_before_frame_commit_and_scene_readiness() -> None:
    events: list[str] = []
    operation = _PopulationOperation(events)

    class Stage:
        def __init__(self, name=None):
            events.append(f"stage.construct:{name}")
            self.current_ordinal = 0
            self._inst = True

        def begin_frame(self):
            events.append("frame.begin")
            return 1

        def end_frame(self, ordinal):
            events.append(f"frame.end:{ordinal}")
            self.current_ordinal = int(ordinal)

        def get_child_paths(self, parent):
            events.append(f"roots.ready:{parent}")
            return ("/World",)

        def destroy(self):
            events.append("stage.destroy")
            self._inst = False

    population = ModuleType("population")

    def open_usd_async(stage, path, ordinal):
        events.append(f"population.enqueue:{Path(path).name}:{ordinal}")
        return operation

    population.open_usd_async = open_usd_async
    scene = _scene.open_scene_from_file(
        runtime=_runtime(Stage, population),
        path="scene.usda",
    )

    assert scene.root_paths == ("/World",)
    assert scene.initial_ordinal == 1
    assert scene.current_ordinal == 1
    assert operation.wait_calls == 1
    assert events == [
        "stage.construct:ovui ovstage provider",
        "frame.begin",
        "population.enqueue:scene.usda:1",
        "population.wait",
        "frame.end:1",
        "roots.ready:",
    ]

    scene.shutdown()
    scene.shutdown()
    assert events.count("stage.destroy") == 1
    assert scene.is_open is False


def test_failed_population_ends_frame_and_preserves_cleanup_diagnostics() -> None:
    events: list[str] = []
    operation = _PopulationOperation(events, ValueError("population primary"))

    class Stage:
        def __init__(self, name=None):
            self.current_ordinal = 0
            self._inst = True
            events.append("construct")

        def begin_frame(self):
            events.append("begin")
            return 1

        def end_frame(self, ordinal):
            events.append(f"end:{ordinal}")
            self.current_ordinal = int(ordinal)

        def destroy(self):
            events.append("destroy")
            raise RuntimeError("destroy secondary")

    population = ModuleType("population")
    population.open_usd_async = lambda stage, path, ordinal: operation

    with pytest.raises(OvstageSceneOpenError, match="population primary") as caught:
        _scene.open_scene_from_file(
            runtime=_runtime(Stage, population),
            path="broken.usda",
        )

    assert events == ["construct", "begin", "population.wait", "end:1", "destroy"]
    assert caught.value.failure.exception_type == "ValueError"
    assert caught.value.__cause__.__class__ is ValueError
    assert caught.value.__notes__ == [
        "destroy failed candidate stage: RuntimeError: destroy secondary"
    ]


def test_failed_frame_end_is_not_retried_and_primary_population_error_survives() -> None:
    events: list[str] = []
    operation = _PopulationOperation(events, ValueError("population primary"))

    class Stage:
        def __init__(self, name=None):
            self.current_ordinal = 0
            self._inst = True

        def begin_frame(self):
            events.append("begin")
            return 4

        def end_frame(self, ordinal):
            events.append(f"end:{ordinal}")
            raise RuntimeError("end secondary")

        def destroy(self):
            events.append("destroy")
            self._inst = False

    population = ModuleType("population")
    population.open_usd_async = lambda stage, path, ordinal: operation

    with pytest.raises(OvstageSceneOpenError, match="population primary") as caught:
        _scene.open_scene_from_file(
            runtime=_runtime(Stage, population),
            path="broken.usda",
        )

    assert events == ["begin", "population.wait", "end:4", "destroy"]
    assert caught.value.__notes__ == [
        "end failed population frame: RuntimeError: end secondary"
    ]


def test_stage_construction_failure_is_structured_without_population() -> None:
    population_calls: list[str] = []

    class Stage:
        def __init__(self, name=None):
            raise RuntimeError("construction primary")

    population = ModuleType("population")
    population.open_usd_async = lambda *args: population_calls.append("populate")

    with pytest.raises(OvstageSceneOpenError, match="construction primary") as caught:
        _scene.open_scene_from_file(
            runtime=_runtime(Stage, population),
            path="scene.usda",
        )

    assert caught.value.failure.ordinal is None
    assert caught.value.failure.exception_type == "RuntimeError"
    assert population_calls == []


class _Physics:
    def __init__(self, events: list[str], error: BaseException | None = None) -> None:
        self.events = events
        self.error = error

    def disable(self) -> None:
        self.events.append("physics.disable")
        if self.error is not None:
            raise self.error


class _ProviderScene:
    def __init__(
        self,
        name: str,
        events: list[str],
        shutdown_error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.shutdown_error = shutdown_error
        self.shutdown_calls = 0
        self.physics_controls = None

    def attach_physics_controls(self, controls) -> None:
        self.physics_controls = controls
        self.events.append(f"{self.name}.attach_physics")

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.events.append(f"{self.name}.shutdown")
        if self.shutdown_error is not None:
            raise self.shutdown_error


def _session(events: list[str]) -> OvstageProviderSession:
    session = OvstageProviderSession(runtime=object())
    session.physics_controls = _Physics(events)
    return session


def test_successful_replacement_installs_candidate_after_old_close(monkeypatch) -> None:
    events: list[str] = []
    session = _session(events)
    old = _ProviderScene("old", events)
    candidate = _ProviderScene("candidate", events)
    session._current_scene = old
    monkeypatch.setattr(provider, "open_scene_from_file", lambda **kwargs: candidate)

    result = session.open_stage("candidate.usda")

    assert result is candidate
    assert session.current_scene is candidate
    assert old.shutdown_calls == 1
    assert candidate.shutdown_calls == 0
    assert events == [
        "candidate.attach_physics",
        "physics.disable",
        "old.shutdown",
    ]


def test_failed_candidate_open_preserves_current_scene(monkeypatch) -> None:
    events: list[str] = []
    session = _session(events)
    old = _ProviderScene("old", events)
    session._current_scene = old

    def fail(**kwargs):
        raise OvstageSceneOpenError(
            _scene.OvstagePopulationFailure(
                provider_name="ovstage",
                entry_point_value="provider",
                operation="population",
                path="missing.usda",
                ordinal=1,
                exception_type="RuntimeError",
                exception_text="missing",
            )
        )

    monkeypatch.setattr(provider, "open_scene_from_file", fail)

    with pytest.raises(OvstageSceneOpenError):
        session.open_stage("missing.usda")

    assert session.current_scene is old
    assert old.shutdown_calls == 0
    assert len(session.population_failures) == 1


def test_replacement_preserves_primary_and_retains_failed_candidate_cleanup(
    monkeypatch,
) -> None:
    events: list[str] = []
    session = _session(events)
    old_error = RuntimeError("old primary")
    cleanup_error = RuntimeError("candidate cleanup secondary")
    old = _ProviderScene("old", events, old_error)
    candidate = _ProviderScene("candidate", events, cleanup_error)
    session._current_scene = old
    monkeypatch.setattr(provider, "open_scene_from_file", lambda **kwargs: candidate)

    with pytest.raises(RuntimeError, match="old primary") as caught:
        session.open_stage("candidate.usda")

    assert session.current_scene is old
    assert session._pending_scene_cleanup == [candidate]
    assert caught.value is old_error
    assert caught.value.__notes__ == [
        "candidate cleanup after active-scene close failure: "
        "RuntimeError: candidate cleanup secondary"
    ]

    old.shutdown_error = None
    candidate.shutdown_error = None
    session.shutdown_scene()
    assert session.current_scene is None
    assert session._pending_scene_cleanup == []
    assert old.shutdown_calls == 2
    assert candidate.shutdown_calls == 2


def test_shutdown_preserves_physics_primary_and_retries_scene_cleanup() -> None:
    events: list[str] = []
    physics_error = RuntimeError("physics primary")
    scene_error = RuntimeError("scene cleanup secondary")
    session = _session(events)
    session.physics_controls.error = physics_error
    active = _ProviderScene("active", events, scene_error)
    session._current_scene = active

    with pytest.raises(RuntimeError, match="physics primary") as caught:
        session.shutdown_scene()

    assert caught.value is physics_error
    assert caught.value.__notes__ == [
        "current scene shutdown failed: RuntimeError: scene cleanup secondary"
    ]
    assert session.current_scene is active

    session.physics_controls.error = None
    active.shutdown_error = None
    session.shutdown_scene()
    session.shutdown_scene()
    assert session.current_scene is None
    assert active.shutdown_calls == 2


class _OrderedBorrowers:
    def __init__(self, values) -> None:
        self.values = list(values)

    def __iter__(self):
        return iter(tuple(self.values))

    def __len__(self):
        return len(self.values)

    def __bool__(self):
        return bool(self.values)

    def discard(self, value) -> None:
        self.values = [item for item in self.values if item is not value]


class _NativeStage:
    current_ordinal = 1

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self._inst = True

    def destroy(self) -> None:
        self.events.append("stage.destroy")
        self._inst = False


def test_scene_attempts_every_renderer_and_keeps_stage_for_detach_retry() -> None:
    events: list[str] = []
    stage = _NativeStage(events)
    scene = OvstageScene(
        stage=stage,
        source_path="scene.usda",
        initial_ordinal=1,
        root_paths=("/World",),
    )

    class Renderer:
        def __init__(self, name, error=None):
            self.name = name
            self.error = error

        def shutdown(self):
            events.append(self.name)
            if self.error is not None:
                raise self.error
            scene.detach_renderer(self)

    failed = Renderer("renderer.failed", RuntimeError("detach primary"))
    detached = Renderer("renderer.detached")
    scene._attached_renderers = _OrderedBorrowers([failed, detached])

    with pytest.raises(RuntimeError, match="detach primary"):
        scene.shutdown()

    assert events == ["renderer.failed", "renderer.detached"]
    assert scene.is_open is True
    assert scene._attached_renderers.values == [failed]

    failed.error = None
    scene.shutdown()
    assert events[-2:] == ["renderer.failed", "stage.destroy"]
    assert scene.is_open is False


def test_scene_releases_public_resources_before_stage_once() -> None:
    events: list[str] = []
    stage = _NativeStage(events)
    scene = OvstageScene(
        stage=stage,
        source_path="scene.usda",
        initial_ordinal=1,
        root_paths=("/World",),
    )

    class Stream:
        def close(self):
            events.append("stream.close")

    class ReleaseOperation:
        def wait(self):
            events.append("hierarchy.release.wait")

    class Hierarchy:
        def release(self):
            events.append("hierarchy.release")
            return ReleaseOperation()

    scene._change_stream = Stream()
    scene._hierarchy = Hierarchy()
    scene.attach_physics_controls(object())

    scene.shutdown()
    scene.shutdown()

    assert events == [
        "stream.close",
        "hierarchy.release",
        "hierarchy.release.wait",
        "stage.destroy",
    ]
    assert scene._change_stream is None
    assert scene._hierarchy is None
    assert scene.physics_controls is None


def test_scene_resource_release_failure_blocks_destroy_and_is_retryable() -> None:
    events: list[str] = []
    stage = _NativeStage(events)
    scene = OvstageScene(
        stage=stage,
        source_path="scene.usda",
        initial_ordinal=1,
        root_paths=("/World",),
    )

    class ReleaseOperation:
        error = RuntimeError("release primary")

        def wait(self):
            events.append("release.wait")
            if self.error is not None:
                raise self.error

    operation = ReleaseOperation()

    class Hierarchy:
        def release(self):
            events.append("hierarchy.release")
            return operation

    hierarchy = Hierarchy()
    scene._hierarchy = hierarchy

    with pytest.raises(RuntimeError, match="release primary"):
        scene.shutdown()

    assert scene.is_open is True
    assert scene._hierarchy is hierarchy
    assert "stage.destroy" not in events

    operation.error = None
    scene.shutdown()
    assert events[-1] == "stage.destroy"
    assert scene.is_open is False


def test_scene_preserves_primary_across_multiple_resource_cleanup_failures() -> None:
    events: list[str] = []
    stage = _NativeStage(events)
    scene = OvstageScene(
        stage=stage,
        source_path="scene.usda",
        initial_ordinal=1,
        root_paths=("/World",),
    )
    stream_error = RuntimeError("stream primary")
    hierarchy_error = RuntimeError("hierarchy secondary")

    class Stream:
        error = stream_error

        def close(self):
            events.append("stream.close")
            if self.error is not None:
                raise self.error

    class ReleaseOperation:
        error = hierarchy_error

        def wait(self):
            events.append("hierarchy.wait")
            if self.error is not None:
                raise self.error

    stream = Stream()
    operation = ReleaseOperation()
    scene._change_stream = stream
    scene._hierarchy = type(
        "Hierarchy",
        (),
        {"release": lambda self: operation},
    )()

    with pytest.raises(RuntimeError, match="stream primary") as caught:
        scene.shutdown()

    assert caught.value is stream_error
    assert caught.value.__notes__ == [
        "additional native scene-resource cleanup failure: "
        "RuntimeError: hierarchy secondary"
    ]
    assert scene.is_open is True
    assert "stage.destroy" not in events

    stream.error = None
    operation.error = None
    scene.shutdown()
    assert scene.is_open is False
    assert events[-1] == "stage.destroy"


def test_stage_destroy_failure_restores_scene_owner_for_retry() -> None:
    events: list[str] = []

    class Stage(_NativeStage):
        error = RuntimeError("destroy primary")

        def destroy(self):
            events.append("stage.destroy")
            if self.error is not None:
                raise self.error
            self._inst = False

    stage = Stage(events)
    scene = OvstageScene(
        stage=stage,
        source_path="scene.usda",
        initial_ordinal=1,
        root_paths=("/World",),
    )

    with pytest.raises(RuntimeError, match="destroy primary"):
        scene.shutdown()

    assert scene.is_open is True
    assert scene._stage is stage

    stage.error = None
    scene.shutdown()
    assert scene.is_open is False
    assert events == ["stage.destroy", "stage.destroy"]


def test_stale_scene_close_cannot_close_current_replacement() -> None:
    old_events: list[str] = []
    current_events: list[str] = []
    old = OvstageScene(
        stage=_NativeStage(old_events),
        source_path="old.usda",
        initial_ordinal=1,
        root_paths=("/Old",),
    )
    current = OvstageScene(
        stage=_NativeStage(current_events),
        source_path="current.usda",
        initial_ordinal=1,
        root_paths=("/Current",),
    )
    session = OvstageProviderSession(runtime=object())
    session._current_scene = current

    old.shutdown()

    assert session.current_scene is current
    assert current.is_open is True
    assert old.is_open is False
    assert old_events == ["stage.destroy"]
    assert current_events == []

    session.physics_controls = _Physics(current_events)
    session.shutdown_scene()
    assert current_events == ["physics.disable", "stage.destroy"]


def test_exact_runtime_lifecycle_subprocess_stays_forbidden_module_free(
    tmp_path: Path,
) -> None:
    scene_path = tmp_path / "lifecycle.usda"
    scene_path.write_text(
        '#usda 1.0\n\ndef Xform "World"\n{\n    def Cube "Item" {}\n}\n'
    )
    missing_path = tmp_path / "missing.usda"
    code = r'''
import importlib.abc
import json
from pathlib import Path
import sys

forbidden = ("pxr", "ovui_data_adapters.openusd")
class Blocker(importlib.abc.MetaPathFinder):
    def __init__(self): self.attempts = []
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == root or fullname.startswith(root + ".") for root in forbidden):
            self.attempts.append(fullname)
            raise ModuleNotFoundError(fullname, name=fullname)
        return None
blocker = Blocker()
sys.meta_path.insert(0, blocker)
import ovstage
from ovui_data_adapters.ovstage.provider import OvstageProviderSession
from ovui_data_adapters.ovstage.runtime_preflight import LoadedRuntime, LoadedRuntimes, REQUIRED_RUNTIME_REQUIREMENTS
runtime = LoadedRuntimes((LoadedRuntime(REQUIRED_RUNTIME_REQUIREMENTS[0], ovstage),))
session = OvstageProviderSession(runtime=runtime)
scene = session.open_stage(sys.argv[1])
assert scene.root_paths == ("/World",)
assert scene.current_ordinal == scene.initial_ordinal == 1
try:
    session.open_stage(sys.argv[2])
except Exception as exc:
    failed = type(exc).__name__
else:
    raise AssertionError("missing scene opened")
assert session.current_scene is scene
session.shutdown_scene()
session.shutdown_scene()
loaded = sorted(name for name in sys.modules if any(name == root or name.startswith(root + ".") for root in forbidden))
print(json.dumps({"attempts": blocker.attempts, "loaded": loaded, "failed": failed, "open": scene.is_open}))
'''
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code, str(scene_path), str(missing_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "attempts": [],
        "loaded": [],
        "failed": "OvstageSceneOpenError",
        "open": False,
    }
