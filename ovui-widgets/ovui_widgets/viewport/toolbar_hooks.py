# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Viewport-owned toolbar contribution registry."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

ToolbarKind = Literal["action", "menu", "badge"]
ToolbarCallback = Callable[[Any], None]
ToolbarBuildCallback = Callable[[Any, Any], None]
ToolbarPredicate = Callable[[Any], bool]
ToolbarTextProvider = Callable[[Any], str]


def _default_widget_name(prefix: str, contribution_id: str) -> str:
    safe_id = contribution_id.replace("/", "_").replace(".", "_")
    return f"{prefix}_{safe_id}"


@dataclass(frozen=True)
class _ToolbarContribution:
    id: str
    label: str
    order: float = 1000.0
    before: str | None = None
    after: str | None = None
    capabilities: Iterable[str] = field(default_factory=tuple)
    visible_fn: ToolbarPredicate | None = None
    enabled_fn: ToolbarPredicate | None = None
    on_add: ToolbarCallback | None = None
    on_remove: ToolbarCallback | None = None
    widget_name: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("contribution id is required")
        if not self.label:
            raise ValueError("contribution label is required")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


@dataclass(frozen=True)
class ViewportToolbarAction(_ToolbarContribution):
    """Clickable viewport toolbar action."""

    callback: ToolbarCallback | None = None
    tooltip: str = ""
    icon_path: str | None = None
    kind: ToolbarKind = "action"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_toolbar_action", self.id),
            )


@dataclass(frozen=True)
class ViewportToolbarMenu(_ToolbarContribution):
    """Popup menu owned by the viewport toolbar."""

    build_fn: ToolbarBuildCallback | None = None
    tooltip: str = ""
    icon_path: str | None = None
    kind: ToolbarKind = "menu"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_toolbar_menu", self.id),
            )


@dataclass(frozen=True)
class ViewportStatusBadge(_ToolbarContribution):
    """Small viewport status indicator."""

    text_fn: ToolbarTextProvider | None = None
    tooltip_fn: ToolbarTextProvider | None = None
    kind: ToolbarKind = "badge"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.widget_name is None:
            object.__setattr__(
                self,
                "widget_name",
                _default_widget_name("viewport_status_badge", self.id),
            )


class ViewportToolbarHandle:
    """Removable handle returned from ``ViewportToolbarRegistry.add``."""

    def __init__(self, registry: "ViewportToolbarRegistry", contribution_id: str) -> None:
        self._registry = registry
        self._contribution_id = contribution_id

    @property
    def id(self) -> str:
        return self._contribution_id

    def remove(self) -> bool:
        return self._registry.remove(self._contribution_id)


