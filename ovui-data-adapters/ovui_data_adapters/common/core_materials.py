# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Backend-neutral contracts for adapter-backed core material creation."""

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


class CoreMaterialFamily(_StableStringEnum):
    """Stable material-family identifiers surfaced by material adapters."""

    USD = "usd"
    MATERIALX = "materialx"
    MDL = "mdl"
    LIBRARY = "library"
    CUSTOM = "custom"
    OTHER = "other"


class CoreMaterialKind(_StableStringEnum):
    """Stable IDs for core material kinds named in SRD 6.8."""

    USD_PREVIEW_SURFACE = "usd_preview_surface"
    USD_PREVIEW_SURFACE_TEXTURE = "usd_preview_surface_texture"
    OPENPBR_BASE = "openpbr_base"
    OPENPBR = "openpbr"
    STANDARD_SURFACE = "standard_surface"
    MATERIALX_REFERENCE = "materialx_reference"
    MDL_FILE = "mdl_file"
    OMNI_SURFACE = "omni_surface"
    OMNI_GLASS = "omni_glass"
    OMNI_PBR = "omni_pbr"
    LIBRARY_REFERENCE = "library_reference"
    OTHER = "other"


class CoreMaterialRequirement(_StableStringEnum):
    """Capability/context requirements for material catalog entries."""

    NONE = "none"
    ACTIVE_STAGE = "active_stage"
    WRITABLE_EDIT_TARGET = "writable_edit_target"
    MATERIAL_SCHEMA = "material_schema"
    BINDABLE_SELECTION = "bindable_selection"
    BACKEND_CAPABILITY = "backend_capability"
    EXTERNAL_REFERENCE = "external_reference"
    UNSUPPORTED = "unsupported"


class CoreMaterialBindingPolicy(_StableStringEnum):
    """Adapter-declared bind behavior for a material entry."""

    NONE = "none"
    OPTIONAL_BIND_TO_SELECTION = "optional_bind_to_selection"
    BIND_TO_SELECTION = "bind_to_selection"


class CoreMaterialWarningSeverity(_StableStringEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CoreMaterialErrorCode(_StableStringEnum):
    UNSUPPORTED = "unsupported"
    DISABLED = "disabled"
    VALIDATION_FAILED = "validation_failed"
    CREATE_FAILED = "create_failed"
    BIND_FAILED = "bind_failed"
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


def _requirement_tuple(values: Iterable[Any] | Any | None) -> tuple[CoreMaterialRequirement, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, CoreMaterialRequirement)):
        values = (values,)
    return tuple(_enum_value(CoreMaterialRequirement, value) for value in values)


def _warning_tuple(
    values: Iterable["CoreMaterialWarning"] | None,
) -> tuple["CoreMaterialWarning", ...]:
    return tuple(values or ())


@dataclass(frozen=True)
class CoreMaterialWarning:
    code: str
    message: str
    severity: CoreMaterialWarningSeverity = CoreMaterialWarningSeverity.WARNING
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = _string_value(self.code)
        if not code:
            raise ValueError("CoreMaterialWarning.code must be non-empty")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", _string_value(self.message))
        object.__setattr__(
            self,
            "severity",
            _enum_value(CoreMaterialWarningSeverity, self.severity),
        )
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))


@dataclass(frozen=True)
class CoreMaterialGroupDescriptor:
    group_id: str
    label: str = ""
    parent_group_id: str = ""
    order: float = 1000.0
    collapsed_by_default: bool = False
    enabled: bool = True
    disabled_reason: str = ""
    warnings: tuple[CoreMaterialWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        group_id = _string_value(self.group_id)
        if not group_id:
            raise ValueError("CoreMaterialGroupDescriptor.group_id must be non-empty")
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "label", self.label or group_id.replace("_", " ").title())
        object.__setattr__(self, "parent_group_id", _string_value(self.parent_group_id))
        object.__setattr__(self, "order", float(self.order))
        object.__setattr__(self, "collapsed_by_default", bool(self.collapsed_by_default))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", _string_value(self.disabled_reason))
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_available(self) -> bool:
        return self.enabled and not self.disabled_reason


