# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Optional contribution registry for USD Viewer menus."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Sequence

MenuKind = Literal["item", "menu", "separator", "custom"]
MenuCallback = Callable[[Any], None]
MenuBuildCallback = Callable[[Any, Any], None]
MenuPredicate = Callable[[Any], bool]
MenuContributionProvider = Callable[[Any], Iterable["AppMenuContribution"]]


def normalize_menu_path(path: str | Sequence[str] | None) -> tuple[str, ...]:
    """Normalize menu paths from ``"File/Recent"`` or sequences."""
    if path is None:
        return ()
    if isinstance(path, str):
        return tuple(part.strip() for part in path.split("/") if part.strip())
    return tuple(str(part).strip() for part in path if str(part).strip())


@dataclass(frozen=True)
class AppMenuContribution:
    """Declarative menu row supplied by an optional component."""

    id: str
    label: str = ""
    parent_path: str | Sequence[str] = ()
    kind: MenuKind = "item"
    order: float = 1000.0
    before: str | None = None
    after: str | None = None
    capabilities: Iterable[str] = field(default_factory=tuple)
    enabled: bool = True
    checkable: bool = False
    checked: bool = False
    hotkey_text: str = ""
    tooltip: str = ""
    disabled_reason: str = ""
    callback: MenuCallback | None = None
    build_fn: MenuBuildCallback | None = None
    visible_fn: MenuPredicate | None = None
    enabled_fn: MenuPredicate | None = None
    checked_fn: MenuPredicate | None = None
    on_add: MenuCallback | None = None
    on_remove: MenuCallback | None = None
    widget_name: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("AppMenuContribution.id is required")
        if self.kind != "separator" and not self.label:
            raise ValueError("AppMenuContribution.label is required")
        object.__setattr__(self, "parent_path", normalize_menu_path(self.parent_path))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "tooltip", str(self.tooltip or ""))
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))
        if self.widget_name is None:
            safe_id = self.id.replace("/", "_").replace(".", "_")
            object.__setattr__(self, "widget_name", f"app_menu_{safe_id}")


@dataclass(frozen=True)
class AppMenuContributionProvider:
    """Dynamic menu contribution provider supplied by an optional component."""

    id: str
    contributions_fn: MenuContributionProvider
    capabilities: Iterable[str] = field(default_factory=tuple)
    visible_fn: MenuPredicate | None = None
    on_add: MenuCallback | None = None
    on_remove: MenuCallback | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("AppMenuContributionProvider.id is required")
        if not callable(self.contributions_fn):
            raise ValueError("AppMenuContributionProvider.contributions_fn must be callable")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


@dataclass(frozen=True)
class AppMenuRoot:
    """Top-level menu contributed by child rows."""

    label: str
    path: tuple[str, ...]
    order: float


@dataclass(frozen=True)
class _MenuNode:
    id: str
    label: str
    kind: MenuKind
    order: float
    contribution: AppMenuContribution | None = None
    before: str | None = None
    after: str | None = None


@dataclass(frozen=True)
class _BuiltMenuWidget:
    id: str
    label: str
    parent_path: tuple[str, ...]
    kind: str
    enabled: bool
    widget: Any


class AppMenuHandle:
    """Removable handle returned from ``AppMenuRegistry.add``."""

    def __init__(self, registry: "AppMenuRegistry", contribution_id: str) -> None:
        self._registry = registry
        self._contribution_id = contribution_id

    @property
    def id(self) -> str:
        return self._contribution_id

    def remove(self) -> bool:
        return self._registry.remove(self._contribution_id)


