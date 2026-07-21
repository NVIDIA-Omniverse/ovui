# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Generic viewport contribution registry.

These hooks are deliberately backend- and feature-agnostic. The viewport owns
when callbacks run and which generic surfaces are available; optional packages
own what they draw, update, or display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import sys
from typing import Any, Callable, Iterable, Literal


ViewportContributionKind = Literal[
    "point_cloud_renderer",
    "output_preset",
    "overlay",
    "anchored_panel",
    "probe_tool",
]
ViewportPanelAnchor = Literal[
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "center",
]
ViewportPredicate = Callable[[Any], bool]
ViewportLifecycleCallback = Callable[[Any], None]
ViewportFrameCallback = Callable[["ViewportFrameContext"], None]
ViewportOverlayBuildCallback = Callable[["ViewportOverlayContext"], None]
ViewportPanelBuildCallback = Callable[["ViewportPanelContext"], None]
ViewportProbeCallback = Callable[["ViewportProbeContext"], Any]


def _default_widget_name(prefix: str, contribution_id: str) -> str:
    safe_id = contribution_id.replace("/", "_").replace(".", "_")
    return f"{prefix}_{safe_id}"


@dataclass(frozen=True)
class ViewportFrameContext:
    """Per-frame context passed to renderer-style viewport contributions."""

    owner: Any
    width: int
    height: int
    render_dt: float
    view_matrix: Any
    projection_matrix: Any
    image_frame: Any = None
    image_bridge: Any = None
    scene_view: Any = None


@dataclass(frozen=True)
class ViewportOverlayContext:
    """Scene overlay build context passed while the viewport scene is active."""

    owner: Any
    scene_view: Any
    scene: Any


@dataclass(frozen=True)
class ViewportPanelContext:
    """Viewport-local panel build context."""

    owner: Any
    ui_module: Any
    anchor: ViewportPanelAnchor


@dataclass(frozen=True)
class ViewportProbeContext:
    """Pointer context passed to generic viewport probe contributions."""

    owner: Any
    x: float
    y: float
    width: int
    height: int
    normalized_x: float
    normalized_y: float
    view_matrix: Any = None
    projection_matrix: Any = None
    image_frame: Any = None
    scene_view: Any = None


@dataclass(frozen=True)
class ViewportProbeResult:
    """Generic readout returned by viewport probe contributions."""

    id: str
    label: str = ""
    text: str = ""
    tooltip: str = ""
    payload: Any = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("probe result id is required")
        object.__setattr__(self, "label", str(self.label or self.id))
        object.__setattr__(self, "text", str(self.text or ""))
        object.__setattr__(self, "tooltip", str(self.tooltip or ""))


@dataclass(frozen=True)
class _ViewportContribution:
    id: str
    label: str
    order: float = 1000.0
    before: str | None = None
    after: str | None = None
    capabilities: Iterable[str] = field(default_factory=tuple)
    visible_fn: ViewportPredicate | None = None
    enabled_fn: ViewportPredicate | None = None
    on_add: ViewportLifecycleCallback | None = None
    on_remove: ViewportLifecycleCallback | None = None
    widget_name: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("contribution id is required")
        if not self.label:
            raise ValueError("contribution label is required")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


@dataclass(frozen=True)
class ViewportPointCloudRenderer(_ViewportContribution):
    """Generic per-frame viewport contribution.

    The name follows the SRD contribution kind, but the callback receives only
    a generic frame context. Feature-specific filtering and display policy are
    intentionally owned by external modules.
    """

    update_fn: ViewportFrameCallback | None = None
    kind: ViewportContributionKind = "point_cloud_renderer"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_point_cloud_renderer", self.id),
            )


@dataclass(frozen=True)
class ViewportOutputPreset(_ViewportContribution):
    """Generic per-frame display-output contribution."""

    update_fn: ViewportFrameCallback | None = None
    kind: ViewportContributionKind = "output_preset"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_output_preset", self.id),
            )


@dataclass(frozen=True)
class ViewportOverlay(_ViewportContribution):
    """Generic scene-overlay contribution."""

    build_fn: ViewportOverlayBuildCallback | None = None
    kind: ViewportContributionKind = "overlay"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_overlay", self.id),
            )


