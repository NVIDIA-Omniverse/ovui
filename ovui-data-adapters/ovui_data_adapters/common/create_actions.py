# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Backend-neutral contracts for adapter-backed prim creation actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from ovui_data_adapters.common._subscription import SubscriptionProtocol


class _NoopSubscription:
    def cancel(self) -> None:
        return None


class _StableStringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class CreateActionCategory(_StableStringEnum):
    """Stable category identifiers for SRD 6.7 Create menu actions."""

    MESH = "mesh"
    SHAPE = "shape"
    GEOMETRY = "geometry"
    LIGHTS = "lights"
    SENSORS = "sensors"
    CAMERAS = "cameras"
    SCOPES = "scopes"
    TRANSFORMS = "transforms"
    DECALS = "decals"
    PROJECTORS = "projectors"
    RENDER_PRODUCTS = "render_products"
    MATERIALS = "materials"
    OTHER = "other"

    @classmethod
    def ordered(cls) -> tuple["CreateActionCategory", ...]:
        return CREATE_ACTION_CATEGORY_ORDER

    @property
    def default_order(self) -> float:
        return float(_CATEGORY_ORDER_BY_VALUE.get(self.value, 1000.0))

    @property
    def default_label(self) -> str:
        return _CATEGORY_LABEL_BY_VALUE.get(self.value, self.value.replace("_", " ").title())


CREATE_ACTION_CATEGORY_ORDER: tuple[CreateActionCategory, ...] = (
    CreateActionCategory.MESH,
    CreateActionCategory.SHAPE,
    CreateActionCategory.LIGHTS,
    CreateActionCategory.CAMERAS,
    CreateActionCategory.SCOPES,
    CreateActionCategory.TRANSFORMS,
    CreateActionCategory.MATERIALS,
    CreateActionCategory.RENDER_PRODUCTS,
    CreateActionCategory.SENSORS,
    CreateActionCategory.DECALS,
    CreateActionCategory.PROJECTORS,
    CreateActionCategory.OTHER,
)

_CATEGORY_ORDER_BY_VALUE: dict[str, float] = {
    category.value: float(index * 100) for index, category in enumerate(CREATE_ACTION_CATEGORY_ORDER)
}

_CATEGORY_LABEL_BY_VALUE: dict[str, str] = {
    CreateActionCategory.MESH.value: "Mesh",
    CreateActionCategory.SHAPE.value: "Shape",
    CreateActionCategory.GEOMETRY.value: "Geometry",
    CreateActionCategory.LIGHTS.value: "Light",
    CreateActionCategory.SENSORS.value: "Sensors",
    CreateActionCategory.CAMERAS.value: "Camera",
    CreateActionCategory.SCOPES.value: "Scope",
    CreateActionCategory.TRANSFORMS.value: "Xform",
    CreateActionCategory.DECALS.value: "Decals",
    CreateActionCategory.PROJECTORS.value: "Projectors",
    CreateActionCategory.RENDER_PRODUCTS.value: "Render Products",
    CreateActionCategory.MATERIALS.value: "Material",
    CreateActionCategory.OTHER.value: "Other",
}


class CreateActionRequirement(_StableStringEnum):
    """Capability/context requirements that a host can surface before execution."""

    NONE = "none"
    ACTIVE_STAGE = "active_stage"
    WRITABLE_EDIT_TARGET = "writable_edit_target"
    SELECTION = "selection"
    BACKEND_CAPABILITY = "backend_capability"
    UNSUPPORTED = "unsupported"


class CreatePlacementPolicy(_StableStringEnum):
    """Adapter-owned placement hints for a create action."""

    DEFAULT_PARENT = "default_parent"
    REQUESTED_PARENT = "requested_parent"
    SELECTED_PARENT = "selected_parent"
    ROOT = "root"
    MATERIAL_LIBRARY = "material_library"


class CreateSelectionPolicy(_StableStringEnum):
    """Selection behavior requested after a successful create action."""

    SELECT_CREATED = "select_created"
    SELECT_PRIMARY = "select_primary"
    PRESERVE_SELECTION = "preserve_selection"
    CLEAR_SELECTION = "clear_selection"


