# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Backend-neutral viewport chrome state adapter.

The viewport renderer owns streamed pixels. This adapter owns the non-pixel
viewport state a client UI needs for toolbar and HUD chrome. It intentionally
does not publish render-progress or path-tracing telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Tuple

from ovui_data_adapters.common.render_targets import RenderTargetCatalog
from ovui_data_adapters.common.render_vars import RenderVarOutputCatalog


TRANSFORM_TOOL_IDS: Tuple[str, ...] = ("move", "rotate", "scale")
CONTRACT_TOOL_TO_OVUI_TOOL = {
    "move": "translate",
    "rotate": "rotate",
    "scale": "scale",
}
OVUI_TOOL_TO_CONTRACT_TOOL = {
    "translate": "move",
    "move": "move",
    "rotate": "rotate",
    "scale": "scale",
}
TOOLBAR_REQUIRED_CONTROLS: Tuple[str, ...] = (
    "move",
    "rotate",
    "scale",
    "camera",
    "render_target",
    "rendervar",
    "path_tracing_progress",
)
_UNSET = object()


def _mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _tuple_or_empty(value: Iterable[str] | str | None) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _dict_tuple(value: Iterable[Mapping[str, Any]] | None) -> Tuple[Mapping[str, Any], ...]:
    return tuple(MappingProxyType(dict(item)) for item in (value or ()))


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    if isinstance(raw, str):
        return raw.lower()
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.lower()
    return str(raw or "").lower()


def _nonempty_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _label_for_path(path: str | None) -> str:
    if path is None:
        return "No camera"
    return path.rsplit("/", 1)[-1] or path


def _kind_label(kind: str) -> str:
    return kind.replace("_", " ").title()


def _target_ui_kind(target: Any) -> str:
    output_kind = _enum_value(getattr(target, "output_kind", None))
    if output_kind == "point_cloud":
        return "point_cloud"
    return _enum_value(getattr(target, "kind", None)) or "render_product"


def _warning_payloads(warnings: Any) -> Tuple[Mapping[str, Any], ...]:
    payloads: list[Mapping[str, Any]] = []
    for warning in warnings or ():
        code = _nonempty_string(getattr(warning, "code", None)) or "warning"
        message = _nonempty_string(getattr(warning, "message", None)) or "Adapter warning."
        severity = _enum_value(getattr(warning, "severity", None)) or "warning"
        payloads.append(MappingProxyType({"code": code, "message": message, "severity": severity}))
    return tuple(payloads)


def _normalize_stream_state(stream_state: Any, client_count: int) -> str:
    normalized = str(stream_state or "").upper()
    if normalized == "STREAMING" or (normalized == "LISTENING" and client_count > 0):
        return "STREAMING"
    if normalized in ("LISTENING", "READY"):
        return "LISTENING"
    if normalized in ("DISCONNECTED", "OFF", "CLOSED"):
        return "OFF"
    return "ERROR"


def _stream_label(
    state: str,
    client_count: int,
    signal_port: int,
    media_port: int,
    error: Any = None,
) -> str:
    if state == "STREAMING":
        return f"Streaming {client_count} client(s)"
    if state == "LISTENING":
        return f"Listening :{signal_port}/{media_port}"
    if state == "OFF":
        return "Off"
    message = str(error or "stream unavailable").strip()
    return f"Error: {message}"


def _coerce_resolution(value: Iterable[int] | Mapping[str, int] | None) -> Tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        width = int(value.get("width", 0) or 0)
        height = int(value.get("height", 0) or 0)
    else:
        items = tuple(value)
        if len(items) != 2:
            raise ValueError("resolution must contain width and height")
        width = int(items[0])
        height = int(items[1])
    if width <= 0 or height <= 0:
        return None
    return (width, height)


@dataclass(frozen=True)
class ViewportCameraState:
    path: str
    label: str
    source: str = "StageAdapter.list_cameras"
    is_active: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", str(self.path or ""))
        object.__setattr__(self, "label", str(self.label or _label_for_path(self.path)))
        object.__setattr__(self, "source", str(self.source or "StageAdapter.list_cameras"))
        object.__setattr__(self, "is_active", bool(self.is_active))

    def as_payload(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "path": self.path,
                "label": self.label,
                "source": self.source,
                "is_active": self.is_active,
            }
        )