@dataclass(frozen=True)
class CoreMaterialDescriptor:
    material_id: str
    label: str = ""
    group_id: str = ""
    submenu_path: tuple[str, ...] = field(default_factory=tuple)
    family: CoreMaterialFamily = CoreMaterialFamily.USD
    kind: CoreMaterialKind = CoreMaterialKind.OTHER
    shader_type: str = ""
    description: str = ""
    icon_key: str = ""
    swatch: tuple[float, float, float, float] | None = None
    order: float = 1000.0
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    requirements: tuple[CoreMaterialRequirement, ...] = field(default_factory=tuple)
    default_scope_path: str = ""
    default_name: str = ""
    binding_policy: CoreMaterialBindingPolicy = CoreMaterialBindingPolicy.NONE
    create_supported: bool = True
    bind_supported: bool = False
    enabled: bool = True
    disabled_reason: str = ""
    warnings: tuple[CoreMaterialWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        material_id = _string_value(self.material_id)
        if not material_id:
            raise ValueError("CoreMaterialDescriptor.material_id must be non-empty")
        swatch = self.swatch
        if swatch is not None:
            swatch_tuple = tuple(float(channel) for channel in swatch)
            if len(swatch_tuple) != 4:
                raise ValueError("CoreMaterialDescriptor.swatch must contain four channels")
            swatch = swatch_tuple
        object.__setattr__(self, "material_id", material_id)
        object.__setattr__(self, "label", self.label or material_id.replace("_", " ").title())
        object.__setattr__(self, "group_id", _string_value(self.group_id))
        object.__setattr__(self, "submenu_path", _string_tuple(self.submenu_path))
        object.__setattr__(self, "family", _enum_value(CoreMaterialFamily, self.family))
        object.__setattr__(self, "kind", _enum_value(CoreMaterialKind, self.kind))
        object.__setattr__(self, "shader_type", _string_value(self.shader_type))
        object.__setattr__(self, "description", _string_value(self.description))
        object.__setattr__(self, "icon_key", _string_value(self.icon_key))
        object.__setattr__(self, "swatch", swatch)
        object.__setattr__(self, "order", float(self.order))
        object.__setattr__(self, "capabilities", _string_tuple(self.capabilities))
        object.__setattr__(self, "requirements", _requirement_tuple(self.requirements))
        object.__setattr__(self, "default_scope_path", _string_value(self.default_scope_path))
        object.__setattr__(self, "default_name", _string_value(self.default_name))
        object.__setattr__(
            self,
            "binding_policy",
            _enum_value(CoreMaterialBindingPolicy, self.binding_policy),
        )
        object.__setattr__(self, "create_supported", bool(self.create_supported))
        object.__setattr__(self, "bind_supported", bool(self.bind_supported))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", _string_value(self.disabled_reason))
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_available(self) -> bool:
        return self.enabled and self.create_supported and not self.disabled_reason

    @property
    def can_bind(self) -> bool:
        return self.bind_supported and self.binding_policy != CoreMaterialBindingPolicy.NONE


@dataclass(frozen=True)
class CoreMaterialCatalog:
    groups: tuple[CoreMaterialGroupDescriptor, ...] = field(default_factory=tuple)
    materials: tuple[CoreMaterialDescriptor, ...] = field(default_factory=tuple)
    active_stage_id: str = ""
    edit_target_id: str = ""
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    bindable_selection_paths: tuple[str, ...] = field(default_factory=tuple)
    revision: str = ""
    warnings: tuple[CoreMaterialWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "groups", tuple(self.groups or ()))
        object.__setattr__(self, "materials", tuple(self.materials or ()))
        object.__setattr__(self, "active_stage_id", _string_value(self.active_stage_id))
        object.__setattr__(self, "edit_target_id", _string_value(self.edit_target_id))
        object.__setattr__(self, "selection_paths", _string_tuple(self.selection_paths))
        object.__setattr__(
            self,
            "bindable_selection_paths",
            _string_tuple(self.bindable_selection_paths),
        )
        object.__setattr__(self, "revision", _string_value(self.revision))
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_empty(self) -> bool:
        return not self.materials

    def group(self, group_id: str) -> CoreMaterialGroupDescriptor | None:
        wanted = _string_value(group_id)
        return next((group for group in self.groups if group.group_id == wanted), None)

    def material(self, material_id: str) -> CoreMaterialDescriptor | None:
        wanted = _string_value(material_id)
        return next((material for material in self.materials if material.material_id == wanted), None)

    def materials_for_group(self, group_id: str) -> tuple[CoreMaterialDescriptor, ...]:
        wanted = _string_value(group_id)
        materials = (material for material in self.materials if material.group_id == wanted)
        return tuple(sorted(materials, key=lambda material: (material.order, material.material_id)))

    @property
    def available_materials(self) -> tuple[CoreMaterialDescriptor, ...]:
        return tuple(material for material in self.materials if material.is_available)


@dataclass(frozen=True)
class CreateMaterialRequest:
    material_id: str
    requested_scope_path: str = ""
    requested_name: str = ""
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    bind_to_selection: bool = False
    options: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        material_id = _string_value(self.material_id)
        if not material_id:
            raise ValueError("CreateMaterialRequest.material_id must be non-empty")
        object.__setattr__(self, "material_id", material_id)
        object.__setattr__(self, "requested_scope_path", _string_value(self.requested_scope_path))
        object.__setattr__(self, "requested_name", _string_value(self.requested_name))
        object.__setattr__(self, "selection_paths", _string_tuple(self.selection_paths))
        object.__setattr__(self, "bind_to_selection", bool(self.bind_to_selection))
        object.__setattr__(self, "options", _mapping_proxy(self.options))
        object.__setattr__(self, "correlation_id", _string_value(self.correlation_id))


@dataclass(frozen=True)
class BindMaterialRequest:
    material_path: str
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    binding_strength: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        material_path = _string_value(self.material_path)
        if not material_path:
            raise ValueError("BindMaterialRequest.material_path must be non-empty")
        object.__setattr__(self, "material_path", material_path)
        object.__setattr__(self, "selection_paths", _string_tuple(self.selection_paths))
        object.__setattr__(self, "binding_strength", _string_value(self.binding_strength))
        object.__setattr__(self, "options", _mapping_proxy(self.options))
        object.__setattr__(self, "correlation_id", _string_value(self.correlation_id))


@dataclass(frozen=True)
class CreateMaterialResult:
    accepted: bool
    created_material_path: str = ""
    created_paths: tuple[str, ...] = field(default_factory=tuple)
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    focus_path: str = ""
    message: str = ""
    error_code: str = ""
    warnings: tuple[CoreMaterialWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        created_material_path = _string_value(self.created_material_path)
        created_paths = _string_tuple(self.created_paths)
        if self.accepted and not created_material_path and created_paths:
            created_material_path = created_paths[0]
        selection_paths = _string_tuple(self.selection_paths)
        focus_path = _string_value(self.focus_path)
        error_code = _string_value(self.error_code)
        if self.accepted and error_code:
            raise ValueError("accepted CreateMaterialResult cannot carry an error_code")
        if not self.accepted:
            has_mutation = bool(created_material_path or created_paths or selection_paths or focus_path)
            if has_mutation:
                raise ValueError("rejected CreateMaterialResult must not report mutations")
            if not error_code:
                error_code = CoreMaterialErrorCode.CREATE_FAILED.value
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "created_material_path", created_material_path)
        object.__setattr__(self, "created_paths", created_paths)
        object.__setattr__(self, "selection_paths", selection_paths)
        object.__setattr__(self, "focus_path", focus_path)
        object.__setattr__(self, "message", _string_value(self.message))
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @classmethod
    def accepted_result(
        cls,
        *,
        created_material_path: str = "",
        created_paths: Iterable[str] | None = None,
        selection_paths: Iterable[str] | None = None,
        focus_path: str = "",
        message: str = "",
        warnings: Iterable[CoreMaterialWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreateMaterialResult":
        paths = _string_tuple(created_paths)
        primary = _string_value(created_material_path) or (paths[0] if paths else "")
        if not paths and primary:
            paths = (primary,)
        if selection_paths is None:
            selection_paths = (primary,) if primary else ()
        return cls(
            accepted=True,
            created_material_path=primary,
            created_paths=paths,
            selection_paths=_string_tuple(selection_paths),
            focus_path=focus_path,
            message=message,
            warnings=tuple(warnings or ()),
            metadata=metadata or {},
        )

    @classmethod
    def rejected_result(
        cls,
        *,
        message: str = "",
        error_code: str | CoreMaterialErrorCode = CoreMaterialErrorCode.CREATE_FAILED,
        warnings: Iterable[CoreMaterialWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreateMaterialResult":
        return cls(
            accepted=False,
            message=message,
            error_code=_string_value(error_code),
            warnings=tuple(warnings or ()),
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class BindMaterialResult:
    accepted: bool
    material_path: str = ""
    bound_prim_paths: tuple[str, ...] = field(default_factory=tuple)
    skipped_prim_paths: tuple[str, ...] = field(default_factory=tuple)
    failed_prim_paths: tuple[str, ...] = field(default_factory=tuple)
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    message: str = ""
    error_code: str = ""
    warnings: tuple[CoreMaterialWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        material_path = _string_value(self.material_path)
        bound_prim_paths = _string_tuple(self.bound_prim_paths)
        skipped_prim_paths = _string_tuple(self.skipped_prim_paths)
        failed_prim_paths = _string_tuple(self.failed_prim_paths)
        selection_paths = _string_tuple(self.selection_paths)
        error_code = _string_value(self.error_code)
        if self.accepted and error_code:
            raise ValueError("accepted BindMaterialResult cannot carry an error_code")
        if not self.accepted:
            has_mutation = bool(bound_prim_paths or selection_paths)
            if has_mutation:
                raise ValueError("rejected BindMaterialResult must not report mutations")
            if not error_code:
                error_code = CoreMaterialErrorCode.BIND_FAILED.value
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "material_path", material_path)
        object.__setattr__(self, "bound_prim_paths", bound_prim_paths)
        object.__setattr__(self, "skipped_prim_paths", skipped_prim_paths)
        object.__setattr__(self, "failed_prim_paths", failed_prim_paths)
        object.__setattr__(self, "selection_paths", selection_paths)
        object.__setattr__(self, "message", _string_value(self.message))
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "warnings", _warning_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @classmethod
    def accepted_result(
        cls,
        *,
        material_path: str,
        bound_prim_paths: Iterable[str] | None = None,
        skipped_prim_paths: Iterable[str] | None = None,
        failed_prim_paths: Iterable[str] | None = None,
        selection_paths: Iterable[str] | None = None,
        message: str = "",
        warnings: Iterable[CoreMaterialWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "BindMaterialResult":
        return cls(
            accepted=True,
            material_path=material_path,
            bound_prim_paths=_string_tuple(bound_prim_paths),
            skipped_prim_paths=_string_tuple(skipped_prim_paths),
            failed_prim_paths=_string_tuple(failed_prim_paths),
            selection_paths=_string_tuple(selection_paths),
            message=message,
            warnings=tuple(warnings or ()),
            metadata=metadata or {},
        )

    @classmethod
    def rejected_result(
        cls,
        *,
        material_path: str = "",
        skipped_prim_paths: Iterable[str] | None = None,
        failed_prim_paths: Iterable[str] | None = None,
        message: str = "",
        error_code: str | CoreMaterialErrorCode = CoreMaterialErrorCode.BIND_FAILED,
        warnings: Iterable[CoreMaterialWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "BindMaterialResult":
        return cls(
            accepted=False,
            material_path=material_path,
            skipped_prim_paths=_string_tuple(skipped_prim_paths),
            failed_prim_paths=_string_tuple(failed_prim_paths),
            message=message,
            error_code=_string_value(error_code),
            warnings=tuple(warnings or ()),
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class CreateAndBindMaterialResult:
    accepted: bool
    created_material_path: str = ""
    created_paths: tuple[str, ...] = field(default_factory=tuple)
    bound_prim_paths: tuple[str, ...] = field(default_factory=tuple)
    skipped_prim_paths: tuple[str, ...] = field(default_factory=tuple)
    failed_prim_paths: tuple[str, ...] = field(default_factory=tuple)
    selection_paths: tuple[str, ...] = field(default_factory=tuple)
    focus_path: str = ""
    binding_applied: bool = False
    message: str = ""
    error_code: str = ""
    warnings: tuple[CoreMaterialWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        created_material_path = _string_value(self.created_material_path)
        created_paths = _string_tuple(self.created_paths)
        if self.accepted and not created_material_path and created_paths:
            created_material_path = created_paths[0]
        bound_prim_paths = _string_tuple(self.bound_prim_paths)
        skipped_prim_paths = _string_tuple(self.skipped_prim_paths)
        failed_prim_paths = _string_tuple(self.failed_prim_paths)
        selection_paths = _string_tuple(self.selection_paths)
        focus_path = _string_value(self.focus_path)
        error_code = _string_value(self.error_code)
        if self.accepted and error_code:
            raise ValueError("accepted CreateAndBindMaterialResult cannot carry an error_code")
        if not self.accepted:
            has_mutation = bool(
                created_material_path
                or created_paths
                or bound_prim_paths
                or selection_paths
                or focus_path
                or self.binding_applied
            )
            if has_mutation:
                raise ValueError("rejected CreateAndBindMaterialResult must not report mutations")
            if not error_code:
                error_code = CoreMaterialErrorCode.CREATE_FAILED.value
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "created_material_path", created_material_path)
        object.__setattr__(self, "created_paths", created_paths)
        object.__setattr__(self, "bound_prim_paths", bound_prim_paths)
        object.__setattr__(self, "skipped_prim_paths", skipped_prim_paths)
        object.__setattr__(self, "failed_prim_paths", failed_prim_paths)
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
        created_material_path: str = "",
        created_paths: Iterable[str] | None = None,
        bound_prim_paths: Iterable[str] | None = None,
        skipped_prim_paths: Iterable[str] | None = None,
        failed_prim_paths: Iterable[str] | None = None,
        selection_paths: Iterable[str] | None = None,
        focus_path: str = "",
        binding_applied: bool = False,
        message: str = "",
        warnings: Iterable[CoreMaterialWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreateAndBindMaterialResult":
        paths = _string_tuple(created_paths)
        primary = _string_value(created_material_path) or (paths[0] if paths else "")
        if not paths and primary:
            paths = (primary,)
        if selection_paths is None:
            selection_paths = (primary,) if primary else ()
        return cls(
            accepted=True,
            created_material_path=primary,
            created_paths=paths,
            bound_prim_paths=_string_tuple(bound_prim_paths),
            skipped_prim_paths=_string_tuple(skipped_prim_paths),
            failed_prim_paths=_string_tuple(failed_prim_paths),
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
        skipped_prim_paths: Iterable[str] | None = None,
        failed_prim_paths: Iterable[str] | None = None,
        message: str = "",
        error_code: str | CoreMaterialErrorCode = CoreMaterialErrorCode.CREATE_FAILED,
        warnings: Iterable[CoreMaterialWarning] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreateAndBindMaterialResult":
        return cls(
            accepted=False,
            skipped_prim_paths=_string_tuple(skipped_prim_paths),
            failed_prim_paths=_string_tuple(failed_prim_paths),
            message=message,
            error_code=_string_value(error_code),
            warnings=tuple(warnings or ()),
            metadata=metadata or {},
        )


def _unsupported_warning(message: str, code: CoreMaterialErrorCode) -> CoreMaterialWarning:
    return CoreMaterialWarning(
        code=code.value,
        message=message,
        severity=CoreMaterialWarningSeverity.ERROR,
    )


class CoreMaterialsAdapter:
    """Default no-support surface for adapter-backed core material actions."""

    def list_core_materials(
        self,
        *,
        selection_paths: Iterable[str] | None = None,
    ) -> CoreMaterialCatalog:
        return CoreMaterialCatalog(selection_paths=tuple(selection_paths or ()))

    def create_material(self, request: CreateMaterialRequest) -> CreateMaterialResult:
        _ = request
        message = "Core material creation is not supported by this adapter."
        return CreateMaterialResult.rejected_result(
            message=message,
            error_code=CoreMaterialErrorCode.UNSUPPORTED,
            warnings=(_unsupported_warning(message, CoreMaterialErrorCode.UNSUPPORTED),),
        )

    def bind_material(self, request: BindMaterialRequest) -> BindMaterialResult:
        message = "Core material binding is not supported by this adapter."
        return BindMaterialResult.rejected_result(
            material_path=request.material_path,
            failed_prim_paths=request.selection_paths,
            message=message,
            error_code=CoreMaterialErrorCode.UNSUPPORTED,
            warnings=(_unsupported_warning(message, CoreMaterialErrorCode.UNSUPPORTED),),
        )

    def create_and_bind_material(
        self,
        request: CreateMaterialRequest,
    ) -> CreateAndBindMaterialResult:
        _ = request
        message = "Core material create-and-bind is not supported by this adapter."
        return CreateAndBindMaterialResult.rejected_result(
            message=message,
            error_code=CoreMaterialErrorCode.UNSUPPORTED,
            warnings=(_unsupported_warning(message, CoreMaterialErrorCode.UNSUPPORTED),),
        )

    def subscribe_core_materials_changes(
        self,
        callback: Callable[[], None],
    ) -> SubscriptionProtocol:
        _ = callback
        return _NoopSubscription()


__all__ = [
    "BindMaterialRequest",
    "BindMaterialResult",
    "CoreMaterialBindingPolicy",
    "CoreMaterialCatalog",
    "CoreMaterialDescriptor",
    "CoreMaterialErrorCode",
    "CoreMaterialFamily",
    "CoreMaterialGroupDescriptor",
    "CoreMaterialKind",
    "CoreMaterialRequirement",
    "CoreMaterialWarning",
    "CoreMaterialWarningSeverity",
    "CoreMaterialsAdapter",
    "CreateAndBindMaterialResult",
    "CreateMaterialRequest",
    "CreateMaterialResult",
]
