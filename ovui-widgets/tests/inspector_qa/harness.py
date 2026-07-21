# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Subprocess and evidence harness for state-guided real ovui Inspector QA.

Every interaction captures screenshot + application state immediately before
and after the HTTP input command. Target coordinates may come from that state,
so this is not strict screenshot-first evidence. The state endpoint is
read-only; all mutations continue to use the same mouse/keyboard path as a user.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_REAL_INPUT_TIMEOUT = 60.0


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _prepend_paths(paths: list[Path], existing: str) -> str:
    entries: list[str] = []
    for path in paths:
        text = str(path)
        if text and text not in entries:
            entries.append(text)
    for text in existing.split(os.pathsep):
        if text and text not in entries:
            entries.append(text)
    return os.pathsep.join(entries)


def _request_error_detail(exc: BaseException) -> str:
    """Retain FastAPI's structured error body in Inspector failures."""

    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        if body:
            return f"{exc}; response={body}"
    return str(exc)


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(int(process_group_id), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_process_group(process_group_id: int, signal_number: int) -> None:
    try:
        os.killpg(int(process_group_id), int(signal_number))
    except ProcessLookupError:
        return


def _wait_for_process_group_exit(process_group_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        if not _process_group_exists(process_group_id):
            return True
        time.sleep(0.05)
    return not _process_group_exists(process_group_id)


@dataclass(frozen=True)
class InspectorRuntimeConfig:
    repo_root: Path
    python: Path
    kit_root: Path
    ovstage_root: Path
    ovrtx_root: Path
    rendering_build: Path
    ovui_python_root: Path

    @classmethod
    def from_environment(cls, repo_root: Path) -> "InspectorRuntimeConfig":
        missing: list[str] = []

        def required_path(name: str, fallback: Path | None = None) -> Path:
            raw = os.environ.get(name, "").strip()
            path = Path(raw).expanduser() if raw else fallback
            if path is None or not path.exists():
                missing.append(name)
                return Path("/")
            return path.resolve()

        kit_root = required_path("KIT_ROOT")
        # Preserve a virtual-environment interpreter symlink. Resolving
        # ``venv/bin/python`` to the host executable drops the venv prefix and
        # its installed numpy/ovui packages when the subprocess starts.
        python_raw = os.environ.get("OVUI_INSPECTOR_APP_PYTHON", "").strip()
        python = Path(python_raw).expanduser() if python_raw else Path(os.sys.executable)
        if not python.exists():
            missing.append("OVUI_INSPECTOR_APP_PYTHON")
        ovstage_root = required_path(
            "OVSTAGE_ROOT",
            kit_root / "rendering" / "ovstage",
        )
        ovrtx_root = required_path(
            "OVRTX_ROOT",
            kit_root / "rendering" / "ovrtx",
        )
        rendering_build = required_path(
            "OVSTAGE_BUILD_DIR",
            kit_root / "rendering" / "_build" / "linux-x86_64" / "release",
        )
        ovui_python_root = required_path(
            "OVUI_PYTHON_ROOT",
            repo_root / "ovui" / "python",
        )
        if missing:
            names = ", ".join(sorted(set(missing)))
            raise RuntimeError(
                f"Inspector QA runtime is incomplete; set or build: {names}"
            )
        return cls(
            repo_root=repo_root.resolve(),
            python=python,
            kit_root=kit_root,
            ovstage_root=ovstage_root,
            ovrtx_root=ovrtx_root,
            rendering_build=rendering_build,
            ovui_python_root=ovui_python_root,
        )

    def process_environment(self, *, port: int, workspace: Path) -> dict[str, str]:
        env = dict(os.environ)
        python_roots = [
            self.ovstage_root / "public" / "python",
            self.ovrtx_root / "public" / "python",
            self.repo_root / "skills" / "omniverse-ui-inspector",
            self.repo_root / "ovui-data-adapters",
            self.repo_root / "ovui-widgets",
            self.ovui_python_root,
        ]
        library_roots = [
            self.rendering_build,
            self.rendering_build / "plugins",
            self.rendering_build / "plugins" / "usdrt",
            self.rendering_build / "plugins" / "rtx",
        ]
        env.update(
            {
                "KIT_ROOT": str(self.kit_root),
                "OVSTAGE_ROOT": str(self.ovstage_root),
                "OVRTX_ROOT": str(self.ovrtx_root),
                "OVSTAGE_BUILD_DIR": str(self.rendering_build),
                "OVSTAGE_LIBRARY_PATH_HINT": str(self.rendering_build),
                "OVRTX_BIN_DIR": str(self.rendering_build),
                "OVRTX_LIBRARY_PATH_HINT": str(self.rendering_build),
                "OVUI_DATA_ADAPTER_PROVIDER": "ovstage",
                "OVUI_WIDGETS_REQUIRE_OVRTX": "1",
                "OVRTX_SKIP_USD_CHECK": "1",
                "OVUIINSPECT_ENABLED": "1",
                "OVUIINSPECT_ENABLE_STATE": "1",
                "OVUIINSPECT_ENABLE_EXECUTE": "0",
                "OVUIINSPECT_HOST": "127.0.0.1",
                "OVUIINSPECT_PORT": str(port),
                "PYTHONFAULTHANDLER": "1",
                "OVGEAR_HEADLESS_WIDTH": "1280",
                "OVGEAR_HEADLESS_HEIGHT": "720",
                "HOME": str(workspace / "home"),
                "XDG_CONFIG_HOME": str(workspace / "config"),
                "PYTHONPATH": _prepend_paths(
                    python_roots,
                    env.get("PYTHONPATH", ""),
                ),
                "LD_LIBRARY_PATH": _prepend_paths(
                    library_roots,
                    env.get("LD_LIBRARY_PATH", ""),
                ),
            }
        )
        return env


class InspectorClient:
    def __init__(self, port: int) -> None:
        self.base_url = f"http://127.0.0.1:{int(port)}"

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> tuple[bytes, str] | dict[str, Any]:
        query = urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(url, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                payload = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"Inspector GET {path} failed: {_request_error_detail(exc)}"
            ) from exc
        if content_type.startswith("image/"):
            return payload, content_type
        return json.loads(payload)

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"Inspector POST {path} failed: {_request_error_detail(exc)}"
            ) from exc

    def health(self) -> dict[str, Any]:
        result = self._get("/health", timeout=5.0)
        assert isinstance(result, dict)
        return result

    def state(self, *, timeout: float = 60.0) -> dict[str, Any]:
        result = self._get("/state", {"timeout": timeout}, timeout=timeout + 5.0)
        assert isinstance(result, dict)
        if not result.get("success"):
            raise RuntimeError(f"Inspector state failed: {result}")
        state = result.get("state")
        if not isinstance(state, dict):
            raise RuntimeError(f"Inspector returned invalid state: {result}")
        return state

    def screenshot(self, path: Path, *, timeout: float = 60.0) -> None:
        result = self._get(
            "/capture/application.png",
            {"timeout": timeout},
            timeout=timeout + 5.0,
        )
        if not isinstance(result, tuple):
            raise RuntimeError(f"Inspector returned no image: {result}")
        payload, content_type = result
        if content_type != "image/png" or not payload.startswith(b"\x89PNG"):
            raise RuntimeError(f"Inspector returned invalid PNG ({content_type})")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def checkpoint(self, path: Path, *, timeout: float = 60.0) -> dict[str, Any]:
        """Atomically register one screenshot beside one read-only app state."""

        query = urlencode({"timeout": timeout, "fmt": "png"})
        result = self._post(
            f"/checkpoint?{query}",
            {},
            timeout=timeout + 5.0,
        )
        if result.get("success") is not True:
            raise RuntimeError(f"Inspector checkpoint failed: {result}")
        state = result.get("state")
        screenshot = result.get("screenshot")
        if not isinstance(state, dict) or not isinstance(screenshot, dict):
            raise RuntimeError(f"Inspector returned invalid checkpoint: {result}")
        try:
            payload = base64.b64decode(
                str(screenshot["image_base64"]),
                validate=True,
            )
        except Exception as exc:
            raise RuntimeError("Inspector checkpoint returned invalid base64") from exc
        if screenshot.get("mime_type") != "image/png" or not payload.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            raise RuntimeError("Inspector checkpoint returned an invalid PNG")
        if int(screenshot.get("bytes", 0) or 0) != len(payload) or not payload:
            raise RuntimeError("Inspector checkpoint byte count does not match image")
        request = screenshot.get("request")
        terminal = screenshot.get("result")
        if not isinstance(request, dict) or not isinstance(terminal, dict):
            raise RuntimeError("Inspector checkpoint omitted request metadata")
        if request.get("request_id") != terminal.get("request_id"):
            raise RuntimeError("Inspector checkpoint request identity changed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {
            "state": state,
            "screenshot_request": request,
            "screenshot_result": terminal,
        }

    def click(
        self,
        x: int,
        y: int,
        *,
        button: str = "left",
        modifiers: list[str] | None = None,
        double: bool = False,
        timeout: float = _REAL_INPUT_TIMEOUT,
    ) -> dict[str, Any]:
        return self._post(
            "/mouse/click",
            {
                "x": int(x),
                "y": int(y),
                "button": str(button),
                "modifiers": modifiers,
                "double": bool(double),
                "timeout": timeout,
            },
            timeout=timeout + 5.0,
        )

    def move(
        self,
        x: int,
        y: int,
        *,
        timeout: float = _REAL_INPUT_TIMEOUT,
    ) -> dict[str, Any]:
        return self._post(
            "/mouse/move",
            {"x": int(x), "y": int(y), "timeout": timeout},
            timeout=timeout + 5.0,
        )

    def scroll(
        self,
        direction: str,
        *,
        amount: float = 3.0,
        x: int | None = None,
        y: int | None = None,
        timeout: float = _REAL_INPUT_TIMEOUT,
    ) -> dict[str, Any]:
        return self._post(
            "/mouse/scroll",
            {
                "direction": str(direction),
                "amount": float(amount),
                "x": None if x is None else int(x),
                "y": None if y is None else int(y),
                "timeout": timeout,
            },
            timeout=timeout + 5.0,
        )

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        steps: int = 12,
        modifiers: list[str] | None = None,
        timeout: float = _REAL_INPUT_TIMEOUT,
    ) -> dict[str, Any]:
        return self._post(
            "/mouse/drag",
            {
                "start_x": int(start_x),
                "start_y": int(start_y),
                "end_x": int(end_x),
                "end_y": int(end_y),
                "button": "left",
                "steps": int(steps),
                "modifiers": modifiers,
                "timeout": timeout,
            },
            timeout=timeout + 5.0,
        )

    def press(
        self,
        key: str,
        *,
        modifiers: list[str] | None = None,
        timeout: float = _REAL_INPUT_TIMEOUT,
    ) -> dict[str, Any]:
        return self._post(
            "/keyboard/press",
            {"key": key, "modifiers": modifiers, "timeout": timeout},
            timeout=timeout + 5.0,
        )

    def type_text(
        self,
        text: str,
        *,
        timeout: float = _REAL_INPUT_TIMEOUT,
    ) -> dict[str, Any]:
        return self._post(
            "/keyboard/type",
            {"text": text, "timeout": timeout},
            timeout=timeout + 5.0,
        )

    def shutdown(self) -> None:
        self._post("/shutdown", {}, timeout=10.0)


