# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Backend-neutral public Render Settings contracts.

These plain-Python contracts describe the public RenderProduct settings surface
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
    value: Iterable["RenderSettingsProviderDescriptor"]
    | "RenderSettingsProviderDescriptor"
    | None,
) -> Tuple["RenderSettingsProviderDescriptor", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderSettingsProviderDescriptor):
        return (value,)
    return tuple(value)


def _groups_tuple(
    value: Iterable["RenderSettingsGroupDescriptor"]
    | "RenderSettingsGroupDescriptor"
    | None,
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

    def __post_init__(self) -> None:
        component_count = int(self.component_count)
        if component_count <= 0:
            raise ValueError("component_count must be positive")
        object.__setattr__(self, "soft_range", _coerce_range(self.soft_range))
        object.__setattr__(self, "hard_range", _coerce_range(self.hard_range))
        object.__setattr__(self, "allowed_values", _any_tuple(self.allowed_values))
        object.__setattr__(self, "component_count", component_count)
        object.__setattr__(self, "pattern", str(self.pattern or ""))
        object.__setattr__(self, "options", _mapping_proxy(self.options))


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
    """Backend-neutral descriptor for one public RenderProduct setting."""

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

    def __post_init__(self) -> None:
        setting_id = str(self.setting_id or "")
        if not setting_id:
            raise ValueError("setting_id is required")
        object.__setattr__(self, "setting_id", setting_id)
        object.__setattr__(self, "label", str(self.label or setting_id))
        object.__setattr__(self, "provider_id", str(self.provider_id or ""))
        object.__setattr__(self, "group_id", str(self.group_id or ""))
        object.__setattr__(self, "namespace", str(self.namespace or ""))
        object.__setattr__(self, "property_name", str(self.property_name or ""))
        object.__setattr__(self, "description", str(self.description or ""))
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
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "revision_token", str(self.revision_token or ""))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_available(self) -> bool:
        return bool(self.enabled and not self.disabled_reason)

    @property
    def resettable(self) -> bool:
        if self.value_state is not None:
            return self.value_state.resettable
        return bool(self.has_default and self.enabled)


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


class _NoopSubscription:
    """No-op subscription handle for unsupported adapter defaults."""

    def cancel(self) -> None:
        return None


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

        return RenderSettingsCatalog(
            active_render_product_path=str(render_product_path or "")
        )

    def read_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValueState | None:
        """Return the latest value state for one setting, if available."""

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

    def subscribe_render_settings_changes(
        self,
        callback: Callable[[], None],
    ) -> SubscriptionProtocol:
        """Subscribe to setting/provider changes, if supported."""

        return _NoopSubscription()


__all__ = [
    "RenderSettingApplyResult",
    "RenderSettingDescriptor",
    "RenderSettingRequirement",
    "RenderSettingResetResult",
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
]