class CreateBindingPolicy(_StableStringEnum):
    """Optional binding behavior for created assets such as materials."""

    NONE = "none"
    BIND_TO_SELECTION = "bind_to_selection"
    OPTIONAL_BIND_TO_SELECTION = "optional_bind_to_selection"


class CreateActionWarningSeverity(_StableStringEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CreateActionErrorCode(_StableStringEnum):
    UNSUPPORTED = "unsupported"
    DISABLED = "disabled"
    VALIDATION_FAILED = "validation_failed"
    CREATE_FAILED = "create_failed"
    NO_ACTIVE_STAGE = "no_active_stage"


def _string_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return "" if value is None else str(value)


def _string_tuple(values: Iterable[Any] | Any | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        return (_string_value(values),)
    try:
        return tuple(_string_value(value) for value in values)
    except TypeError:
        return (_string_value(values),)


def _mapping_proxy(values: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(values or {}))


def _enum_value(enum_type: type[_StableStringEnum], value: Any) -> _StableStringEnum:
    if isinstance(value, enum_type):
        return value
    return enum_type(_string_value(value))


def _requirement_tuple(values: Iterable[Any] | Any | None) -> tuple[CreateActionRequirement, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, CreateActionRequirement)):
        values = (values,)
    return tuple(_enum_value(CreateActionRequirement, value) for value in values)


def _warning_tuple(values: Iterable["CreateActionWarning"] | None) -> tuple["CreateActionWarning", ...]:
    return tuple(values or ())


def _category_id(value: str | CreateActionCategory) -> str:
    return _string_value(value)


def _category_default_order(category_id: str) -> float:
    return float(_CATEGORY_ORDER_BY_VALUE.get(category_id, 1000.0))


def _category_default_label(category_id: str) -> str:
    return _CATEGORY_LABEL_BY_VALUE.get(category_id, category_id.replace("_", " ").title())


@dataclass(frozen=True)
class CreateActionWarning:
    code: str
    message: str
    severity: CreateActionWarningSeverity = CreateActionWarningSeverity.WARNING
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = _string_value(self.code)
        if not code:
            raise ValueError("CreateActionWarning.code must be non-empty")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", _string_value(self.message))
        object.__setattr__(
            self,
            "severity",
            _enum_value(CreateActionWarningSeverity, self.severity),
        )
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))