@dataclass(frozen=True)
class ViewportStreamState:
    state: str = "OFF"
    label: str = "Off"
    client_count: int = 0
    protocol: str = "webrtc"
    signal_port: int = 0
    media_port: int = 0
    source: str = "ViewportStateAdapter"

    def __post_init__(self) -> None:
        client_count = max(0, int(self.client_count))
        signal_port = int(self.signal_port)
        media_port = int(self.media_port)
        state = _normalize_stream_state(self.state, client_count)
        label = str(self.label or _stream_label(state, client_count, signal_port, media_port))
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "client_count", client_count)
        object.__setattr__(self, "protocol", str(self.protocol or "webrtc"))
        object.__setattr__(self, "signal_port", signal_port)
        object.__setattr__(self, "media_port", media_port)
        object.__setattr__(self, "source", str(self.source or "ViewportStateAdapter"))

    def as_payload(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "state": self.state,
                "label": self.label,
                "client_count": self.client_count,
                "protocol": self.protocol,
                "signal_port": self.signal_port,
                "media_port": self.media_port,
                "source": self.source,
            }
        )


@dataclass(frozen=True)
class ViewportStateSnapshot:
    revision: int = 1
    active_tool: str = "move"
    ovui_tool: str = "translate"
    available_tools: Tuple[str, ...] = TRANSFORM_TOOL_IDS
    tool_registry_available: bool = False
    cameras: Tuple[ViewportCameraState, ...] = field(default_factory=tuple)
    active_camera_path: str | None = None
    active_camera_label: str = "No camera"
    render_target_catalog: RenderTargetCatalog = field(default_factory=RenderTargetCatalog)
    render_target_groups: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    active_target_id: str | None = None
    active_kind: str | None = None
    active_target_label: str = "None"
    active_target_capability: str = "none"
    active_render_product_path: str | None = None
    render_var_catalog: RenderVarOutputCatalog = field(default_factory=RenderVarOutputCatalog)
    render_var_items: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    active_render_var_output_id: str | None = None
    render_var_render_product_path: str | None = None
    supports_render_var_clear: bool = False
    scene_label: str | None = None
    fps: float | None = None
    resolution: Tuple[int, int] | None = None
    stream: ViewportStreamState | None = None
    toolbar_availability: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    viewport_ui_state: Mapping[str, Any] = field(default_factory=dict)
    capability_state: Mapping[str, Any] = field(default_factory=dict)
    stage_identifier: str = ""
    backend_owned: bool = True
    render_progress_present: bool = False
    path_tracing_present: bool = False

    def __post_init__(self) -> None:
        revision = max(1, int(self.revision))
        active_tool = str(self.active_tool or "move").lower()
        if active_tool not in TRANSFORM_TOOL_IDS:
            active_tool = "move"
        ovui_tool = str(self.ovui_tool or CONTRACT_TOOL_TO_OVUI_TOOL[active_tool])
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "active_tool", active_tool)
        object.__setattr__(self, "ovui_tool", ovui_tool)
        object.__setattr__(self, "available_tools", _tuple_or_empty(self.available_tools) or TRANSFORM_TOOL_IDS)
        object.__setattr__(self, "tool_registry_available", bool(self.tool_registry_available))
        object.__setattr__(self, "cameras", tuple(self.cameras))
        object.__setattr__(self, "active_camera_label", str(self.active_camera_label or _label_for_path(self.active_camera_path)))
        object.__setattr__(self, "render_target_groups", _dict_tuple(self.render_target_groups))
        object.__setattr__(self, "active_target_label", str(self.active_target_label or "None"))
        object.__setattr__(self, "active_target_capability", str(self.active_target_capability or "none"))
        object.__setattr__(self, "render_var_items", _dict_tuple(self.render_var_items))
        object.__setattr__(self, "supports_render_var_clear", bool(self.supports_render_var_clear))
        if self.fps is not None:
            fps = float(self.fps)
            object.__setattr__(self, "fps", fps if fps >= 0 else None)
        object.__setattr__(self, "resolution", _coerce_resolution(self.resolution))
        object.__setattr__(self, "toolbar_availability", _freeze_nested_mapping(self.toolbar_availability))
        object.__setattr__(self, "viewport_ui_state", _mapping_proxy(self.viewport_ui_state))
        object.__setattr__(self, "capability_state", _mapping_proxy(self.capability_state))
        object.__setattr__(self, "stage_identifier", str(self.stage_identifier or ""))
        object.__setattr__(self, "backend_owned", bool(self.backend_owned))
        object.__setattr__(self, "render_progress_present", False)
        object.__setattr__(self, "path_tracing_present", False)