@dataclass(frozen=True)
class ViewportAnchoredPanel(_ViewportContribution):
    """Generic viewport-local anchored panel contribution."""

    build_fn: ViewportPanelBuildCallback | None = None
    anchor: ViewportPanelAnchor = "top_left"
    kind: ViewportContributionKind = "anchored_panel"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_anchored_panel", self.id),
            )


@dataclass(frozen=True)
class ViewportProbeTool(_ViewportContribution):
    """Generic pointer-probe contribution."""

    probe_fn: ViewportProbeCallback | None = None
    anchor: ViewportPanelAnchor = "bottom_right"
    kind: ViewportContributionKind = "probe_tool"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_probe_tool", self.id),
            )


class ViewportContributionHandle:
    """Removable handle returned from ``ViewportContributionRegistry.add``."""

    def __init__(
        self,
        registry: "ViewportContributionRegistry",
        contribution_id: str,
    ) -> None:
        self._registry = registry
        self._contribution_id = contribution_id

    @property
    def id(self) -> str:
        return self._contribution_id

    def remove(self) -> bool:
        return self._registry.remove(self._contribution_id)


class ViewportContributionRegistry:
    """Registry for generic viewport-local contributions."""

    def __init__(self, owner: Any, *, capabilities: Iterable[str] = ()) -> None:
        self._owner = owner
        self._entries: dict[str, _ViewportContribution] = {}
        self._capabilities: set[str] = set(capabilities)
        self._failures: dict[str, BaseException] = {}

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._capabilities)

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

    def set_capability(self, capability: str, enabled: bool = True) -> None:
        if enabled:
            self._capabilities.add(capability)
        else:
            self._capabilities.discard(capability)

    def set_capabilities(self, capabilities: Iterable[str]) -> None:
        self._capabilities = set(capabilities)

    def add(
        self,
        contribution: _ViewportContribution,
    ) -> ViewportContributionHandle:
        """Register a contribution once and return its removal handle."""

        if contribution.id in self._entries:
            return ViewportContributionHandle(self, contribution.id)
        self._entries[contribution.id] = contribution
        self._invoke_lifecycle(contribution, "add")
        return ViewportContributionHandle(self, contribution.id)

    def remove(self, contribution_id: str) -> bool:
        contribution = self._entries.pop(contribution_id, None)
        if contribution is None:
            return False
        self._invoke_lifecycle(contribution, "remove")
        return True

    def clear(self) -> None:
        for contribution_id in reversed(tuple(self._entries)):
            self.remove(contribution_id)

    def iter_contributions(
        self,
        kind: ViewportContributionKind | None = None,
    ) -> tuple[_ViewportContribution, ...]:
        entries = [
            entry
            for entry in self._entries.values()
            if (kind is None or getattr(entry, "kind", None) == kind)
            and self._is_available(entry)
        ]
        return tuple(self._apply_anchors(entries))

    def build_overlays(self, scene_view: Any) -> None:
        scene = getattr(scene_view, "scene", None)
        context = ViewportOverlayContext(
            owner=self._owner,
            scene_view=scene_view,
            scene=scene,
        )
        for contribution in self.iter_contributions("overlay"):
            if not isinstance(contribution, ViewportOverlay):
                continue
            if contribution.build_fn is None or not self._enabled(contribution):
                continue
            try:
                contribution.build_fn(context)
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("overlay", contribution.id, exc)

    def build_anchored_panels(self, ui_module: Any) -> None:
        for contribution in self.iter_contributions("anchored_panel"):
            if not isinstance(contribution, ViewportAnchoredPanel):
                continue
            if contribution.build_fn is None or not self._enabled(contribution):
                continue
            context = ViewportPanelContext(
                owner=self._owner,
                ui_module=ui_module,
                anchor=contribution.anchor,
            )
            try:
                contribution.build_fn(context)
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("panel", contribution.id, exc)

    def update_frame(self, context: ViewportFrameContext) -> None:
        self._update_frame_kind(
            "point_cloud_renderer",
            ViewportPointCloudRenderer,
            context,
        )
        self._update_frame_kind(
            "output_preset",
            ViewportOutputPreset,
            context,
        )

    def probe(self, context: ViewportProbeContext) -> tuple[ViewportProbeResult, ...]:
        results: list[ViewportProbeResult] = []
        for contribution in self.iter_contributions("probe_tool"):
            if not isinstance(contribution, ViewportProbeTool):
                continue
            if contribution.probe_fn is None or not self._enabled(contribution):
                continue
            try:
                value = contribution.probe_fn(context)
                results.extend(self._coerce_probe_results(contribution.id, value))
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("probe", contribution.id, exc)
        return tuple(results)

    def _update_frame_kind(
        self,
        kind: ViewportContributionKind,
        contribution_type: type[ViewportPointCloudRenderer | ViewportOutputPreset],
        context: ViewportFrameContext,
    ) -> None:
        for contribution in self.iter_contributions(kind):
            if not isinstance(contribution, contribution_type):
                continue
            if contribution.update_fn is None or not self._enabled(contribution):
                continue
            try:
                contribution.update_fn(context)
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("frame", contribution.id, exc)

    @staticmethod
    def _coerce_probe_results(
        contribution_id: str,
        value: Any,
    ) -> tuple[ViewportProbeResult, ...]:
        if value is None:
            return ()
        if isinstance(value, ViewportProbeResult):
            return (value,)
        if isinstance(value, str):
            return (ViewportProbeResult(id=contribution_id, text=value),)
        try:
            return tuple(
                result
                for result in value
                if isinstance(result, ViewportProbeResult)
            )
        except TypeError:
            return (
                ViewportProbeResult(
                    id=contribution_id,
                    text=str(value),
                    payload=value,
                ),
            )

    def _apply_anchors(
        self,
        entries: list[_ViewportContribution],
    ) -> list[_ViewportContribution]:
        ordered = sorted(entries, key=lambda entry: (float(entry.order), entry.id))
        for entry in tuple(ordered):
            target_id = entry.before or entry.after
            if not target_id:
                continue
            current_index = self._index_of(ordered, entry.id)
            target_index = self._index_of(ordered, target_id)
            if current_index is None or target_index is None:
                continue
            item = ordered.pop(current_index)
            if current_index < target_index:
                target_index -= 1
            insert_at = target_index if entry.before else target_index + 1
            ordered.insert(insert_at, item)
        return ordered

    @staticmethod
    def _index_of(
        entries: list[_ViewportContribution],
        contribution_id: str,
    ) -> int | None:
        for index, entry in enumerate(entries):
            if entry.id == contribution_id:
                return index
        return None

    def _is_available(self, contribution: _ViewportContribution) -> bool:
        if any(capability not in self._capabilities for capability in contribution.capabilities):
            return False
        if contribution.visible_fn is None:
            return True
        try:
            return bool(contribution.visible_fn(self._owner))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("visible", contribution.id, exc)
            return False

    def _enabled(self, contribution: _ViewportContribution) -> bool:
        if contribution.enabled_fn is None:
            return True
        try:
            return bool(contribution.enabled_fn(self._owner))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("enabled", contribution.id, exc)
            return False

    def _invoke_lifecycle(self, contribution: _ViewportContribution, action: str) -> None:
        fn = contribution.on_add if action == "add" else contribution.on_remove
        if fn is None:
            return
        try:
            fn(self._owner)
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log(action, contribution.id, exc)

    @staticmethod
    def _log(action: str, contribution_id: str, exc: BaseException) -> None:
        print(
            f"[ovui_widgets.viewport.viewport_hooks] {action} failed for "
            f"{contribution_id}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


__all__ = [
    "ViewportAnchoredPanel",
    "ViewportContributionHandle",
    "ViewportContributionRegistry",
    "ViewportFrameContext",
    "ViewportOverlay",
    "ViewportOverlayContext",
    "ViewportOutputPreset",
    "ViewportPanelContext",
    "ViewportPointCloudRenderer",
    "ViewportProbeContext",
    "ViewportProbeResult",
    "ViewportProbeTool",
]