@dataclass(frozen=True)
class CreateActionCategoryDescriptor:
    category_id: str | CreateActionCategory
    label: str = ""
    order: float | None = None
    collapsed_by_default: bool = False
    enabled: bool = True
    disabled_reason: str = ""
    warnings: tuple[CreateActionWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        category_id = _category_id(self.category_id)
        if not category_id:
            raise ValueError("CreateActionCategoryDescriptor.category_id must be non-empty")
        order = self.order
        if order is None:
            order = _category_default_order(category_id)
        object.__setattr__(self, "category_id", category_id)
        object.__setattr__(self, "label", self.label or _category_default_label(category_id))
        object.__setattr__(self, "order", float(order))
        object.__setattr__(self, "collapsed_by_default", bool(self.collapsed_by_default))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", _string_value(self.disabled_reason))
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_available(self) -> bool:
        return self.enabled and not self.disabled_reason


@dataclass(frozen=True)
class CreateActionDescriptor:
    action_id: str
    label: str = ""
    category_id: str | CreateActionCategory = CreateActionCategory.MESH
    target_prim_type: str = ""
    prim_kind: str = ""
    description: str = ""
    icon_key: str = ""
    order: float = 1000.0
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    requirements: tuple[CreateActionRequirement, ...] = field(default_factory=tuple)
    placement_policy: CreatePlacementPolicy = CreatePlacementPolicy.DEFAULT_PARENT
    selection_policy: CreateSelectionPolicy = CreateSelectionPolicy.SELECT_CREATED
    binding_policy: CreateBindingPolicy = CreateBindingPolicy.NONE
    default_parent_path: str = ""
    default_name: str = ""
    option_schema: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    disabled_reason: str = ""
    warnings: tuple[CreateActionWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        action_id = _string_value(self.action_id)
        if not action_id:
            raise ValueError("CreateActionDescriptor.action_id must be non-empty")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "label", self.label or action_id)
        object.__setattr__(self, "category_id", _category_id(self.category_id))
        object.__setattr__(self, "target_prim_type", _string_value(self.target_prim_type))
        object.__setattr__(self, "prim_kind", _string_value(self.prim_kind))
        object.__setattr__(self, "description", _string_value(self.description))
        object.__setattr__(self, "icon_key", _string_value(self.icon_key))
        object.__setattr__(self, "order", float(self.order))
        object.__setattr__(self, "capabilities", _string_tuple(self.capabilities))
        object.__setattr__(self, "requirements", _requirement_tuple(self.requirements))
        object.__setattr__(
            self,
            "placement_policy",
            _enum_value(CreatePlacementPolicy, self.placement_policy),
        )
        object.__setattr__(
            self,
            "selection_policy",
            _enum_value(CreateSelectionPolicy, self.selection_policy),
        )
        object.__setattr__(
            self,
            "binding_policy",
            _enum_value(CreateBindingPolicy, self.binding_policy),
        )
        object.__setattr__(self, "default_parent_path", _string_value(self.default_parent_path))
        object.__setattr__(self, "default_name", _string_value(self.default_name))
        object.__setattr__(self, "option_schema", _mapping_proxy(self.option_schema))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", _string_value(self.disabled_reason))
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_available(self) -> bool:
        return self.enabled and not self.disabled_reason

    @property
    def category_order(self) -> float:
        return _category_default_order(self.category_id)

    @property
    def can_bind(self) -> bool:
        return self.binding_policy != CreateBindingPolicy.NONE


@dataclass(frozen=True)
class CreateActionCatalog:
    categories: tuple[CreateActionCategoryDescriptor, ...] = field(default_factory=tuple)
    actions: tuple[CreateActionDescriptor, ...] = field(default_factory=tuple)
    active_stage_id: str = ""
    edit_target_id: str = ""
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    revision: str = ""
    warnings: tuple[CreateActionWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "categories", tuple(self.categories or ()))
        object.__setattr__(self, "actions", tuple(self.actions or ()))
        object.__setattr__(self, "active_stage_id", _string_value(self.active_stage_id))
        object.__setattr__(self, "edit_target_id", _string_value(self.edit_target_id))
        object.__setattr__(self, "selection_paths", _string_tuple(self.selection_paths))
        object.__setattr__(self, "revision", _string_value(self.revision))
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_empty(self) -> bool:
        return not self.actions

    def category(self, category_id: str | CreateActionCategory) -> CreateActionCategoryDescriptor | None:
        wanted = _category_id(category_id)
        return next((category for category in self.categories if category.category_id == wanted), None)

    def action(self, action_id: str) -> CreateActionDescriptor | None:
        wanted = _string_value(action_id)
        return next((action for action in self.actions if action.action_id == wanted), None)

    def actions_for_category(
        self, category_id: str | CreateActionCategory
    ) -> tuple[CreateActionDescriptor, ...]:
        wanted = _category_id(category_id)
        actions = (action for action in self.actions if action.category_id == wanted)
        return tuple(sorted(actions, key=lambda action: (action.order, action.action_id)))

    @property
    def available_actions(self) -> tuple[CreateActionDescriptor, ...]:
        return tuple(action for action in self.actions if action.is_available)


@dataclass(frozen=True)
class CreateRequest:
    action_id: str
    requested_parent_path: str = ""
    requested_name: str = ""
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    placement_hint: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        action_id = _string_value(self.action_id)
        if not action_id:
            raise ValueError("CreateRequest.action_id must be non-empty")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "requested_parent_path", _string_value(self.requested_parent_path))
        object.__setattr__(self, "requested_name", _string_value(self.requested_name))
        object.__setattr__(self, "selection_paths", _string_tuple(self.selection_paths))
        object.__setattr__(self, "placement_hint", _string_value(self.placement_hint))
        object.__setattr__(self, "options", _mapping_proxy(self.options))
        object.__setattr__(self, "correlation_id", _string_value(self.correlation_id))