def _freeze_nested_mapping(value: Mapping[str, Mapping[str, Any]] | None) -> Mapping[str, Mapping[str, Any]]:
    frozen: dict[str, Mapping[str, Any]] = {}
    for key, child in (value or {}).items():
        frozen[str(key)] = MappingProxyType(dict(child))
    return MappingProxyType(frozen)


class _ViewportStateSubscription:
    def __init__(
        self,
        callbacks: list[Callable[[ViewportStateSnapshot], None]],
        callback: Callable[[ViewportStateSnapshot], None],
    ) -> None:
        self._callbacks = callbacks
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        try:
            self._callbacks.remove(self._callback)
        except ValueError:
            pass


class ViewportStateAdapter:
    """Adapter-owned state source for React viewport toolbar/HUD chrome."""

    def __init__(
        self,
        *,
        stage_adapter: Any | None = None,
        renderer_adapter: Any | None = None,
        render_settings_adapter: Any | None = None,
        selection_bus: Any | None = None,
        tool_registry_available: bool = False,
        active_tool: str = "move",
        available_tools: Iterable[str] = TRANSFORM_TOOL_IDS,
        viewport: Any | None = None,
    ) -> None:
        self.stage_adapter = stage_adapter
        self.renderer_adapter = renderer_adapter
        self.render_settings_adapter = render_settings_adapter
        self.selection_bus = selection_bus
        self.viewport = viewport
        self._callbacks: list[Callable[[ViewportStateSnapshot], None]] = []
        self._revision = 0
        self._active_tool = self._normalize_contract_tool(active_tool)
        self._available_tools = _tuple_or_empty(available_tools) or TRANSFORM_TOOL_IDS
        self._tool_registry_available = bool(tool_registry_available)
        self._snapshot = ViewportStateSnapshot(
            revision=1,
            active_tool=self._active_tool,
            ovui_tool=CONTRACT_TOOL_TO_OVUI_TOOL[self._active_tool],
            available_tools=self._available_tools,
            tool_registry_available=self._tool_registry_available,
            toolbar_availability=self._toolbar_availability((), (), ()),
            stream=ViewportStreamState(),
        )

    def snapshot(self) -> ViewportStateSnapshot:
        return self._snapshot

    def subscribe_viewport_state_changes(
        self,
        callback: Callable[[ViewportStateSnapshot], None],
    ) -> _ViewportStateSubscription:
        self._callbacks.append(callback)
        return _ViewportStateSubscription(self._callbacks, callback)

    def set_active_tool(
        self,
        tool: str,
        *,
        tool_registry_available: bool | None = None,
        notify: bool = True,
    ) -> ViewportStateSnapshot:
        active_tool = self._normalize_contract_tool(tool)
        if tool_registry_available is not None:
            self._tool_registry_available = bool(tool_registry_available)
        self._active_tool = active_tool
        return self.update(
            active_tool=active_tool,
            ovui_tool=CONTRACT_TOOL_TO_OVUI_TOOL[active_tool],
            available_tools=self._available_tools,
            tool_registry_available=self._tool_registry_available,
            notify=notify,
        )

    def update_stream(
        self,
        *,
        stream_state: str,
        client_count: int = 0,
        protocol: str = "webrtc",
        signal_port: int = 0,
        media_port: int = 0,
        source: str = "ViewportStateAdapter",
        error: Any = None,
        notify: bool = True,
    ) -> ViewportStateSnapshot:
        normalized = _normalize_stream_state(stream_state, int(client_count or 0))
        stream = ViewportStreamState(
            state=normalized,
            label=_stream_label(normalized, int(client_count or 0), signal_port, media_port, error),
            client_count=int(client_count or 0),
            protocol=protocol,
            signal_port=signal_port,
            media_port=media_port,
            source=source,
        )
        return self.update(stream=stream, notify=notify)

    def update(
        self,
        *,
        active_tool: str | None = None,
        ovui_tool: str | None = None,
        available_tools: Iterable[str] | None = None,
        tool_registry_available: bool | None = None,
        cameras: Iterable[ViewportCameraState] | None = None,
        active_camera_path: Any = _UNSET,
        active_camera_label: Any = _UNSET,
        render_target_catalog: RenderTargetCatalog | None = None,
        render_target_groups: Iterable[Mapping[str, Any]] | None = None,
        active_target_id: Any = _UNSET,
        active_kind: Any = _UNSET,
        active_target_label: Any = _UNSET,
        active_target_capability: Any = _UNSET,
        active_render_product_path: Any = _UNSET,
        render_var_catalog: RenderVarOutputCatalog | None = None,
        render_var_items: Iterable[Mapping[str, Any]] | None = None,
        active_render_var_output_id: Any = _UNSET,
        render_var_render_product_path: Any = _UNSET,
        supports_render_var_clear: bool | None = None,
        scene_label: Any = _UNSET,
        fps: Any = _UNSET,
        resolution: Any = _UNSET,
        stream: ViewportStreamState | None = None,
        toolbar_availability: Mapping[str, Mapping[str, Any]] | None = None,
        viewport_ui_state: Mapping[str, Any] | None = None,
        capability_state: Mapping[str, Any] | None = None,
        stage_identifier: Any = _UNSET,
        notify: bool = True,
    ) -> ViewportStateSnapshot:
        current = self._snapshot
        next_tool = self._normalize_contract_tool(active_tool or current.active_tool)
        next_ovui_tool = ovui_tool or CONTRACT_TOOL_TO_OVUI_TOOL[next_tool]
        if available_tools is not None:
            self._available_tools = _tuple_or_empty(available_tools) or TRANSFORM_TOOL_IDS
        if tool_registry_available is not None:
            self._tool_registry_available = bool(tool_registry_available)
        next_cameras = tuple(cameras) if cameras is not None else current.cameras
        next_target_groups = tuple(render_target_groups) if render_target_groups is not None else current.render_target_groups
        next_render_var_items = tuple(render_var_items) if render_var_items is not None else current.render_var_items
        next_toolbar = toolbar_availability or self._toolbar_availability(
            next_cameras,
            next_target_groups,
            next_render_var_items,
        )
        snapshot = ViewportStateSnapshot(
            revision=self._next_revision(),
            active_tool=next_tool,
            ovui_tool=next_ovui_tool,
            available_tools=self._available_tools,
            tool_registry_available=self._tool_registry_available,
            cameras=next_cameras,
            active_camera_path=(
                current.active_camera_path if active_camera_path is _UNSET else active_camera_path
            ),
            active_camera_label=(
                current.active_camera_label if active_camera_label is _UNSET else active_camera_label
            ),
            render_target_catalog=render_target_catalog or current.render_target_catalog,
            render_target_groups=next_target_groups,
            active_target_id=current.active_target_id if active_target_id is _UNSET else active_target_id,
            active_kind=current.active_kind if active_kind is _UNSET else active_kind,
            active_target_label=(
                current.active_target_label if active_target_label is _UNSET else active_target_label
            ),
            active_target_capability=(
                current.active_target_capability
                if active_target_capability is _UNSET
                else active_target_capability
            ),
            active_render_product_path=(
                current.active_render_product_path
                if active_render_product_path is _UNSET
                else active_render_product_path
            ),
            render_var_catalog=render_var_catalog or current.render_var_catalog,
            render_var_items=next_render_var_items,
            active_render_var_output_id=(
                current.active_render_var_output_id
                if active_render_var_output_id is _UNSET
                else active_render_var_output_id
            ),
            render_var_render_product_path=(
                current.render_var_render_product_path
                if render_var_render_product_path is _UNSET
                else render_var_render_product_path
            ),
            supports_render_var_clear=(
                supports_render_var_clear
                if supports_render_var_clear is not None
                else current.supports_render_var_clear
            ),
            scene_label=current.scene_label if scene_label is _UNSET else scene_label,
            fps=current.fps if fps is _UNSET else fps,
            resolution=current.resolution if resolution is _UNSET else resolution,
            stream=stream if stream is not None else current.stream,
            toolbar_availability=next_toolbar,
            viewport_ui_state=viewport_ui_state if viewport_ui_state is not None else current.viewport_ui_state,
            capability_state=capability_state if capability_state is not None else current.capability_state,
            stage_identifier=current.stage_identifier if stage_identifier is _UNSET else stage_identifier,
        )
        self._active_tool = snapshot.active_tool
        self._snapshot = snapshot
        if notify:
            self._notify(snapshot)
        return snapshot

    def refresh_from_adapters(
        self,
        *,
        stage_adapter: Any | None = None,
        renderer_adapter: Any | None = None,
        render_settings_adapter: Any | None = None,
        selection_bus: Any | None = None,
        viewport: Any | None = None,
        current_usd_path: str = "",
        active_tool: str | None = None,
        available_tools: Iterable[str] | None = None,
        tool_registry_available: bool | None = None,
        fps: float | None = None,
        resolution: Iterable[int] | Mapping[str, int] | None = None,
        stream_state: str = "OFF",
        client_count: int = 0,
        stream_label: str = "",
        protocol: str = "webrtc",
        signal_port: int = 0,
        media_port: int = 0,
        stream_source: str = "ViewportStateAdapter",
        viewport_ui_state: Mapping[str, Any] | None = None,
        notify: bool = True,
    ) -> ViewportStateSnapshot:
        if stage_adapter is not None:
            self.stage_adapter = stage_adapter
        if renderer_adapter is not None:
            self.renderer_adapter = renderer_adapter
        if render_settings_adapter is not None:
            self.render_settings_adapter = render_settings_adapter
        if selection_bus is not None:
            self.selection_bus = selection_bus
        if viewport is not None:
            self.viewport = viewport
        if available_tools is not None:
            self._available_tools = _tuple_or_empty(available_tools) or TRANSFORM_TOOL_IDS
        if tool_registry_available is not None:
            self._tool_registry_available = bool(tool_registry_available)
        if active_tool is not None:
            self._active_tool = self._normalize_contract_tool(active_tool)

        cameras, active_camera_path, active_camera_label = self._read_cameras()
        render_catalog, target_groups, target_state = self._read_render_targets()
        render_var_catalog, render_var_items, render_var_state = self._read_render_vars(
            target_state["active_render_product_path"]
        )
        normalized_stream = _normalize_stream_state(stream_state, int(client_count or 0))
        stream = ViewportStreamState(
            state=normalized_stream,
            label=stream_label
            or _stream_label(normalized_stream, int(client_count or 0), signal_port, media_port),
            client_count=int(client_count or 0),
            protocol=protocol,
            signal_port=signal_port,
            media_port=media_port,
            source=stream_source,
        )
        scene_label = Path(current_usd_path).name if current_usd_path else None
        return self.update(
            active_tool=self._active_tool,
            ovui_tool=CONTRACT_TOOL_TO_OVUI_TOOL[self._active_tool],
            available_tools=self._available_tools,
            tool_registry_available=self._tool_registry_available,
            cameras=cameras,
            active_camera_path=active_camera_path,
            active_camera_label=active_camera_label,
            render_target_catalog=render_catalog,
            render_target_groups=target_groups,
            active_target_id=target_state["active_target_id"],
            active_kind=target_state["active_kind"],
            active_target_label=target_state["active_label"],
            active_target_capability=target_state["active_capability"],
            active_render_product_path=target_state["active_render_product_path"],
            render_var_catalog=render_var_catalog,
            render_var_items=render_var_items,
            active_render_var_output_id=render_var_state["active_output_id"],
            render_var_render_product_path=render_var_state["active_render_product_path"],
            supports_render_var_clear=bool(render_var_items),
            scene_label=scene_label,
            fps=fps,
            resolution=resolution,
            stream=stream,
            viewport_ui_state=viewport_ui_state,
            stage_identifier=str(current_usd_path or ""),
            notify=notify,
        )

    def _next_revision(self) -> int:
        self._revision += 1
        return self._revision

    def _notify(self, snapshot: ViewportStateSnapshot) -> None:
        for callback in tuple(self._callbacks):
            callback(snapshot)

    def _normalize_contract_tool(self, tool: str) -> str:
        raw = str(tool or "move").lower()
        contract = OVUI_TOOL_TO_CONTRACT_TOOL.get(raw, raw)
        return contract if contract in TRANSFORM_TOOL_IDS else "move"

    def _read_cameras(self) -> tuple[Tuple[ViewportCameraState, ...], str | None, str]:
        list_cameras = getattr(self.stage_adapter, "list_cameras", None)
        items: list[ViewportCameraState] = []
        if callable(list_cameras):
            try:
                for choice in list_cameras() or ():
                    path = _nonempty_string(getattr(choice, "path", None))
                    if path is None or not path.startswith("/"):
                        continue
                    label = str(
                        getattr(choice, "display_name", "")
                        or getattr(choice, "label", "")
                        or _label_for_path(path)
                    )
                    items.append(ViewportCameraState(path=path, label=label))
            except Exception:
                items = []
        active_path = self._active_camera_path_from_renderer()
        if active_path is not None and not active_path.startswith("/"):
            active_path = None
        active_label = _label_for_path(active_path) if active_path else "None"
        active_items: list[ViewportCameraState] = []
        for item in items:
            is_active = item.path == active_path
            active_items.append(
                ViewportCameraState(
                    path=item.path,
                    label=item.label,
                    source=item.source,
                    is_active=is_active,
                )
            )
            if is_active:
                active_label = item.label
        return (tuple(active_items), active_path, active_label)

    def _read_render_targets(self) -> tuple[RenderTargetCatalog, Tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
        get_catalog = getattr(self.stage_adapter, "get_render_target_catalog", None)
        catalog = RenderTargetCatalog()
        targets: tuple[Any, ...] = ()
        if callable(get_catalog):
            try:
                catalog = get_catalog()
                targets = tuple(getattr(catalog, "targets", ()) or ())
            except Exception:
                catalog = RenderTargetCatalog()
                targets = ()
        active_render_product_path = _nonempty_string(getattr(catalog, "active_render_product_path", None))
        if active_render_product_path is None:
            active_render_product_path = self._active_render_product_path_from_renderer()
        active_target_id = _nonempty_string(getattr(catalog, "active_target_id", None))
        groups_by_kind: dict[str, dict[str, Any]] = {}
        active_kind: str | None = None
        active_label = "None"
        active_capability = "none"
        for target in targets:
            item = self._render_target_item(target)
            if item is None:
                continue
            kind = str(item["kind"])
            group = groups_by_kind.setdefault(kind, {"kind": kind, "label": _kind_label(kind), "items": []})
            is_active = False
            if active_target_id is not None and item["target_id"] == active_target_id:
                is_active = True
            elif active_target_id is None and active_render_product_path is not None:
                is_active = item.get("render_product_path") == active_render_product_path
            item["is_active"] = bool(is_active)
            if is_active:
                active_target_id = str(item["target_id"])
                active_kind = kind
                active_label = str(item["label"])
                active_capability = str(item.get("capability") or "unknown")
                active_render_product_path = (
                    _nonempty_string(item.get("render_product_path")) or active_render_product_path
                )
            group["items"].append(item)
        groups = tuple(MappingProxyType({"kind": group["kind"], "label": group["label"], "items": tuple(group["items"])}) for group in groups_by_kind.values())
        state = MappingProxyType(
            {
                "active_target_id": active_target_id,
                "active_kind": active_kind,
                "active_label": active_label,
                "active_capability": active_capability,
                "active_render_product_path": active_render_product_path,
            }
        )
        return catalog, groups, state

    def _render_target_item(self, target: Any) -> dict[str, Any] | None:
        target_id = _nonempty_string(getattr(target, "target_id", None)) or _nonempty_string(
            getattr(target, "render_product_path", None)
        )
        if target_id is None:
            return None
        kind = _target_ui_kind(target)
        enabled = bool(getattr(target, "enabled", True)) and not bool(getattr(target, "disabled_reason", ""))
        item: dict[str, Any] = {
            "target_id": target_id,
            "label": str(
                getattr(target, "display_label", "")
                or getattr(target, "display_name", "")
                or getattr(target, "source_display_name", "")
                or target_id
            ),
            "kind": kind,
            "render_product_path": _nonempty_string(getattr(target, "render_product_path", None)),
            "source_path": _nonempty_string(getattr(target, "source_path", None)),
            "source_type": _nonempty_string(getattr(target, "source_type", None)),
            "output_kind": _enum_value(getattr(target, "output_kind", None)) or "unknown",
            "enabled": enabled,
            "disabled": not enabled,
            "reason": str(getattr(target, "disabled_reason", "") or ""),
            "capability": "supported" if enabled else "unsupported",
            "source": "ViewportStateAdapter.stage_adapter.get_render_target_catalog",
        }
        resolution = getattr(target, "resolution", None)
        if isinstance(resolution, tuple) and len(resolution) == 2:
            item["resolution"] = f"{resolution[0]}x{resolution[1]}"
        output_names = tuple(str(name) for name in (getattr(target, "output_names", ()) or ()))
        if output_names:
            item["output_names"] = list(output_names)
        capabilities = tuple(str(value) for value in (getattr(target, "capabilities", ()) or ()))
        if capabilities:
            item["capabilities"] = list(capabilities)
        warnings = _warning_payloads(getattr(target, "warnings", ()) or ())
        if warnings:
            item["warnings"] = warnings
        return item

    def _read_render_vars(
        self,
        active_render_product_path: str | None,
    ) -> tuple[RenderVarOutputCatalog, Tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
        list_outputs = getattr(self.renderer_adapter, "list_render_var_outputs", None)
        catalog = RenderVarOutputCatalog()
        outputs: tuple[Any, ...] = ()
        if callable(list_outputs):
            try:
                if active_render_product_path:
                    catalog = list_outputs(active_render_product_path)
                else:
                    catalog = list_outputs()
                outputs = tuple(getattr(catalog, "outputs", ()) or ())
            except Exception:
                catalog = RenderVarOutputCatalog()
                outputs = ()
            if not outputs:
                try:
                    fallback_catalog = list_outputs()
                    fallback_outputs = tuple(getattr(fallback_catalog, "outputs", ()) or ())
                except Exception:
                    fallback_catalog = RenderVarOutputCatalog()
                    fallback_outputs = ()
                if fallback_outputs:
                    catalog = fallback_catalog
                    outputs = fallback_outputs
        active_output_id = _nonempty_string(getattr(catalog, "active_output_id", None))
        if active_output_id is None:
            active_output_id = _nonempty_string(getattr(catalog, "selected_output_id", None))
        catalog_product_path = (
            _nonempty_string(getattr(catalog, "active_render_product_path", None))
            or active_render_product_path
        )
        items: list[Mapping[str, Any]] = []
        for output in outputs:
            item = self._render_var_item(output)
            if item is None:
                continue
            item["is_active"] = item["id"] == active_output_id
            items.append(MappingProxyType(item))
        state = MappingProxyType(
            {
                "active_output_id": active_output_id,
                "active_render_product_path": catalog_product_path,
            }
        )
        return catalog, tuple(items), state

    def _render_var_item(self, output: Any) -> dict[str, Any] | None:
        output_id = _nonempty_string(getattr(output, "output_id", None))
        if output_id is None:
            return None
        enabled = bool(getattr(output, "enabled", True)) and not bool(getattr(output, "disabled_reason", ""))
        item: dict[str, Any] = {
            "id": output_id,
            "label": str(
                getattr(output, "display_name", "")
                or getattr(output, "render_var_name", "")
                or output_id
            ),
            "kind": _enum_value(getattr(output, "output_kind", None)) or "unknown",
            "render_product_path": _nonempty_string(getattr(output, "render_product_path", None)),
            "render_var_name": _nonempty_string(getattr(output, "render_var_name", None)),
            "enabled": enabled,
            "disabled": not enabled,
            "reason": str(getattr(output, "disabled_reason", "") or ""),
            "source": "ViewportStateAdapter.renderer_adapter.list_render_var_outputs",
        }
        dtype = _nonempty_string(getattr(output, "dtype", None))
        if dtype:
            item["dtype"] = dtype
        component_count = getattr(output, "component_count", None)
        if isinstance(component_count, int) and not isinstance(component_count, bool):
            item["component_count"] = component_count
        warnings = _warning_payloads(getattr(output, "warnings", ()) or ())
        if warnings:
            item["warnings"] = warnings
        return item

    def _toolbar_availability(
        self,
        cameras: Iterable[Any],
        render_target_groups: Iterable[Mapping[str, Any]],
        render_var_items: Iterable[Mapping[str, Any]],
    ) -> Mapping[str, Mapping[str, Any]]:
        availability: dict[str, Mapping[str, Any]] = {
            "move": {"available": self._tool_registry_available, "hotkey": "W"},
            "rotate": {"available": self._tool_registry_available, "hotkey": "E"},
            "scale": {"available": self._tool_registry_available, "hotkey": "R"},
            "camera": {
                "available": bool(tuple(cameras)),
                "source": "ViewportStateAdapter.stage_adapter.list_cameras",
            },
            "render_target": {
                "available": any(tuple(group.get("items", ()) or ()) for group in render_target_groups),
                "source": "ViewportStateAdapter.stage_adapter.get_render_target_catalog",
            },
            "rendervar": {
                "available": bool(tuple(render_var_items)),
                "source": "ViewportStateAdapter.renderer_adapter.list_render_var_outputs",
            },
            "path_tracing_progress": {
                "available": False,
                "reason": "Renderer progress telemetry is outside the SRD React-visible toolbar state.",
            },
            "grid_overlay": {
                "available": False,
                "disabled_placeholder": True,
                "reason": "Grid overlay control is not exposed by the viewport state adapter.",
            },
        }
        if not self._tool_registry_available:
            for control in TRANSFORM_TOOL_IDS:
                availability[control] = {
                    **dict(availability[control]),
                    "reason": "Real ovui ToolRegistry is unavailable.",
                }
        for control in TOOLBAR_REQUIRED_CONTROLS:
            availability.setdefault(control, {"available": False})
        return _freeze_nested_mapping(availability)

    def _active_camera_path_from_renderer(self) -> str | None:
        get_active = getattr(self.renderer_adapter, "get_active_camera_path", None)
        if not callable(get_active):
            return None
        try:
            return _nonempty_string(get_active())
        except Exception:
            return None

    def _active_render_product_path_from_renderer(self) -> str | None:
        get_active = getattr(self.renderer_adapter, "get_active_render_product_path", None)
        if not callable(get_active):
            return None
        try:
            return _nonempty_string(get_active())
        except Exception:
            return None


__all__ = [
    "CONTRACT_TOOL_TO_OVUI_TOOL",
    "OVUI_TOOL_TO_CONTRACT_TOOL",
    "TOOLBAR_REQUIRED_CONTROLS",
    "TRANSFORM_TOOL_IDS",
    "ViewportCameraState",
    "ViewportStateAdapter",
    "ViewportStateSnapshot",
    "ViewportStreamState",
]
