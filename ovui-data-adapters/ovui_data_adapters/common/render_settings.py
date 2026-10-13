# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Backend-neutral public Render Settings contracts.

These plain-Python contracts describe the provider-neutral Render Settings surface
without exposing USD prims, ovrtx handles, UI widgets, or concrete property
adapter implementations. Concrete adapters own schema discovery, validation,
authoring, reset, and change notification. Optional UI modules consume these
descriptors and route presentation through the existing Property window
infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple

from ovui_data_adapters.common._subscription import SubscriptionProtocol


class _StableStringEnum(str, Enum):
    """String enum whose values are stable public contract tokens."""

    def __str__(self) -> str:
        return self.value


class RenderSettingValueType(_StableStringEnum):
    """Normalized value families for public render settings."""

    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    ENUM = "enum"
    STRING = "string"
    VECTOR = "vector"
    COLOR = "color"
    TOKEN = "token"
    PATH = "path"
    UNKNOWN = "unknown"
    # Appended after the pre-existing members so the original enum sequence
    # remains an unchanged prefix for order-sensitive callers.
    RELATIONSHIP = "relationship"


class RenderSettingRequirement(_StableStringEnum):
    """Post-write requirement reported for a public setting."""

    NONE = "none"
    WARMUP = "warmup"
    RENDERER_RESTART = "renderer_restart"
    APPLICATION_RESTART = "application_restart"
    UNSUPPORTED = "unsupported"


class RenderSettingVisibility(_StableStringEnum):
    """Visibility policy for providers and settings."""

    PUBLIC = "public"
    DEV_ONLY = "dev_only"
    HIDDEN = "hidden"


class RenderSettingSurfaceKind(_StableStringEnum):
    """Semantic surface bound by a source-owned Render Settings declaration."""

    VALUE = "value"
    RELATIONSHIP = "relationship"
    ACTION = "action"
    DIAGNOSTIC = "diagnostic"


class RenderSettingAccess(_StableStringEnum):
    """Provider access reported independently from presentation placement."""

    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    UNSUPPORTED = "unsupported"


class RenderSettingPersistence(_StableStringEnum):
    """Lifetime/authorship domain for a provider binding.

    Values map onto the accepted binding scopes: USD RenderProduct/stage
    authorship, application settings with and without persistence, renderer
    runtime tokens, transient renderer state, and value-less surfaces.
    """

    RENDER_PRODUCT = "render_product"
    STAGE = "stage"
    APPLICATION = "application"
    APPLICATION_PERSISTENT = "application_persistent"
    RUNTIME = "runtime"
    TRANSIENT = "transient"
    NONE = "none"


class RenderSettingLifecycle(_StableStringEnum):
    """What a renderer must be made to do before a written value is effective.

    Provider-neutral renderer vocabulary: a member names the CONSUMER FAMILY
    that samples a value, never a particular runtime's key, ABI or extension.
    A renderer adapter implements the members — "can this lifecycle run right
    now", "run it", "describe what did or did not happen" — so a settings
    source routing a new row through an existing lifecycle never needs new
    per-adapter wiring.
    """

    #: Consumer holds a live subscription or re-reads per request.
    LIVE = "live"
    #: Consumer samples at texture/resource construction; existing uploads keep
    #: the old value until resources are reloaded.
    TEXTURE_RELOAD = "texture_reload"
    #: Consumer samples during material population/upload.
    MATERIAL_RELOAD = "material_reload"
    #: Consumer samples while constructing resource-manager/dome resources.
    RESOURCE_RELOAD = "resource_reload"
    #: Consumer reads the value once while the scene is created.
    SCENE_RECREATE = "scene_recreate"
    #: New geometry jobs pick the value up immediately; already generated or
    #: cached geometry needs repopulating.
    GEOMETRY_REPOPULATE = "geometry_repopulate"
    #: The value's real owner is a renderer-construction configuration field,
    #: so the renderer must be rebuilt from an updated configuration.
    RENDERER_CONFIG_RECREATE = "renderer_config_recreate"
    #: Declared by a settings source that names no researched consumer family,
    #: so no lifecycle cheaper than the provider's default may be claimed.
    DECLARED = "declared"
    #: The declared row names no consumer on this build.
    NONE = "none"