class InspectorAppProcess:
    def __init__(
        self,
        config: InspectorRuntimeConfig,
        workspace: Path,
        *,
        scene: Path | None,
    ) -> None:
        self.config = config
        self.workspace = workspace
        self.scene = scene
        self.port = _free_local_port()
        self.client = InspectorClient(self.port)
        self.process: subprocess.Popen | None = None
        self._process_group_id: int | None = None
        self._closed = False
        self._log_handle = None
        self.log_path = workspace / "app.log"

    def start(self) -> "InspectorAppProcess":
        if self.process is not None:
            raise RuntimeError("Inspector application process is already started")
        if self._closed:
            raise RuntimeError("Inspector application process is already closed")
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "home").mkdir(exist_ok=True)
        (self.workspace / "config").mkdir(exist_ok=True)
        command = [
            "xvfb-run",
            "-a",
            "-s",
            "-screen 0 1280x720x24",
            str(self.config.python),
            "-m",
            "ovui_widgets.app",
        ]
        if self.scene is not None:
            command.append(str(self.scene))
        self._log_handle = self.log_path.open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen(
                command,
                cwd=self.workspace,
                env=self.config.process_environment(
                    port=self.port,
                    workspace=self.workspace,
                ),
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            self._process_group_id = int(self.process.pid)
            deadline = time.monotonic() + 300.0
            last_error = "Inspector did not answer"
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        f"OVStage viewer exited with {self.process.returncode}:\n"
                        f"{self.log_text()}"
                    )
                try:
                    health = self.client.health()
                    if health.get("app_attached"):
                        return self
                except RuntimeError as exc:
                    last_error = str(exc)
                time.sleep(0.25)
            raise RuntimeError(f"{last_error}:\n{self.log_text()}")
        except BaseException:
            self.close()
            raise

    def wait_for_scene(
        self,
        *,
        timeout: float = 300.0,
        require_prim_screen_centers: bool = False,
    ) -> dict[str, Any]:
        """Wait until the scene/renderer readiness criteria pass.

        ``require_prim_screen_centers`` is for workflows that aim input at
        state-discovered prim screen centers: those come from native bounds
        queries that can commit after the first rendered frame, so such
        workflows must opt in. Empty, headless, or otherwise nonprojectable
        scenes stay ready under the default criteria.
        """
        deadline = time.monotonic() + timeout
        last_error = "scene state was unavailable"
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"OVStage viewer exited with {self.process.returncode}:\n{self.log_text()}"
                )
            try:
                state = self.client.state(timeout=min(60.0, timeout))
            except RuntimeError as exc:
                last_error = str(exc)
                time.sleep(0.25)
                continue
            renderer = state.get("renderer", {})
            components = state.get("components", {})
            loaded_components = set(components.get("loaded_names", ()))
            required_components = {
                "ovstage_physics_controls",
            }
            core_scene_ready = bool(
                state.get("ovstage", {}).get("available")
                and state.get("adapter", {}).get("available")
                and renderer.get("available")
                and int(renderer.get("successful_frame_count", 0)) > 0
            )
            centers = state.get("viewport", {}).get("prim_screen_centers") or {}
            centers_pending = require_prim_screen_centers and not centers
            missing_components = sorted(required_components - loaded_components)
            component_failures = components.get("failures", {})
            if core_scene_ready and (missing_components or component_failures):
                raise RuntimeError(
                    "Inspector native runtime is missing installed component "
                    "entry points. Install ovui-data-adapters/dist/ovstage "
                    "in the application "
                    f"interpreter. missing={missing_components}, "
                    f"failures={component_failures}\n{self.log_text()}"
                )
            if core_scene_ready and not centers_pending:
                return state
            if core_scene_ready and centers_pending:
                viewport = state.get("viewport", {})
                last_error = (
                    "scene is ready but no prim screen centers have been "
                    "projected yet (required by this workflow for "
                    "state-guided viewport input): "
                    f"viewport_available={viewport.get('available')}, "
                    f"projection_paths_truncated="
                    f"{viewport.get('projection_paths_truncated')}, "
                    f"native_paths={len(state.get('ovstage', {}).get('paths', ()))}"
                )
            else:
                last_error = (
                    "scene has not rendered with the full native component set: "
                    f"missing_components={missing_components}, "
                    f"component_failures={component_failures}, "
                    f"state={state}"
                )
            time.sleep(0.25)
        raise RuntimeError(f"{last_error}:\n{self.log_text()}")

    def log_text(self) -> str:
        if self._log_handle is not None:
            self._log_handle.flush()
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self.process
        process_group_id = self._process_group_id
        # Relinquish the signal-capable group ID before cleanup. A repeated
        # close can inspect the retained Popen return code but can never signal
        # a later process that happens to reuse this numeric PID/PGID.
        self._process_group_id = None
        try:
            if process is not None:
                if process.poll() is None:
                    try:
                        self.client.shutdown()
                    except Exception:
                        pass
                try:
                    process.wait(timeout=30.0)
                except subprocess.TimeoutExpired:
                    if process_group_id is not None:
                        _signal_process_group(process_group_id, signal.SIGTERM)
                    try:
                        process.wait(timeout=10.0)
                    except subprocess.TimeoutExpired:
                        if process_group_id is not None:
                            _signal_process_group(process_group_id, signal.SIGKILL)
                        try:
                            process.wait(timeout=10.0)
                        except subprocess.TimeoutExpired:
                            pass

            # ``xvfb-run`` is a shell wrapper. If it exits before reaping the
            # viewer/Xvfb children, Popen alone no longer owns those processes.
            # The dedicated session keeps the group addressable for deterministic
            # cleanup without touching any unrelated test process.
            if (
                process_group_id is not None
                and _process_group_exists(process_group_id)
            ):
                _signal_process_group(process_group_id, signal.SIGTERM)
                if not _wait_for_process_group_exit(process_group_id, 5.0):
                    _signal_process_group(process_group_id, signal.SIGKILL)
                    _wait_for_process_group_exit(process_group_id, 5.0)
        finally:
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    def __enter__(self) -> "InspectorAppProcess":
        return self.start()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