@dataclass(frozen=True)
class CreateResult:
    accepted: bool
    created_paths: tuple[str, ...] = field(default_factory=tuple)
    primary_path: str = ""
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    focus_path: str = ""
    binding_applied: bool = False
    message: str = ""
    error_code: str = ""
    warnings: tuple[CreateActionWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        created_paths = _string_tuple(self.created_paths)
        primary_path = _string_value(self.primary_path)
        if self.accepted and not primary_path and created_paths:
            primary_path = created_paths[0]
        selection_paths = _string_tuple(self.selection_paths)
        focus_path = _string_value(self.focus_path)
        error_code = _string_value(self.error_code)
        if self.accepted and error_code:
            raise ValueError("accepted CreateResult cannot carry an error_code")
        if not self.accepted:
            has_mutation = bool(created_paths or primary_path or selection_paths or focus_path or self.binding_applied)
            if has_mutation:
                raise ValueError("rejected CreateResult must not report mutations")
            if not error_code:
                error_code = CreateActionErrorCode.CREATE_FAILED.value
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "created_paths", created_paths)
        object.__setattr__(self, "primary_path", primary_path)
        object.__setattr__(self, "selection_paths", selection_paths)
        object.__setattr__(self, "focus_path", focus_path)
        object.__setattr__(self, "binding_applied", bool(self.binding_applied))
        object.__setattr__(self, "message", _string_value(self.message))
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @classmethod
    def accepted_result(
        cls,
        *,
        created_paths: Iterable[str],
        primary_path: str = "",
        selection_paths: Iterable[str] | None = None,
        focus_path: str = "",
        binding_applied: bool = False,
        message: str = "",
        warnings: Iterable[CreateActionWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreateResult":
        created_paths_tuple = _string_tuple(created_paths)
        primary = primary_path or (created_paths_tuple[0] if created_paths_tuple else "")
        if selection_paths is None:
            selection_paths = (primary,) if primary else ()
        return cls(
            accepted=True,
            created_paths=created_paths_tuple,
            primary_path=primary,
            selection_paths=_string_tuple(selection_paths),
            focus_path=focus_path,
            binding_applied=binding_applied,
            message=message,
            warnings=tuple(warnings or ()),
            metadata=metadata or {},
        )

    @classmethod
    def rejected_result(
        cls,
        *,
        message: str = "",
        error_code: str | CreateActionErrorCode = CreateActionErrorCode.CREATE_FAILED,
        warnings: Iterable[CreateActionWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreateResult":
        return cls(
            accepted=False,
            message=message,
            error_code=_string_value(error_code),
            warnings=tuple(warnings or ()),
            metadata=metadata or {},
        )


class CreateActionsAdapter:
    """Default no-support surface for adapter-backed create actions."""

    def list_create_actions(
        self,
        *,
        selection_paths: Iterable[str] | None = None,
    ) -> CreateActionCatalog:
        return CreateActionCatalog(selection_paths=tuple(selection_paths or ()))

    def create_prim(self, request: CreateRequest) -> CreateResult:
        _ = request
        return CreateResult.rejected_result(
            message="Create actions are not supported by this adapter.",
            error_code=CreateActionErrorCode.UNSUPPORTED,
            warnings=(
                CreateActionWarning(
                    code=CreateActionErrorCode.UNSUPPORTED.value,
                    message="Create actions are not supported by this adapter.",
                    severity=CreateActionWarningSeverity.ERROR,
                ),
            ),
        )

    def subscribe_create_actions_changes(
        self,
        callback: Callable[[], None],
    ) -> SubscriptionProtocol:
        _ = callback
        return _NoopSubscription()


__all__ = [
    "CREATE_ACTION_CATEGORY_ORDER",
    "CreateActionCatalog",
    "CreateActionCategory",
    "CreateActionCategoryDescriptor",
    "CreateActionDescriptor",
    "CreateActionErrorCode",
    "CreateActionRequirement",
    "CreateActionWarning",
    "CreateActionWarningSeverity",
    "CreateActionsAdapter",
    "CreateBindingPolicy",
    "CreatePlacementPolicy",
    "CreateRequest",
    "CreateResult",
    "CreateSelectionPolicy",
]