class RenderSettingWarningSeverity(_StableStringEnum):
    """Severity for public render setting warnings and results."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _tuple_or_empty(value: Iterable[str] | str | None) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _any_tuple(value: Iterable[Any] | Any | None) -> Tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _warnings_tuple(
    value: Iterable["RenderSettingWarning"] | "RenderSettingWarning" | None,
) -> Tuple["RenderSettingWarning", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderSettingWarning):
        return (value,)
    return tuple(value)


def _providers_tuple(
    value: Iterable["RenderSettingsProviderDescriptor"] | "RenderSettingsProviderDescriptor" | None,
) -> Tuple["RenderSettingsProviderDescriptor", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderSettingsProviderDescriptor):
        return (value,)
    return tuple(value)


def _groups_tuple(
    value: Iterable["RenderSettingsGroupDescriptor"] | "RenderSettingsGroupDescriptor" | None,
) -> Tuple["RenderSettingsGroupDescriptor", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderSettingsGroupDescriptor):
        return (value,)
    return tuple(value)


def _settings_tuple(
    value: Iterable["RenderSettingDescriptor"] | "RenderSettingDescriptor" | None,
) -> Tuple["RenderSettingDescriptor", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderSettingDescriptor):
        return (value,)
    return tuple(value)


def _coerce_range(value: Iterable[float] | None) -> Tuple[float, float] | None:
    if value is None:
        return None
    items = tuple(value)
    if len(items) != 2:
        raise ValueError("range values must contain min and max")
    lo, hi = float(items[0]), float(items[1])
    if hi < lo:
        raise ValueError("range max must be greater than or equal to min")
    return (lo, hi)


def _mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class RenderSettingWarning:
    """Warning or disabled-state reason attached to render settings."""

    code: str
    message: str
    severity: RenderSettingWarningSeverity = RenderSettingWarningSeverity.WARNING

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        if not isinstance(self.severity, RenderSettingWarningSeverity):
            object.__setattr__(
                self,
                "severity",
                RenderSettingWarningSeverity(str(self.severity)),
            )


@dataclass(frozen=True)
class RenderSettingValueConstraints:
    """Validation metadata for one setting value."""

    soft_range: Tuple[float, float] | None = None
    hard_range: Tuple[float, float] | None = None
    allowed_values: Tuple[Any, ...] = field(default_factory=tuple)
    component_count: int = 1
    pattern: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)
    step: float | None = None

    def __post_init__(self) -> None:
        component_count = int(self.component_count)
        if component_count <= 0:
            raise ValueError("component_count must be positive")
        object.__setattr__(self, "soft_range", _coerce_range(self.soft_range))
        object.__setattr__(self, "hard_range", _coerce_range(self.hard_range))
        object.__setattr__(self, "allowed_values", _any_tuple(self.allowed_values))
        if self.step is not None:
            step = float(self.step)
            if step <= 0:
                raise ValueError("step must be positive")
            object.__setattr__(self, "step", step)
        object.__setattr__(self, "component_count", component_count)
        object.__setattr__(self, "pattern", str(self.pattern or ""))
        object.__setattr__(self, "options", _mapping_proxy(self.options))


@dataclass(frozen=True)
class RenderSettingCapability:
    """What a provider can do for one binding, without layout authority."""

    surface_kind: RenderSettingSurfaceKind = RenderSettingSurfaceKind.VALUE
    access: RenderSettingAccess = RenderSettingAccess.READ_WRITE
    can_apply: bool = True
    can_reset: bool = True
    can_subscribe: bool = True
    can_invoke: bool = False
    disabled_reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.surface_kind, RenderSettingSurfaceKind):
            object.__setattr__(
                self,
                "surface_kind",
                RenderSettingSurfaceKind(str(self.surface_kind)),
            )
        if not isinstance(self.access, RenderSettingAccess):
            object.__setattr__(self, "access", RenderSettingAccess(str(self.access)))
        object.__setattr__(self, "can_apply", bool(self.can_apply))
        object.__setattr__(self, "can_reset", bool(self.can_reset))
        object.__setattr__(self, "can_subscribe", bool(self.can_subscribe))
        object.__setattr__(self, "can_invoke", bool(self.can_invoke))
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

        if self.access is RenderSettingAccess.UNSUPPORTED:
            if not self.disabled_reason:
                raise ValueError("unsupported capability requires disabled_reason")
            if self.can_apply or self.can_reset or self.can_subscribe or self.can_invoke:
                raise ValueError("unsupported capability cannot expose operations")
        if self.access is RenderSettingAccess.READ_ONLY and (self.can_apply or self.can_reset):
            raise ValueError("read-only capability cannot apply or reset")
        if self.surface_kind is RenderSettingSurfaceKind.ACTION:
            if self.access is not RenderSettingAccess.UNSUPPORTED and not self.can_invoke:
                raise ValueError("action capability requires can_invoke")
            if self.can_apply or self.can_reset:
                raise ValueError("action capability cannot apply or reset a value")
        elif self.can_invoke:
            raise ValueError("can_invoke is valid only for action capabilities")
        if self.surface_kind is RenderSettingSurfaceKind.DIAGNOSTIC:
            if self.access is RenderSettingAccess.READ_WRITE:
                raise ValueError("diagnostic capability cannot be read-write")

    @classmethod
    def read_only(
        cls,
        *,
        surface_kind: RenderSettingSurfaceKind | str = RenderSettingSurfaceKind.VALUE,
        can_subscribe: bool = True,
    ) -> "RenderSettingCapability":
        return cls(
            surface_kind=surface_kind,
            access=RenderSettingAccess.READ_ONLY,
            can_apply=False,
            can_reset=False,
            can_subscribe=can_subscribe,
        )

    @classmethod
    def action(cls, *, can_subscribe: bool = False) -> "RenderSettingCapability":
        return cls(
            surface_kind=RenderSettingSurfaceKind.ACTION,
            can_apply=False,
            can_reset=False,
            can_subscribe=can_subscribe,
            can_invoke=True,
        )

    @classmethod
    def unsupported(
        cls,
        reason: str,
        *,
        surface_kind: RenderSettingSurfaceKind | str = RenderSettingSurfaceKind.VALUE,
    ) -> "RenderSettingCapability":
        return cls(
            surface_kind=surface_kind,
            access=RenderSettingAccess.UNSUPPORTED,
            can_apply=False,
            can_reset=False,
            can_subscribe=False,
            can_invoke=False,
            disabled_reason=reason,
        )


@dataclass(frozen=True)
class RenderSettingValueState:
    """Current/default/authored/dirty state for one setting."""

    current_value: Any = None
    default_value: Any = None
    has_default: bool = False
    authored: bool = False
    inherited: bool = False
    dirty: bool = False
    invalid: bool = False
    disabled: bool = False
    disabled_reason: str = ""
    message: str = ""
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "has_default", bool(self.has_default))
        object.__setattr__(self, "authored", bool(self.authored))
        object.__setattr__(self, "inherited", bool(self.inherited))
        object.__setattr__(self, "dirty", bool(self.dirty))
        object.__setattr__(self, "invalid", bool(self.invalid))
        object.__setattr__(self, "disabled", bool(self.disabled))
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))
        object.__setattr__(self, "message", str(self.message or ""))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def resettable(self) -> bool:
        """Whether a reset-to-default affordance should be active."""

        return bool(self.authored and not self.disabled)


@dataclass(frozen=True)
class RenderSettingsProviderDescriptor:
    """One provider contributing settings to the Render Settings host."""

    provider_id: str
    display_name: str = ""
    api_version: str = "1"
    capabilities: Tuple[str, ...] = field(default_factory=tuple)
    visibility: RenderSettingVisibility = RenderSettingVisibility.PUBLIC
    visibility_gate: str = ""
    isolation_key: str = ""
    enabled: bool = True
    disabled_reason: str = ""
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        provider_id = str(self.provider_id or "")
        if not provider_id:
            raise ValueError("provider_id is required")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(
            self,
            "display_name",
            str(self.display_name or provider_id),
        )
        object.__setattr__(self, "api_version", str(self.api_version or "1"))
        object.__setattr__(self, "capabilities", _tuple_or_empty(self.capabilities))
        if not isinstance(self.visibility, RenderSettingVisibility):
            object.__setattr__(
                self,
                "visibility",
                RenderSettingVisibility(str(self.visibility)),
            )
        object.__setattr__(self, "visibility_gate", str(self.visibility_gate or ""))
        object.__setattr__(
            self,
            "isolation_key",
            str(self.isolation_key or provider_id),
        )
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def dev_only(self) -> bool:
        """Compatibility predicate for SRD Section 5 dev-only visibility."""

        return self.visibility is RenderSettingVisibility.DEV_ONLY

    @property
    def is_available(self) -> bool:
        return bool(self.enabled and not self.disabled_reason)


@dataclass(frozen=True)
class RenderSettingsGroupDescriptor:
    """Group shown in the Render Settings property window."""

    group_id: str
    label: str = ""
    provider_id: str = ""
    order: float = 1000.0
    collapsed_default: bool = False
    parent_group_id: str = ""
    description: str = ""
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        group_id = str(self.group_id or "")
        if not group_id:
            raise ValueError("group_id is required")
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "label", str(self.label or group_id))
        object.__setattr__(self, "provider_id", str(self.provider_id or ""))
        object.__setattr__(self, "order", float(self.order))
        object.__setattr__(self, "collapsed_default", bool(self.collapsed_default))
        object.__setattr__(self, "parent_group_id", str(self.parent_group_id or ""))
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))


@dataclass(frozen=True)
class RenderSettingDescriptor:
    """Backend-neutral binding for one source-owned Render Settings surface.

    ``order`` is retained for compatibility with the existing flat catalog;
    exact contextual display order belongs to the six source-owner modules and
    their PropertyWindow projection, never to a provider binding.
    """

    setting_id: str
    label: str = ""
    provider_id: str = ""
    group_id: str = ""
    namespace: str = ""
    property_name: str = ""
    description: str = ""
    value_type: RenderSettingValueType = RenderSettingValueType.UNKNOWN
    constraints: RenderSettingValueConstraints = field(
        default_factory=RenderSettingValueConstraints
    )
    units: str = ""
    default_value: Any = None
    has_default: bool = False
    requirement: RenderSettingRequirement = RenderSettingRequirement.NONE
    visibility: RenderSettingVisibility = RenderSettingVisibility.PUBLIC
    visibility_gate: str = ""
    order: float = 1000.0
    enabled: bool = True
    disabled_reason: str = ""
    value_state: RenderSettingValueState | None = None
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)
    revision_token: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_id: str = ""
    binding_id: str = ""
    capability: RenderSettingCapability = field(default_factory=RenderSettingCapability)
    persistence: RenderSettingPersistence = RenderSettingPersistence.RENDER_PRODUCT

    def __post_init__(self) -> None:
        setting_id = str(self.setting_id or "")
        if not setting_id:
            raise ValueError("setting_id is required")
        object.__setattr__(self, "setting_id", setting_id)
        object.__setattr__(self, "source_id", str(self.source_id or setting_id))
        object.__setattr__(self, "binding_id", str(self.binding_id or setting_id))
        object.__setattr__(self, "label", str(self.label or setting_id))
        object.__setattr__(self, "provider_id", str(self.provider_id or ""))
        object.__setattr__(self, "group_id", str(self.group_id or ""))
        object.__setattr__(self, "namespace", str(self.namespace or ""))
        object.__setattr__(self, "property_name", str(self.property_name or ""))
        object.__setattr__(self, "description", str(self.description or ""))
        if not isinstance(self.capability, RenderSettingCapability):
            raise TypeError("capability must be a RenderSettingCapability")
        if not isinstance(self.constraints, RenderSettingValueConstraints):
            raise TypeError("constraints must be RenderSettingValueConstraints")
        if not isinstance(self.value_type, RenderSettingValueType):
            object.__setattr__(
                self,
                "value_type",
                RenderSettingValueType(str(self.value_type)),
            )
        if not isinstance(self.requirement, RenderSettingRequirement):
            object.__setattr__(
                self,
                "requirement",
                RenderSettingRequirement(str(self.requirement)),
            )
        if not isinstance(self.persistence, RenderSettingPersistence):
            object.__setattr__(
                self,
                "persistence",
                RenderSettingPersistence(str(self.persistence)),
            )
        if not isinstance(self.visibility, RenderSettingVisibility):
            object.__setattr__(
                self,
                "visibility",
                RenderSettingVisibility(str(self.visibility)),
            )
        object.__setattr__(self, "units", str(self.units or ""))
        object.__setattr__(self, "has_default", bool(self.has_default))
        object.__setattr__(self, "visibility_gate", str(self.visibility_gate or ""))
        object.__setattr__(self, "order", float(self.order))
        object.__setattr__(self, "enabled", bool(self.enabled))
        disabled_reason = str(self.disabled_reason or "")
        if not disabled_reason and self.capability.access is RenderSettingAccess.UNSUPPORTED:
            disabled_reason = self.capability.disabled_reason
        object.__setattr__(self, "disabled_reason", disabled_reason)
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "revision_token", str(self.revision_token or ""))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_available(self) -> bool:
        return bool(
            self.enabled
            and not self.disabled_reason
            and self.capability.access is not RenderSettingAccess.UNSUPPORTED
        )

    @property
    def effective_disabled_reason(self) -> str:
        """Concrete provider reason without affecting source-owned placement."""

        return self.disabled_reason or self.capability.disabled_reason

    @property
    def resettable(self) -> bool:
        if not self.capability.can_reset or not self.is_available:
            return False
        if self.value_state is not None:
            return self.value_state.resettable
        return bool(self.has_default)


@dataclass(frozen=True)
class RenderSettingsCatalog:
    """Immutable snapshot of public settings for an active RenderProduct."""

    active_render_product_path: str = ""
    active_render_product_label: str = ""
    providers: Tuple[RenderSettingsProviderDescriptor, ...] = field(default_factory=tuple)
    groups: Tuple[RenderSettingsGroupDescriptor, ...] = field(default_factory=tuple)
    settings: Tuple[RenderSettingDescriptor, ...] = field(default_factory=tuple)
    revision: str = ""
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "active_render_product_path",
            str(self.active_render_product_path or ""),
        )
        object.__setattr__(
            self,
            "active_render_product_label",
            str(self.active_render_product_label or ""),
        )
        object.__setattr__(self, "providers", _providers_tuple(self.providers))
        object.__setattr__(self, "groups", _groups_tuple(self.groups))
        object.__setattr__(self, "settings", _settings_tuple(self.settings))
        object.__setattr__(self, "revision", str(self.revision or ""))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))

    @property
    def is_empty(self) -> bool:
        return not self.settings

    def provider(self, provider_id: str) -> RenderSettingsProviderDescriptor | None:
        for descriptor in self.providers:
            if descriptor.provider_id == provider_id:
                return descriptor
        return None

    def group(self, group_id: str) -> RenderSettingsGroupDescriptor | None:
        for descriptor in self.groups:
            if descriptor.group_id == group_id:
                return descriptor
        return None

    def setting(self, setting_id: str) -> RenderSettingDescriptor | None:
        for descriptor in self.settings:
            if descriptor.setting_id == setting_id:
                return descriptor
        return None


@dataclass(frozen=True)
class RenderSettingValidationResult:
    """Result of validating an edited setting value before apply."""

    accepted: bool = False
    setting_id: str = ""
    normalized_value: Any = None
    requirement: RenderSettingRequirement = RenderSettingRequirement.NONE
    message: str = ""
    warning_code: Optional[str] = None
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "setting_id", str(self.setting_id or ""))
        if not isinstance(self.requirement, RenderSettingRequirement):
            object.__setattr__(
                self,
                "requirement",
                RenderSettingRequirement(str(self.requirement)),
            )
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))

    @classmethod
    def accepted_result(
        cls,
        *,
        setting_id: str = "",
        normalized_value: Any = None,
        requirement: RenderSettingRequirement | str = RenderSettingRequirement.NONE,
        message: str = "",
    ) -> "RenderSettingValidationResult":
        return cls(
            True,
            setting_id=setting_id,
            normalized_value=normalized_value,
            requirement=(
                requirement
                if isinstance(requirement, RenderSettingRequirement)
                else RenderSettingRequirement(str(requirement))
            ),
            message=message,
        )

    @classmethod
    def rejected_result(
        cls,
        message: str,
        *,
        setting_id: str = "",
        warning_code: str = "validation_failed",
    ) -> "RenderSettingValidationResult":
        return cls(
            False,
            setting_id=setting_id,
            message=message,
            warning_code=warning_code,
        )


@dataclass(frozen=True)
class RenderSettingApplyResult:
    """Result of applying a validated setting value."""

    accepted: bool = False
    setting_id: str = ""
    current_value: Any = None
    value_state: RenderSettingValueState | None = None
    requirement: RenderSettingRequirement = RenderSettingRequirement.NONE
    message: str = ""
    warning_code: Optional[str] = None
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "setting_id", str(self.setting_id or ""))
        if not isinstance(self.requirement, RenderSettingRequirement):
            object.__setattr__(
                self,
                "requirement",
                RenderSettingRequirement(str(self.requirement)),
            )
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))

    @classmethod
    def accepted_result(
        cls,
        *,
        setting_id: str = "",
        current_value: Any = None,
        value_state: RenderSettingValueState | None = None,
        requirement: RenderSettingRequirement | str = RenderSettingRequirement.NONE,
        message: str = "",
    ) -> "RenderSettingApplyResult":
        return cls(
            True,
            setting_id=setting_id,
            current_value=current_value,
            value_state=value_state,
            requirement=(
                requirement
                if isinstance(requirement, RenderSettingRequirement)
                else RenderSettingRequirement(str(requirement))
            ),
            message=message,
        )

    @classmethod
    def rejected_result(
        cls,
        message: str,
        *,
        setting_id: str = "",
        warning_code: str = "apply_failed",
    ) -> "RenderSettingApplyResult":
        return cls(
            False,
            setting_id=setting_id,
            message=message,
            warning_code=warning_code,
        )


@dataclass(frozen=True)
class RenderSettingResetResult:
    """Result of clearing an authored setting opinion."""

    accepted: bool = False
    setting_id: str = ""
    reset_value: Any = None
    value_state: RenderSettingValueState | None = None
    requirement: RenderSettingRequirement = RenderSettingRequirement.NONE
    message: str = ""
    warning_code: Optional[str] = None
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "setting_id", str(self.setting_id or ""))
        if not isinstance(self.requirement, RenderSettingRequirement):
            object.__setattr__(
                self,
                "requirement",
                RenderSettingRequirement(str(self.requirement)),
            )
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))

    @classmethod
    def accepted_result(
        cls,
        *,
        setting_id: str = "",
        reset_value: Any = None,
        value_state: RenderSettingValueState | None = None,
        requirement: RenderSettingRequirement | str = RenderSettingRequirement.NONE,
        message: str = "",
    ) -> "RenderSettingResetResult":
        return cls(
            True,
            setting_id=setting_id,
            reset_value=reset_value,
            value_state=value_state,
            requirement=(
                requirement
                if isinstance(requirement, RenderSettingRequirement)
                else RenderSettingRequirement(str(requirement))
            ),
            message=message,
        )

    @classmethod
    def rejected_result(
        cls,
        message: str,
        *,
        setting_id: str = "",
        warning_code: str = "reset_failed",
    ) -> "RenderSettingResetResult":
        return cls(
            False,
            setting_id=setting_id,
            message=message,
            warning_code=warning_code,
        )


@dataclass(frozen=True)
class RenderSettingActionResult:
    """Result of invoking a source-owned non-value action surface."""

    accepted: bool = False
    action_id: str = ""
    requirement: RenderSettingRequirement = RenderSettingRequirement.NONE
    message: str = ""
    warning_code: Optional[str] = None
    warnings: Tuple[RenderSettingWarning, ...] = field(default_factory=tuple)
    output: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "action_id", str(self.action_id or ""))
        if not isinstance(self.requirement, RenderSettingRequirement):
            object.__setattr__(
                self,
                "requirement",
                RenderSettingRequirement(str(self.requirement)),
            )
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "output", _mapping_proxy(self.output))

    @classmethod
    def accepted_result(
        cls,
        *,
        action_id: str = "",
        requirement: RenderSettingRequirement | str = RenderSettingRequirement.NONE,
        message: str = "",
        output: Mapping[str, Any] | None = None,
    ) -> "RenderSettingActionResult":
        return cls(
            True,
            action_id=action_id,
            requirement=requirement,
            message=message,
            output=output or {},
        )

    @classmethod
    def rejected_result(
        cls,
        message: str,
        *,
        action_id: str = "",
        warning_code: str = "action_failed",
    ) -> "RenderSettingActionResult":
        return cls(
            False,
            action_id=action_id,
            message=message,
            warning_code=warning_code,
        )


def render_setting_values_semantically_equal(
    old_value: Any,
    new_value: Any,
    *,
    missing: Any = None,
) -> bool:
    """Semantic equality for the shared render-setting no-op boundary.

    ``missing`` (an authorship-transition sentinel) is never equal to a
    concrete value; booleans compare strictly by truth AND boolean-ness
    (1 never aliases True); numeric scalars compare by value; strings
    exactly; sequences elementwise with equal length."""

    if missing is not None and (old_value is missing or new_value is missing):
        return False
    if isinstance(old_value, bool) or isinstance(new_value, bool):
        return (
            isinstance(old_value, bool)
            and isinstance(new_value, bool)
            and old_value == new_value
        )
    if isinstance(old_value, str) or isinstance(new_value, str):
        return (
            isinstance(old_value, str)
            and isinstance(new_value, str)
            and old_value == new_value
        )
    if isinstance(old_value, (list, tuple)) or isinstance(
        new_value, (list, tuple)
    ):
        if not (
            isinstance(old_value, (list, tuple))
            and isinstance(new_value, (list, tuple))
        ):
            return False
        if len(old_value) != len(new_value):
            return False
        return all(
            render_setting_values_semantically_equal(left, right)
            for left, right in zip(old_value, new_value)
        )
    if isinstance(old_value, (int, float)) and isinstance(
        new_value, (int, float)
    ):
        return float(old_value) == float(new_value)
    try:
        return bool(old_value == new_value)
    except Exception:
        return False


class _NoopSubscription:
    """No-op subscription handle for unsupported adapter defaults."""

    def cancel(self) -> None:
        return None


class RenderSettingsSubscriptionOwner:
    """Deterministic, idempotent ownership for provider subscriptions.

    Definition/projection objects describe subscription dependencies but never
    start them. Adapters/controllers use this owner when they acquire concrete
    handles so teardown has one explicit lifetime boundary.
    """

    def __init__(self) -> None:
        self._subscriptions: list[SubscriptionProtocol] = []
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def own(self, subscription: SubscriptionProtocol) -> SubscriptionProtocol:
        if not isinstance(subscription, SubscriptionProtocol):
            raise TypeError("subscription must provide cancel()")
        if self._cancelled:
            subscription.cancel()
            return subscription
        self._subscriptions.append(subscription)
        return subscription

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        subscriptions, self._subscriptions = self._subscriptions, []
        first_error: Exception | None = None
        for subscription in reversed(subscriptions):
            try:
                subscription.cancel()
            except Exception as error:  # teardown continues deterministically
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error


class RenderSettingsAdapter:
    """Default no-support public Render Settings adapter surface.

    Concrete render-settings property adapters can inherit this alongside the
    existing ``PropertyAdapter`` contract to expose catalog, validation,
    apply/reset, and change-notification behavior without leaking backend
    objects into UI/controller code.
    """

    def list_render_settings(
        self,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingsCatalog:
        """Return a catalog snapshot for a RenderProduct, if supported."""

        return RenderSettingsCatalog(active_render_product_path=str(render_product_path or ""))

    def read_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValueState | None:
        """Return the latest value state for one setting, if available."""

        return None

    def read_render_setting_value(
        self,
        attr_name: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> Any:
        """Return the effective value of ONE named setting, if available.

        Same owner-prim resolution and same authored-else-default rule as
        :meth:`list_render_settings`, for a single declared attribute name.
        A caller that needs one value — the active render-mode token, say —
        would otherwise have to describe the whole declared setting surface
        to reach it. ``None`` means the adapter has no value to report.
        """

        return None

    def validate_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValidationResult:
        """Validate a setting value before apply, if supported."""

        return RenderSettingValidationResult.rejected_result(
            "Public render settings are not supported.",
            setting_id=setting_id,
            warning_code="unsupported",
        )

    def apply_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingApplyResult:
        """Apply a setting value, if supported."""

        return RenderSettingApplyResult.rejected_result(
            "Public render settings are not supported.",
            setting_id=setting_id,
            warning_code="unsupported",
        )

    def reset_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingResetResult:
        """Reset a setting to its default/inherited state, if supported."""

        return RenderSettingResetResult.rejected_result(
            "Public render settings are not supported.",
            setting_id=setting_id,
            warning_code="unsupported",
        )

    def invoke_render_setting_action(
        self,
        action_id: str,
        *,
        render_product_path: Optional[str] = None,
        payload: Mapping[str, Any] | None = None,
    ) -> RenderSettingActionResult:
        """Invoke a non-value action surface, if supported."""

        return RenderSettingActionResult.rejected_result(
            "Public render setting actions are not supported.",
            action_id=action_id,
            warning_code="unsupported",
        )

    def subscribe_render_settings_changes(
        self,
        callback: Callable[[], None],
    ) -> SubscriptionProtocol:
        """Subscribe to setting/provider changes, if supported."""

        return _NoopSubscription()


# --------------------------------------------------------------------------
# Owner scopes: WHICH prim authoritatively carries a render setting.
#
# A render setting is not always carried by the RenderProduct. Exposure and
# auto-exposure live on the Camera the product renders through, and a handful
# of settings live on the private RenderSettings prim the renderer resolves.
# Every adapter has to agree on that classification, because writing to the
# wrong prim means the renderer never reads the value and reading from the
# wrong prim means the UI never shows it.
# --------------------------------------------------------------------------

#: The default owner slot: the active RenderProduct prim.
RENDER_PRODUCT_OWNER_SCOPE = "RenderProduct"
#: The Camera the active RenderProduct renders through.
CAMERA_OWNER_SCOPE = "Camera"
#: The private RenderSettings prim resolved for globally owned settings.
RENDER_SETTINGS_OWNER_SCOPE = "RenderSettings"


def build_render_setting_builtin_spec_index(
    builtin_specs: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, Any]]:
    """Index builtin specs by attribute name.

    Catalogs are rebuilt per request and the declared setting surface is large,
    so a linear scan per attribute is quadratic; the index is rebuilt only when
    a schema is installed.
    """

    return {
        str(spec.get("attr_name") or ""): spec
        for spec in builtin_specs
        if spec.get("attr_name")
    }


def render_setting_spec_owner_scope(
    index: Mapping[str, Mapping[str, Any]],
    attr_name: str,
) -> str:
    """Declared owner scope for one builtin attribute name."""

    spec = index.get(str(attr_name))
    if spec is None:
        return RENDER_PRODUCT_OWNER_SCOPE
    return str(spec.get("owner_scope") or RENDER_PRODUCT_OWNER_SCOPE)


def render_setting_owner_scope(descriptor: Any) -> str:
    """Owner prim type that authoritatively carries this setting.

    Reads the descriptor's own metadata (flat or nested under
    ``render_settings_metadata``) and falls back to the RenderProduct — the
    renderer's own default owner slot. Failing closed on an owner that cannot
    be resolved belongs to the owner-path resolver, which returns an empty path
    for a scope it cannot address; it does not belong here, where an empty
    string would misreport the declared scope.
    """

    metadata = getattr(descriptor, "metadata", None) or {}
    nested = metadata.get("render_settings_metadata")
    return str(
        metadata.get("owner_scope")
        or (nested.get("owner_scope") if isinstance(nested, Mapping) else "")
        or RENDER_PRODUCT_OWNER_SCOPE
    )


__all__ = [
    "CAMERA_OWNER_SCOPE",
    "RENDER_PRODUCT_OWNER_SCOPE",
    "RENDER_SETTINGS_OWNER_SCOPE",
    "RenderSettingAccess",
    "RenderSettingActionResult",
    "RenderSettingApplyResult",
    "RenderSettingCapability",
    "RenderSettingDescriptor",
    "RenderSettingLifecycle",
    "RenderSettingPersistence",
    "RenderSettingRequirement",
    "RenderSettingResetResult",
    "RenderSettingSurfaceKind",
    "RenderSettingValidationResult",
    "RenderSettingValueConstraints",
    "RenderSettingValueState",
    "RenderSettingValueType",
    "RenderSettingVisibility",
    "RenderSettingWarning",
    "RenderSettingWarningSeverity",
    "RenderSettingsAdapter",
    "RenderSettingsCatalog",
    "RenderSettingsGroupDescriptor",
    "RenderSettingsProviderDescriptor",
    "RenderSettingsSubscriptionOwner",
    "build_render_setting_builtin_spec_index",
    "render_setting_owner_scope",
    "render_setting_spec_owner_scope",
]