@dataclass(frozen=True)
class FeatureEvidenceContract:
    """Evidence tokens one Inspector scenario promises for one feature."""

    feature_id: str
    required_tokens: frozenset[str]


@dataclass(frozen=True)
class ScenarioEvidenceContract:
    """Source-level declaration consumed by the matrix gate and runtime manifest."""

    scenario_id: str
    features: tuple[FeatureEvidenceContract, ...]

    @classmethod
    def declare(
        cls,
        scenario_id: str,
        features: Mapping[str, Iterable[str]],
    ) -> "ScenarioEvidenceContract":
        assert isinstance(scenario_id, str) and scenario_id.strip() == scenario_id
        assert scenario_id, "scenario_id must be non-empty"
        assert features, f"{scenario_id}: at least one feature is required"
        contracts: list[FeatureEvidenceContract] = []
        for feature_id, raw_tokens in features.items():
            assert isinstance(feature_id, str) and feature_id.strip() == feature_id
            assert feature_id, f"{scenario_id}: feature ID must be non-empty"
            assert not isinstance(raw_tokens, str), (
                f"{scenario_id}: {feature_id} evidence tokens must be an iterable of names"
            )
            tokens = tuple(raw_tokens)
            assert tokens, f"{scenario_id}: {feature_id} has no evidence tokens"
            assert all(
                isinstance(token, str) and token and token.strip() == token
                for token in tokens
            ), f"{scenario_id}: {feature_id} has an invalid evidence token"
            assert len(tokens) == len(set(tokens)), (
                f"{scenario_id}: {feature_id} has duplicate evidence tokens"
            )
            contracts.append(
                FeatureEvidenceContract(
                    feature_id=feature_id,
                    required_tokens=frozenset(tokens),
                )
            )
        feature_ids = [contract.feature_id for contract in contracts]
        assert len(feature_ids) == len(set(feature_ids)), (
            f"{scenario_id}: duplicate feature declarations"
        )
        return cls(
            scenario_id=scenario_id,
            features=tuple(sorted(contracts, key=lambda contract: contract.feature_id)),
        )

    @property
    def feature_ids(self) -> frozenset[str]:
        return frozenset(contract.feature_id for contract in self.features)

    def tokens_for(self, feature_id: str) -> frozenset[str]:
        for contract in self.features:
            if contract.feature_id == feature_id:
                return contract.required_tokens
        raise AssertionError(
            f"{self.scenario_id}: feature {feature_id!r} is not declared"
        )

    def as_manifest(self) -> dict[str, Any]:
        return {
            "id": self.scenario_id,
            "features": [
                {
                    "id": contract.feature_id,
                    "required_evidence": sorted(contract.required_tokens),
                }
                for contract in self.features
            ],
        }