class ViewportToolbarRegistry:
    """Registry for package-local toolbar contributions."""

    def __init__(self, owner: Any, *, capabilities: Iterable[str] = ()) -> None:
        self._owner = owner
        self._entries: dict[str, _ToolbarContribution] = {}
        self._capabilities: set[str] = set(capabilities)
        self._failures: dict[str, BaseException] = {}
        self._menus: dict[str, Any] = {}
        self._menu_anchors: dict[str, Any] = {}
        self._icon_providers: dict[str, Any] = {}
        self._widgets: dict[str, Any] = {}

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._capabilities)

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

    def built_widget_geometry(self) -> tuple[dict[str, Any], ...]:
        """Return current toolbar contribution hit geometry."""

        rows: list[dict[str, Any]] = []
        for contribution in self.iter_contributions():
            widget = self._widgets.get(contribution.id)
            if widget is None:
                continue
            width = float(getattr(widget, "computed_width", 0.0) or 0.0)
            height = float(getattr(widget, "computed_height", 0.0) or 0.0)
            x = float(getattr(widget, "screen_position_x", 0.0) or 0.0)
            y = float(getattr(widget, "screen_position_y", 0.0) or 0.0)
            rect = (
                {"x": x, "y": y, "width": width, "height": height}
                if width > 0.0 and height > 0.0
                else None
            )
            rows.append(
                {
                    "id": contribution.id,
                    "label": contribution.label,
                    "kind": contribution.kind,
                    "enabled": self._enabled(contribution),
                    "widget_name": contribution.widget_name or "",
                    "rect": rect,
                    "point": (
                        [
                            int(round(x + width * 0.5)),
                            int(round(y + height * 0.5)),
                        ]
                        if rect is not None
                        else None
                    ),
                }
            )
        return tuple(rows)

    def set_capability(self, capability: str, enabled: bool = True) -> None:
        if enabled:
            self._capabilities.add(capability)
        else:
            self._capabilities.discard(capability)

    def set_capabilities(self, capabilities: Iterable[str]) -> None:
        self._capabilities = set(capabilities)

    def add(self, contribution: _ToolbarContribution) -> ViewportToolbarHandle:
        """Register a contribution once and return its removal handle."""
        if contribution.id in self._entries:
            return ViewportToolbarHandle(self, contribution.id)
        self._entries[contribution.id] = contribution
        self._invoke_lifecycle(contribution, "add")
        return ViewportToolbarHandle(self, contribution.id)

    def remove(self, contribution_id: str) -> bool:
        contribution = self._entries.pop(contribution_id, None)
        if contribution is None:
            return False
        self._widgets.pop(contribution_id, None)
        self._destroy_menu(contribution_id)
        self._menu_anchors.pop(contribution_id, None)
        self._invoke_lifecycle(contribution, "remove")
        return True

    def clear(self) -> None:
        for contribution_id in reversed(tuple(self._entries)):
            self.remove(contribution_id)

    def iter_contributions(
        self,
        kind: ToolbarKind | None = None,
    ) -> tuple[_ToolbarContribution, ...]:
        entries = [
            entry
            for entry in self._entries.values()
            if (kind is None or getattr(entry, "kind", None) == kind)
            and self._is_available(entry)
        ]
        return tuple(self._apply_anchors(entries))

    def build_toolbar(
        self,
        ui_module: Any,
        *,
        button_size: int,
    ) -> None:
        for contribution in self.iter_contributions():
            try:
                if isinstance(contribution, ViewportToolbarAction):
                    self._build_action(contribution, ui_module, button_size)
                elif isinstance(contribution, ViewportToolbarMenu):
                    self._build_menu(contribution, ui_module, button_size)
                elif isinstance(contribution, ViewportStatusBadge):
                    self._build_badge(contribution, ui_module)
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("build", contribution.id, exc)

    def _build_action(
        self,
        contribution: ViewportToolbarAction,
        ui: Any,
        button_size: int,
    ) -> None:
        if contribution.icon_path:
            self._widgets[contribution.id] = self._build_icon_button(
                contribution,
                ui,
                button_size,
                clicked_fn=self._make_callback(contribution),
            )
            return
        button = ui.Button(
            contribution.label,
            width=button_size,
            height=button_size,
            enabled=self._enabled(contribution),
            identifier=contribution.widget_name,
            clicked_fn=self._make_callback(contribution),
        )
        self._widgets[contribution.id] = button
        tooltip = contribution.tooltip or contribution.label
        if tooltip:
            try:
                button.tooltip = tooltip
            except Exception:
                pass
        ui.Spacer(width=3)

    def _build_menu(
        self,
        contribution: ViewportToolbarMenu,
        ui: Any,
        button_size: int,
    ) -> None:
        if contribution.icon_path:
            holder: dict[str, Any] = {}

            def _clicked() -> None:
                self._show_menu(contribution, holder["button"])

            holder["button"] = self._build_icon_button(
                contribution,
                ui,
                button_size,
                clicked_fn=_clicked,
            )
            self._widgets[contribution.id] = holder["button"]
            return
        button = ui.Button(
            contribution.label,
            width=button_size,
            height=button_size,
            enabled=self._enabled(contribution),
            identifier=contribution.widget_name,
            clicked_fn=lambda c=contribution: self._show_menu(c, button),
        )
        self._widgets[contribution.id] = button
        tooltip = contribution.tooltip or contribution.label
        if tooltip:
            try:
                button.tooltip = tooltip
            except Exception:
                pass
        ui.Spacer(width=3)

    def _build_icon_button(
        self,
        contribution: _ToolbarContribution,
        ui: Any,
        button_size: int,
        *,
        clicked_fn: Callable[[], None] | None,
    ) -> Any:
        icon_size = max(1, int(button_size) - 7)
        tooltip = getattr(contribution, "tooltip", "") or contribution.label
        with ui.ZStack(
            width=button_size,
            height=button_size,
            content_clipping=True,
        ):
            ui.Rectangle(
                style_type_name_override="Viewport.Toolbar.Button",
            )
            with ui.VStack(spacing=0):
                ui.Spacer()
                with ui.HStack(height=icon_size, spacing=0):
                    ui.Spacer()
                    ui.ImageWithProvider(
                        self._icon_provider(ui, str(getattr(contribution, "icon_path"))),
                        width=icon_size,
                        height=icon_size,
                        enabled=False,
                        opaque_for_mouse_events=False,
                        style_type_name_override="Viewport.Toolbar.Icon",
                    )
                    ui.Spacer()
                ui.Spacer()
            button = ui.InvisibleButton(
                width=button_size,
                height=button_size,
                enabled=self._enabled(contribution),
                identifier=contribution.widget_name,
                tooltip=tooltip,
            )
            if clicked_fn is not None:
                button.set_clicked_fn(clicked_fn)
        ui.Spacer(width=3)
        return button

    def _icon_provider(self, ui: Any, icon_path: str) -> Any:
        provider = self._icon_providers.get(icon_path)
        if provider is None:
            provider = ui.RasterImageProvider(icon_path)
            self._icon_providers[icon_path] = provider
        return provider

    def _build_badge(self, contribution: ViewportStatusBadge, ui: Any) -> None:
        text = contribution.label
        if contribution.text_fn is not None:
            try:
                text = str(contribution.text_fn(self._owner))
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("text", contribution.id, exc)
                text = contribution.label
        label = ui.Label(
            text,
            enabled=self._enabled(contribution),
            name=contribution.widget_name,
            style_type_name_override="Viewport.HUD.Value",
        )
        self._widgets[contribution.id] = label
        if contribution.tooltip_fn is not None:
            try:
                label.tooltip = str(contribution.tooltip_fn(self._owner))
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("tooltip", contribution.id, exc)
        ui.Spacer(width=6)

    def _show_menu(self, contribution: ViewportToolbarMenu, anchor: Any) -> None:
        if not self._enabled(contribution):
            return
        try:
            import omni.ui as ui

            from ovui_widgets.common.menu import create_flat_menu

            self._destroy_menu(contribution.id)
            self._menu_anchors[contribution.id] = anchor
            menu = create_flat_menu(contribution.label, ui_module=ui)
            self._menus[contribution.id] = menu
            with menu:
                if contribution.build_fn is not None:
                    contribution.build_fn(self._owner, ui)
            x = float(getattr(anchor, "screen_position_x", 0.0) or 0.0)
            y = float(
                (getattr(anchor, "screen_position_y", 0.0) or 0.0)
                + (getattr(anchor, "computed_height", 0.0) or 0.0)
            )
            menu.show_at(x, y)
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("menu", contribution.id, exc)

    def reshow_menu(self, contribution_id: str) -> bool:
        """Rebuild a shown toolbar menu from its most recent anchor."""

        contribution = self._entries.get(contribution_id)
        anchor = self._menu_anchors.get(contribution_id)
        if not isinstance(contribution, ViewportToolbarMenu) or anchor is None:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._show_menu(contribution, anchor)
            return True

        async def _reshow_next_frame() -> None:
            try:
                import omni.ui as ui

                await ui.next_frame()
                next_contribution = self._entries.get(contribution_id)
                next_anchor = self._menu_anchors.get(contribution_id)
                if (
                    isinstance(next_contribution, ViewportToolbarMenu)
                    and next_anchor is anchor
                ):
                    self._show_menu(next_contribution, next_anchor)
            except Exception as exc:
                self._failures[contribution_id] = exc
                self._log("menu_refresh", contribution_id, exc)

        loop.create_task(_reshow_next_frame())
        return True

    def _destroy_menu(self, contribution_id: str) -> None:
        menu = self._menus.pop(contribution_id, None)
        if menu is None:
            return
        try:
            menu.destroy()
        except Exception:
            try:
                menu.hide()
            except Exception:
                pass

    def _apply_anchors(
        self,
        entries: list[_ToolbarContribution],
    ) -> list[_ToolbarContribution]:
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
    def _index_of(entries: list[_ToolbarContribution], contribution_id: str) -> int | None:
        for index, entry in enumerate(entries):
            if entry.id == contribution_id:
                return index
        return None

    def _is_available(self, contribution: _ToolbarContribution) -> bool:
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

    def _enabled(self, contribution: _ToolbarContribution) -> bool:
        if contribution.enabled_fn is None:
            return True
        try:
            return bool(contribution.enabled_fn(self._owner))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("enabled", contribution.id, exc)
            return False

    def _make_callback(self, contribution: ViewportToolbarAction) -> Callable[[], None] | None:
        if contribution.callback is None:
            return None

        def _callback() -> None:
            try:
                contribution.callback(self._owner)
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("trigger", contribution.id, exc)

        return _callback

    def _invoke_lifecycle(self, contribution: _ToolbarContribution, action: str) -> None:
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
            f"[ovui_widgets.viewport.toolbar_hooks] {action} failed for "
            f"{contribution_id}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


__all__ = [
    "ViewportStatusBadge",
    "ViewportToolbarAction",
    "ViewportToolbarHandle",
    "ViewportToolbarMenu",
    "ViewportToolbarRegistry",
]