class AppMenuRegistry:
    """Component-owned menu contribution registry."""

    def __init__(self, app: Any, *, capabilities: Iterable[str] = ()) -> None:
        self._app = app
        self._entries: dict[str, AppMenuContribution] = {}
        self._providers: dict[str, AppMenuContributionProvider] = {}
        self._capabilities: set[str] = set(capabilities)
        self._failures: dict[str, BaseException] = {}
        self._built_widgets: dict[str, _BuiltMenuWidget] = {}

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._capabilities)

    @property
    def failures(self) -> dict[str, BaseException]:
        return dict(self._failures)

    def built_item_geometry(self) -> tuple[dict[str, Any], ...]:
        """Return immutable geometry snapshots for currently built menu rows."""

        rows: list[dict[str, Any]] = []
        for record in self._built_widgets.values():
            widget = record.widget
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
                    "id": record.id,
                    "label": record.label,
                    "parent_path": record.parent_path,
                    "kind": record.kind,
                    "enabled": record.enabled,
                    "visible": bool(getattr(widget, "visible", True)),
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

    def add(self, contribution: AppMenuContribution) -> AppMenuHandle:
        """Register a contribution once and return its removal handle."""
        if contribution.id in self._entries or contribution.id in self._providers:
            return AppMenuHandle(self, contribution.id)
        self._entries[contribution.id] = contribution
        self._invoke_lifecycle(contribution, "add")
        return AppMenuHandle(self, contribution.id)

    def add_provider(self, provider: AppMenuContributionProvider) -> AppMenuHandle:
        """Register a dynamic contribution provider once."""
        if provider.id in self._providers or provider.id in self._entries:
            return AppMenuHandle(self, provider.id)
        self._providers[provider.id] = provider
        self._invoke_provider_lifecycle(provider, "add")
        return AppMenuHandle(self, provider.id)

    def remove(self, contribution_id: str) -> bool:
        contribution = self._entries.pop(contribution_id, None)
        if contribution is not None:
            self._built_widgets.pop(contribution_id, None)
            self._invoke_lifecycle(contribution, "remove")
            return True

        provider = self._providers.pop(contribution_id, None)
        if provider is not None:
            # Dynamic provider entry IDs need not share the provider prefix.
            # Clear the read-only cache; the next menu build repopulates it.
            self._built_widgets.clear()
            self._invoke_provider_lifecycle(provider, "remove")
            return True
        return False

    def clear(self) -> None:
        for contribution_id in reversed(tuple(self._entries)):
            self.remove(contribution_id)
        for provider_id in reversed(tuple(self._providers)):
            self.remove(provider_id)
        self._built_widgets.clear()

    def iter_contributions(
        self,
        parent_path: str | Sequence[str],
    ) -> tuple[AppMenuContribution, ...]:
        path = normalize_menu_path(parent_path)
        return tuple(
            entry
            for entry in self._available_entries()
            if entry.parent_path == path and self._is_available(entry)
        )

    def iter_top_level_menus(
        self,
        *,
        exclude: Iterable[str] = (),
    ) -> tuple[AppMenuRoot, ...]:
        excluded = set(exclude)
        roots: dict[str, float] = {}
        for entry in self._available_entries():
            path = entry.parent_path
            if path:
                label = path[0]
                order = min(float(entry.order), roots.get(label, float(entry.order)))
            else:
                label = entry.label
                order = float(entry.order)
            if label and label not in excluded:
                roots[label] = order
        return tuple(
            AppMenuRoot(label=label, path=(label,), order=order)
            for label, order in sorted(roots.items(), key=lambda item: (item[1], item[0]))
        )

    def build_path(
        self,
        parent_path: str | Sequence[str],
        ui_module: Any | None = None,
    ) -> None:
        if ui_module is None:
            import omni.ui as ui
        else:
            ui = ui_module
        path = normalize_menu_path(parent_path)
        self._built_widgets = {
            item_id: record
            for item_id, record in self._built_widgets.items()
            if record.parent_path != path
        }
        for node in self._iter_nodes(path):
            try:
                self._build_node(node, path, ui)
            except Exception as exc:
                self._failures[node.id] = exc
                self._log("build", node.id, exc)

    def _build_node(self, node: _MenuNode, path: tuple[str, ...], ui: Any) -> None:
        contribution = node.contribution
        if node.kind == "separator":
            ui.Separator()
            return
        if node.kind == "menu":
            menu = ui.Menu(node.label)
            self._remember_built_widget(node, path, menu, enabled=True)
            with menu:
                if contribution is not None and contribution.build_fn is not None:
                    contribution.build_fn(self._app, ui)
                self.build_path(path + (node.label,), ui)
            return
        if node.kind == "custom":
            if contribution is not None and contribution.build_fn is not None:
                contribution.build_fn(self._app, ui)
            return
        if contribution is None:
            return
        enabled = self._enabled(contribution)
        kwargs: dict[str, Any] = {
            "enabled": enabled,
            "name": contribution.widget_name,
            "triggered_fn": self._make_callback(contribution),
        }
        if contribution.hotkey_text:
            kwargs["hotkey_text"] = contribution.hotkey_text
        if contribution.checkable:
            kwargs["checkable"] = True
            kwargs["checked"] = self._checked(contribution)
        item = ui.MenuItem(contribution.label, **kwargs)
        self._remember_built_widget(node, path, item, enabled=enabled)
        tooltip = self._tooltip(contribution, enabled)
        if tooltip:
            self._set_tooltip(item, tooltip)

    def _remember_built_widget(
        self,
        node: _MenuNode,
        parent_path: tuple[str, ...],
        widget: Any,
        *,
        enabled: bool,
    ) -> None:
        self._built_widgets[node.id] = _BuiltMenuWidget(
            id=node.id,
            label=node.label,
            parent_path=parent_path,
            kind=node.kind,
            enabled=bool(enabled),
            widget=widget,
        )

    def _iter_nodes(self, path: tuple[str, ...]) -> tuple[_MenuNode, ...]:
        nodes: list[_MenuNode] = []
        explicit_menus: set[str] = set()
        entries = self._available_entries()
        for entry in entries:
            if entry.parent_path == path:
                nodes.append(
                    _MenuNode(
                        id=entry.id,
                        label=entry.label,
                        kind=entry.kind,
                        order=float(entry.order),
                        contribution=entry,
                        before=entry.before,
                        after=entry.after,
                    )
                )
                if entry.kind == "menu":
                    explicit_menus.add(entry.label)

        implicit: dict[str, float] = {}
        prefix_len = len(path)
        for entry in entries:
            parent = entry.parent_path
            if len(parent) <= prefix_len or parent[:prefix_len] != path:
                continue
            label = parent[prefix_len]
            if label in explicit_menus:
                continue
            implicit[label] = min(implicit.get(label, float(entry.order)), float(entry.order))
        for label, order in implicit.items():
            nodes.append(
                _MenuNode(
                    id="/".join(path + (label,)),
                    label=label,
                    kind="menu",
                    order=order,
                )
            )
        return tuple(self._apply_anchors(nodes))

    def _apply_anchors(self, nodes: list[_MenuNode]) -> list[_MenuNode]:
        ordered = sorted(nodes, key=lambda node: (node.order, node.id))
        for node in tuple(ordered):
            target_id = node.before or node.after
            if not target_id:
                continue
            current_index = self._index_of(ordered, node.id)
            target_index = self._index_of(ordered, target_id)
            if current_index is None or target_index is None:
                continue
            item = ordered.pop(current_index)
            if current_index < target_index:
                target_index -= 1
            insert_at = target_index if node.before else target_index + 1
            ordered.insert(insert_at, item)
        return ordered

    def _available_entries(self) -> tuple[AppMenuContribution, ...]:
        entries: list[AppMenuContribution] = []
        for entry in self._entries.values():
            if self._is_available(entry):
                entries.append(entry)
        for provider in self._providers.values():
            if not self._provider_available(provider):
                continue
            for entry in self._provider_entries(provider):
                if self._is_available(entry):
                    entries.append(entry)
        return tuple(entries)

    def _provider_entries(
        self,
        provider: AppMenuContributionProvider,
    ) -> tuple[AppMenuContribution, ...]:
        try:
            raw_entries = provider.contributions_fn(self._app)
        except Exception as exc:
            self._failures[provider.id] = exc
            self._log("provider", provider.id, exc)
            return ()
        if raw_entries is None:
            return ()

        entries: list[AppMenuContribution] = []
        try:
            iterator = iter(raw_entries)
        except Exception as exc:
            self._failures[provider.id] = exc
            self._log("provider", provider.id, exc)
            return ()
        index = 0
        while True:
            try:
                entry = next(iterator)
            except StopIteration:
                break
            except Exception as exc:
                self._failures[provider.id] = exc
                self._log("provider", provider.id, exc)
                break
            if not isinstance(entry, AppMenuContribution):
                failure_id = f"{provider.id}:{index}"
                exc = TypeError(
                    "AppMenuContributionProvider entries must be AppMenuContribution"
                )
                self._failures[failure_id] = exc
                self._log("provider", failure_id, exc)
            else:
                entries.append(entry)
            index += 1
        return tuple(entries)

    def _provider_available(self, provider: AppMenuContributionProvider) -> bool:
        if any(capability not in self._capabilities for capability in provider.capabilities):
            return False
        if provider.visible_fn is None:
            return True
        try:
            return bool(provider.visible_fn(self._app))
        except Exception as exc:
            self._failures[provider.id] = exc
            self._log("visible", provider.id, exc)
            return False

    @staticmethod
    def _index_of(nodes: list[_MenuNode], node_id: str) -> int | None:
        for index, node in enumerate(nodes):
            if node.id == node_id:
                return index
        return None

    def _is_available(self, contribution: AppMenuContribution) -> bool:
        if any(capability not in self._capabilities for capability in contribution.capabilities):
            return False
        if contribution.visible_fn is None:
            return True
        try:
            return bool(contribution.visible_fn(self._app))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("visible", contribution.id, exc)
            return False

    def _enabled(self, contribution: AppMenuContribution) -> bool:
        if not contribution.enabled:
            return False
        if contribution.enabled_fn is None:
            return True
        try:
            return bool(contribution.enabled_fn(self._app))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("enabled", contribution.id, exc)
            return False

    def _checked(self, contribution: AppMenuContribution) -> bool:
        if contribution.checked_fn is None:
            return bool(contribution.checked)
        try:
            return bool(contribution.checked_fn(self._app))
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log("checked", contribution.id, exc)
            return False

    @staticmethod
    def _tooltip(contribution: AppMenuContribution, enabled: bool) -> str:
        if not enabled and contribution.disabled_reason:
            return contribution.disabled_reason
        return contribution.tooltip

    @staticmethod
    def _set_tooltip(item: Any, tooltip: str) -> None:
        if item is None:
            return
        try:
            item.tooltip = tooltip
        except Exception:
            return

    def _make_callback(self, contribution: AppMenuContribution) -> Callable[[], None] | None:
        if contribution.callback is None:
            return None

        def _callback() -> None:
            try:
                contribution.callback(self._app)
            except Exception as exc:
                self._failures[contribution.id] = exc
                self._log("trigger", contribution.id, exc)

        return _callback

    def _invoke_lifecycle(self, contribution: AppMenuContribution, action: str) -> None:
        fn = contribution.on_add if action == "add" else contribution.on_remove
        if fn is None:
            return
        try:
            fn(self._app)
        except Exception as exc:
            self._failures[contribution.id] = exc
            self._log(action, contribution.id, exc)

    def _invoke_provider_lifecycle(
        self,
        provider: AppMenuContributionProvider,
        action: str,
    ) -> None:
        fn = provider.on_add if action == "add" else provider.on_remove
        if fn is None:
            return
        try:
            fn(self._app)
        except Exception as exc:
            self._failures[provider.id] = exc
            self._log(action, provider.id, exc)

    @staticmethod
    def _log(action: str, contribution_id: str, exc: BaseException) -> None:
        print(
            f"[ovui_widgets.app.menu_hooks] {action} failed for {contribution_id}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


__all__ = [
    "AppMenuContribution",
    "AppMenuContributionProvider",
    "AppMenuHandle",
    "AppMenuRegistry",
    "AppMenuRoot",
    "normalize_menu_path",
]