class EvidenceRecorder:
    def __init__(
        self,
        client: InspectorClient,
        root: Path,
        *,
        scenario: ScenarioEvidenceContract | None = None,
    ) -> None:
        self.client = client
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.scenario = scenario
        self._sequence = 0
        self._actions: list[dict[str, Any]] = []
        self._checks: list[dict[str, Any]] = []
        self._write_manifest()

    @property
    def action_count(self) -> int:
        return len(self._actions)

    def _summary(self) -> dict[str, Any]:
        if self.scenario is None:
            return {
                "action_count": self.action_count,
                "contract_declared": False,
                "complete": None,
                "passed": None,
                "missing_evidence": [],
                "failed_evidence": [],
            }

        missing: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        for feature in self.scenario.features:
            for token in sorted(feature.required_tokens):
                matching = [
                    check
                    for check in self._checks
                    if check["feature_id"] == feature.feature_id
                    and check["token"] == token
                ]
                if not matching:
                    missing.append({"feature_id": feature.feature_id, "token": token})
                elif not all(check["passed"] for check in matching):
                    failed.append({"feature_id": feature.feature_id, "token": token})
        complete = self.action_count > 0 and not missing and not failed
        return {
            "action_count": self.action_count,
            "contract_declared": True,
            "complete": complete,
            "passed": complete,
            "missing_action": self.action_count == 0,
            "missing_evidence": missing,
            "failed_evidence": failed,
        }

    def _manifest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "interaction_mode": "state_guided",
            "scenario": None if self.scenario is None else self.scenario.as_manifest(),
            "actions": self._actions,
            "evidence_checks": self._checks,
            "summary": self._summary(),
        }

    def _write_manifest(self) -> None:
        (self.root / "manifest.json").write_text(
            json.dumps(self._manifest_payload(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def check(
        self,
        feature_id: str,
        token: str,
        passed: bool,
        *,
        detail: str = "",
    ) -> None:
        """Record one explicit evidence result for a declared feature token."""

        assert self.scenario is not None, "evidence checks require a scenario contract"
        assert feature_id in self.scenario.feature_ids, (
            f"{self.scenario.scenario_id}: undeclared feature {feature_id!r}"
        )
        assert token in self.scenario.tokens_for(feature_id), (
            f"{self.scenario.scenario_id}: undeclared evidence token "
            f"{feature_id}:{token}"
        )
        assert isinstance(passed, bool), f"{feature_id}:{token}: passed must be bool"
        assert isinstance(detail, str), f"{feature_id}:{token}: detail must be text"
        self._checks.append(
            {
                "feature_id": feature_id,
                "token": token,
                "passed": passed,
                "detail": detail,
                "after_action": self.action_count,
            }
        )
        self._write_manifest()
        if not passed:
            raise AssertionError(
                f"Evidence check failed for {feature_id}:{token}"
                + (f": {detail}" if detail else "")
            )

    def finalize(self) -> dict[str, Any]:
        """Persist and enforce action plus evidence-token completion."""

        payload = self._manifest_payload()
        self._write_manifest()
        if self.scenario is None:
            return payload
        summary = payload["summary"]
        problems: list[str] = []
        if summary["missing_action"]:
            problems.append("no EvidenceRecorder.action was completed")
        if summary["missing_evidence"]:
            missing = ", ".join(
                f"{item['feature_id']}:{item['token']}"
                for item in summary["missing_evidence"]
            )
            problems.append(f"missing evidence results: {missing}")
        if summary["failed_evidence"]:
            failed = ", ".join(
                f"{item['feature_id']}:{item['token']}"
                for item in summary["failed_evidence"]
            )
            problems.append(f"failed evidence results: {failed}")
        if problems:
            raise AssertionError(
                f"Evidence scenario {self.scenario.scenario_id!r} is incomplete: "
                + "; ".join(problems)
            )
        return payload

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _screenshot_stats(
        path: Path,
        rect: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import numpy as np
        from PIL import Image, ImageStat

        with Image.open(path) as image:
            rgb = image.convert("RGB")
            if rect:
                left = max(0, int(round(float(rect.get("x", 0.0)))))
                top = max(0, int(round(float(rect.get("y", 0.0)))))
                right = min(
                    rgb.width,
                    left + max(0, int(round(float(rect.get("width", 0.0))))),
                )
                bottom = min(
                    rgb.height,
                    top + max(0, int(round(float(rect.get("height", 0.0))))),
                )
                if right > left and bottom > top:
                    rgb = rgb.crop((left, top, right, bottom))
            extrema = ImageStat.Stat(rgb).extrema
            ranges = [int(high) - int(low) for low, high in extrema]
            pixels = np.asarray(rgb, dtype=np.uint8)
            nonblack = int(np.count_nonzero(np.any(pixels != 0, axis=-1)))
            luma = (
                pixels[..., 0].astype(np.float32) * 0.2126
                + pixels[..., 1].astype(np.float32) * 0.7152
                + pixels[..., 2].astype(np.float32) * 0.0722
            )
            return {
                "width": rgb.width,
                "height": rgb.height,
                "channel_extrema": [[int(low), int(high)] for low, high in extrema],
                "max_channel_range": max(ranges, default=0),
                "nonblack_pixels": nonblack,
                "pixel_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                "luma_mean": float(luma.mean()) if luma.size else 0.0,
                "luma_std": float(luma.std()) if luma.size else 0.0,
            }

    def checkpoint(self, label: str) -> dict[str, Any]:
        self._sequence += 1
        stem = f"{self._sequence:03d}-{label}"
        immediate_screenshot_path = self.root / f"{stem}.png"
        state_path = self.root / f"{stem}.json"
        immediate_capture = self.client.checkpoint(immediate_screenshot_path)
        immediate_state = immediate_capture["state"]
        state, settle_frames = self._settled_state(immediate_state)
        screenshot_path = immediate_screenshot_path
        capture = immediate_capture
        if settle_frames:
            # Preserve the immediate evidence. A second unique checkpoint is
            # allowed only after read-only state polling proves that deferred
            # model/population work settled.
            immediate_state_path = self.root / f"{stem}-immediate.json"
            immediate_state_path.write_text(
                json.dumps(immediate_state, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            screenshot_path = self.root / f"{stem}-settled.png"
            capture = self.client.checkpoint(screenshot_path)
            state = capture["state"]
        viewport_stats = self._screenshot_stats(
            screenshot_path,
            state.get("viewport", {}).get("image_rect"),
        )
        screenshot_stats = self._screenshot_stats(screenshot_path)
        assert screenshot_stats["width"] > 0 and screenshot_stats["height"] > 0
        assert screenshot_stats["nonblack_pixels"] > 0, screenshot_stats
        assert screenshot_stats["max_channel_range"] > 0, screenshot_stats
        native_scene_verified = bool(
            state.get("ovstage", {}).get("available")
            and state.get("adapter", {}).get("available")
        )
        if native_scene_verified:
            assert_native_scene_state(state)
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "label": label,
            "screenshot": str(screenshot_path),
            "screenshot_sha256": self._sha256(screenshot_path),
            "screenshot_stats": screenshot_stats,
            "viewport_stats": viewport_stats,
            "state_path": str(state_path),
            "state": state,
            "settle_frames": settle_frames,
            "native_scene_verified": native_scene_verified,
            "immediate_screenshot": str(immediate_screenshot_path),
            "immediate_screenshot_sha256": self._sha256(
                immediate_screenshot_path
            ),
            "screenshot_request": capture["screenshot_request"],
            "screenshot_result": capture["screenshot_result"],
            "immediate_screenshot_request": immediate_capture[
                "screenshot_request"
            ],
            "immediate_screenshot_result": immediate_capture[
                "screenshot_result"
            ],
        }

    def _settled_state(self, state: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Wait out transient model-present/UI-rebuild gaps using read-only frames."""

        def property_geometry_pending(value: dict[str, Any]) -> bool:
            property_ui = value.get("property_ui", {})
            if (
                property_ui.get("available") is not True
                or not property_ui.get("filter_text")
            ):
                return False
            rows = property_ui.get("rows", {})
            field_rects = [
                rect
                for row in rows.values()
                for rect in row.get("field_rects", ())
                if isinstance(rect, dict)
            ]
            if not field_rects:
                return bool(rows)
            return not any(
                float(rect.get("width", 0.0) or 0.0) > 0.0
                and float(rect.get("height", 0.0) or 0.0) > 0.0
                for rect in field_rects
            )

        def camera_menu_geometry_pending(value: dict[str, Any]) -> bool:
            camera_menu = value.get("viewport", {}).get("camera_menu", {})
            items = camera_menu.get("items", ())
            return bool(
                camera_menu.get("shown")
                and items
                and not any(item.get("point") is not None for item in items)
            )

        settled_frames = 0
        layers_ui = state.get("layers_ui", {})
        while settled_frames < 24 and (
            (
                state.get("layers", {}).get("available") is True
                and layers_ui.get("available") is False
            )
            or (
                state.get("adapter", {}).get("available") is True
                and state.get("ovstage", {}).get("available") is not True
            )
            or property_geometry_pending(state)
            or camera_menu_geometry_pending(state)
        ):
            state = self.client.state(timeout=60.0)
            settled_frames += 1
            layers_ui = state.get("layers_ui", {})
        return state, settled_frames

    def action(
        self,
        label: str,
        perform: Callable[[], dict[str, Any]],
        *,
        evidence_tokens: Mapping[str, Iterable[str]] | None = None,
    ) -> dict[str, Any]:
        before = self.checkpoint(f"{label}-before")
        result = perform()
        if not result.get("success"):
            raise AssertionError(f"Inspector action {label!r} failed: {result}")
        after = self.checkpoint(f"{label}-after")
        record = {
            "label": label,
            "before": {key: value for key, value in before.items() if key != "state"},
            "after": {key: value for key, value in after.items() if key != "state"},
            "screenshot_changed": (
                before["screenshot_sha256"] != after["screenshot_sha256"]
            ),
            "result": result,
        }
        self._actions.append(record)
        for feature_id, tokens in (evidence_tokens or {}).items():
            for token in tokens:
                self.check(
                    feature_id,
                    token,
                    True,
                    detail=f"Inspector action {label!r} completed successfully",
                )
        self._write_manifest()
        return {"before": before, "after": after, "record": record}


def assert_native_scene_state(state: dict[str, Any]) -> None:
    """Native-only scene consistency for the exact no-pxr OVStage runtime.

    Every observation comes from the public native OVStage snapshot and the
    adapter/UI views built on it; there is no backing-USD stage, bridge
    identity, or USD/native parity to compare against.
    """

    ovstage = state.get("ovstage", {})
    assert ovstage.get("available") is True, ovstage
    assert not ovstage.get("error"), ovstage
    native_paths = set(ovstage.get("paths", ()))
    assert native_paths, ovstage

    adapter = state.get("adapter", {})
    assert adapter.get("available") is True, adapter
    adapter_paths = set(adapter.get("paths", ()))
    # The adapter view must contain every committed native user-scene path;
    # its only additions are synthesized hierarchy ancestors of native paths.
    # User-facing versus runtime-internal classification comes from the
    # provider's own ownership rule recorded per prim in the native snapshot
    # — the harness keeps no second path policy of its own.
    native_prims = ovstage.get("prims", {}) or {}
    user_native_paths = {
        str(path)
        for path, record in native_prims.items()
        if bool(record.get("user_facing"))
    }
    assert user_native_paths, {
        "no_provider_classified_user_paths": sorted(native_prims)[:8]
    }
    missing = user_native_paths - adapter_paths
    assert not missing, {"missing_from_adapter": sorted(missing)}
    for extra in adapter_paths - native_paths:
        assert any(
            native.startswith(extra + "/") for native in native_paths
        ), {"non_native_adapter_path": extra}

    selection = state.get("selection", {})
    selected = set(selection.get("paths", ()) or ())
    assert selected <= adapter_paths, {
        "selection_outside_adapter_view": sorted(selected - adapter_paths)
    }


def assert_real_borrow_renderer(state: dict[str, Any]) -> None:
    renderer = state.get("renderer", {})
    assert renderer.get("adapter_class") == "OvstageRendererAdapter", renderer
    assert renderer.get("is_borrow_mode") is True, renderer
    # A borrow claim must cite its live evidence: either a public config
    # field, or (current wheels, which expose none) the renderer-retained
    # borrowed-stage identity proven below.
    assert renderer.get("attach_mode_source") in {
        "config.attach_mode",
        "native_attach_ovstage",
    }, renderer
    assert renderer.get("attached_exact_ovstage") is True, renderer
    assert renderer.get("native_attached_exact_ovstage") is True, renderer
    assert int(renderer.get("borrow_step_count", 0)) > 0, renderer
    assert int(renderer.get("successful_frame_count", 0)) > 0, renderer
    assert int(renderer.get("selection_outline_attribute_writes", 0)) == 0, renderer
