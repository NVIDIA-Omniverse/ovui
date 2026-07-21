# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""SRD section 4.4 built-in viewport resolution preset catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ovui_widgets.viewport.resolution_settings import (
    SETTING_RESOLUTION_PRESETS,
    normalize_loaded_custom_resolution_list,
)

RESOLUTION_CATALOG_KIND_PRESET = "preset"
RESOLUTION_CATALOG_KIND_CUSTOM = "custom"
RESOLUTION_CATALOG_KIND_SAVED_CUSTOM = RESOLUTION_CATALOG_KIND_CUSTOM
RESOLUTION_CATALOG_KIND_SENTINEL = "sentinel"
RESOLUTION_PRESET_SOURCE_SRD_4_4 = "SRD 4.4"
RESOLUTION_SENTINEL_SOURCE_SRD_4_3 = "SRD 4.3"
RESOLUTION_SAVED_CUSTOM_SOURCE_SETTING = "viewport.resolution.custom.list"
RESOLUTION_RATIO_BADGE_TOLERANCE = 0.01
VIEWPORT_SENTINEL_DIMENSIONS = (0, 0)
CUSTOM_SENTINEL_DIMENSIONS = (-1, -1)
RESOLUTION_SENTINEL_VIEWPORT_KEY = "sentinel:Viewport"
RESOLUTION_SENTINEL_CUSTOM_KEY = "sentinel:Custom"
RESOLUTION_MATCH_SOURCE_BUILTIN = "built-in preset"
RESOLUTION_MATCH_SOURCE_SAVED_CUSTOM = "saved custom"
RESOLUTION_MATCH_SOURCE_SENTINEL = "custom sentinel"
RESOLUTION_MATCH_PRIORITY_DESCRIPTION = (
    "exact dimensions -> built-in preset over saved custom -> first normalized "
    "saved custom -> Custom sentinel"
)
RESOLUTION_SELECTION_KEYING_DESCRIPTION = (
    "accepted requested full dimensions; not render scale, fill, clamp, or "
    "effective size"
)
KNOWN_RESOLUTION_RATIO_BADGES = (
    (16 / 9, "16:9"),
    (1.0, "1:1"),
    (32 / 9, "32:9"),
    (4 / 3, "4:3"),
    (21 / 9, "21:9"),
)
DEFAULT_VISIBLE_RESOLUTION_PRESET_LABELS = (
    "UHD",
    "1440P",
    "2K",
    "HD1080P",
    "HD720P",
    "Square",
    "Icon",
)
_MISSING = object()


@dataclass(frozen=True)
class ResolutionBadgeMetadata:
    """Reusable text metadata for future render-resolution menu rows."""

    resolution_text: str
    ratio_badge_label: str | None


@dataclass(frozen=True)
class ResolutionPresetCatalogRow:
    """Canonical built-in resolution preset row independent of widget rendering."""

    key: str
    label: str
    width: int
    height: int
    kind: str = RESOLUTION_CATALOG_KIND_PRESET
    recognized: bool = True
    source: str = RESOLUTION_PRESET_SOURCE_SRD_4_4

    @property
    def dimensions(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def dimension_text(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def resolution_text(self) -> str:
        return resolution_badge_metadata(self.width, self.height).resolution_text

    @property
    def ratio_badge_label(self) -> str | None:
        return resolution_badge_metadata(self.width, self.height).ratio_badge_label


@dataclass(frozen=True)
class ResolutionSavedCustomCatalogRow:
    """Saved custom resolution catalog row without Area-4 rendering."""

    label: str
    width: int
    height: int
    kind: str = RESOLUTION_CATALOG_KIND_CUSTOM
    source: str = RESOLUTION_SAVED_CUSTOM_SOURCE_SETTING

    @property
    def key(self) -> str:
        return f"custom:{self.label}:{self.width}x{self.height}"

    @property
    def dimensions(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def dimension_text(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def resolution_text(self) -> str:
        return resolution_badge_metadata(self.width, self.height).resolution_text

    @property
    def ratio_badge_label(self) -> str | None:
        return resolution_badge_metadata(self.width, self.height).ratio_badge_label


ResolutionSavedCustomBadgeRow = ResolutionSavedCustomCatalogRow


@dataclass(frozen=True)
class ResolutionSentinelCatalogRow:
    """Stable non-preset catalog sentinel row metadata from SRD section 4.3."""

    key: str
    label: str
    width: int
    height: int
    meaning: str
    kind: str = RESOLUTION_CATALOG_KIND_SENTINEL
    source: str = RESOLUTION_SENTINEL_SOURCE_SRD_4_3

    @property
    def dimensions(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def dimension_text(self) -> str:
        return f"[{self.width},{self.height}]"

    @property
    def resolution_text(self) -> str:
        return self.dimension_text

    @property
    def ratio_badge_label(self) -> str | None:
        return None

    @property
    def requires_positive_unsaved_size(self) -> bool:
        return self.key == RESOLUTION_SENTINEL_CUSTOM_KEY


@dataclass(frozen=True)
class ResolutionCatalogMatch:
    """Deterministic positive-size match result for Area-4/5 consumers."""

    row: (
        ResolutionPresetCatalogRow
        | ResolutionSavedCustomCatalogRow
        | ResolutionSentinelCatalogRow
    )
    requested_size: tuple[int, int]
    source: str

    @property
    def key(self) -> str:
        return self.row.key

    @property
    def label(self) -> str:
        return self.row.label

    @property
    def kind(self) -> str:
        return self.row.kind

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.row.dimensions

    @property
    def resolution_text(self) -> str:
        return self.row.resolution_text

    @property
    def ratio_badge_label(self) -> str | None:
        return self.row.ratio_badge_label


@dataclass(frozen=True)
class ResolutionCatalogSelection:
    """Exactly-one catalog selection derived from accepted requested size."""

    row: (
        ResolutionPresetCatalogRow
        | ResolutionSavedCustomCatalogRow
        | ResolutionSentinelCatalogRow
    )
    requested_size: tuple[int, int]
    current_label: str
    source: str

    @property
    def key(self) -> str:
        return self.row.key

    @property
    def label(self) -> str:
        return self.row.label

    @property
    def kind(self) -> str:
        return self.row.kind

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.row.dimensions

    @property
    def resolution_text(self) -> str:
        return self.row.resolution_text

    @property
    def ratio_badge_label(self) -> str | None:
        return self.row.ratio_badge_label

    @property
    def selected_row_count(self) -> int:
        return 1


BUILTIN_RESOLUTION_PRESETS: tuple[ResolutionPresetCatalogRow, ...] = (
    ResolutionPresetCatalogRow("preset:UHD", "UHD", 3840, 2160),
    ResolutionPresetCatalogRow("preset:1440P", "1440P", 2560, 1440),
    ResolutionPresetCatalogRow("preset:2K", "2K", 2048, 1080),
    ResolutionPresetCatalogRow("preset:HD1080P", "HD1080P", 1920, 1080),
    ResolutionPresetCatalogRow("preset:HD720P", "HD720P", 1280, 720),
    ResolutionPresetCatalogRow("preset:Square", "Square", 1024, 1024),
    ResolutionPresetCatalogRow("preset:Icon", "Icon", 512, 512),
    ResolutionPresetCatalogRow("preset:SD", "SD", 1280, 960),
    ResolutionPresetCatalogRow("preset:Ultra Wide", "Ultra Wide", 3440, 1440),
    ResolutionPresetCatalogRow(
        "preset:Super Ultra Wide",
        "Super Ultra Wide",
        3840,
        1440,
    ),
    ResolutionPresetCatalogRow("preset:5K Wide", "5K Wide", 5120, 2880),
)
_PRESETS_BY_DIMENSIONS = {
    row.dimensions: row
    for row in BUILTIN_RESOLUTION_PRESETS
}
VIEWPORT_RESOLUTION_SENTINEL = ResolutionSentinelCatalogRow(
    RESOLUTION_SENTINEL_VIEWPORT_KEY,
    "Viewport",
    VIEWPORT_SENTINEL_DIMENSIONS[0],
    VIEWPORT_SENTINEL_DIMENSIONS[1],
    "UI-frame-driven mode",
)
CUSTOM_RESOLUTION_SENTINEL = ResolutionSentinelCatalogRow(
    RESOLUTION_SENTINEL_CUSTOM_KEY,
    "Custom",
    CUSTOM_SENTINEL_DIMENSIONS[0],
    CUSTOM_SENTINEL_DIMENSIONS[1],
    "unsaved positive non-matching requested size",
)
RESOLUTION_SENTINEL_ROWS = (
    VIEWPORT_RESOLUTION_SENTINEL,
    CUSTOM_RESOLUTION_SENTINEL,
)


def _strict_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _strict_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _strict_integer_pair(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    width = _strict_int(value[0])
    height = _strict_int(value[1])
    if width is None or height is None:
        return None
    return (width, height)


def _strict_positive_size_pair(value: Any) -> tuple[int, int] | None:
    size = _strict_integer_pair(value)
    if size is None:
        return None
    width, height = size
    if width <= 0 or height <= 0:
        return None
    return size


def _sentinel_row_text(row: ResolutionSentinelCatalogRow) -> str:
    return f"{row.label} {row.dimension_text}"


def _requested_size_text(value: Any) -> str:
    size = _strict_integer_pair(value)
    if size is None:
        return "invalid"
    width, height = size
    return f"[{width},{height}]"


def resolution_badge_metadata(width: Any, height: Any) -> ResolutionBadgeMetadata:
    """Return resolution text and Kit-compatible ratio badge metadata."""

    normalized_width = _strict_positive_int(width)
    normalized_height = _strict_positive_int(height)
    if normalized_width is None or normalized_height is None:
        return ResolutionBadgeMetadata("", None)

    ratio = normalized_width / normalized_height
    for known_ratio, label in KNOWN_RESOLUTION_RATIO_BADGES:
        relative_delta = abs(ratio - known_ratio) / known_ratio
        if relative_delta <= RESOLUTION_RATIO_BADGE_TOLERANCE:
            return ResolutionBadgeMetadata(
                f"{normalized_width}x{normalized_height}",
                label,
            )
    return ResolutionBadgeMetadata(
        f"{normalized_width}x{normalized_height}",
        f"{ratio:.2f}:1",
    )


def iter_saved_custom_resolution_badge_rows(
    entries: Iterable[Any] | None,
) -> tuple[ResolutionSavedCustomBadgeRow, ...]:
    """Return badge metadata rows for valid saved custom resolution entries."""

    return iter_saved_custom_resolution_catalog_rows(entries)


def iter_saved_custom_resolution_catalog_rows(
    entries: Iterable[Any] | None,
) -> tuple[ResolutionSavedCustomCatalogRow, ...]:
    """Return saved custom catalog rows from Area-1 normalized list data."""

    normalized_entries = normalize_loaded_custom_resolution_list(list(entries or ()))
    return tuple(
        ResolutionSavedCustomCatalogRow(
            entry["name"],
            entry["width"],
            entry["height"],
        )
        for entry in normalized_entries
    )


def match_resolution_catalog_row_for_requested_size(
    requested_size: Any,
    *,
    saved_custom_entries: Iterable[Any] | None = None,
) -> ResolutionCatalogMatch | None:
    """Match a positive requested size using the A2-T06 priority contract.

    Matching is exact on integer width and height. Built-in presets win over
    saved custom rows with the same dimensions. If no built-in matches, the
    first normalized saved custom row wins. Positive non-matches fall back to
    the Custom sentinel. Invalid and non-positive sizes do not match here.
    """

    size = _strict_positive_size_pair(requested_size)
    if size is None:
        return None

    builtin = _PRESETS_BY_DIMENSIONS.get(size)
    if builtin is not None:
        return ResolutionCatalogMatch(
            row=builtin,
            requested_size=size,
            source=RESOLUTION_MATCH_SOURCE_BUILTIN,
        )

    for custom_row in iter_saved_custom_resolution_catalog_rows(saved_custom_entries):
        if custom_row.dimensions == size:
            return ResolutionCatalogMatch(
                row=custom_row,
                requested_size=size,
                source=RESOLUTION_MATCH_SOURCE_SAVED_CUSTOM,
            )

    return ResolutionCatalogMatch(
        row=CUSTOM_RESOLUTION_SENTINEL,
        requested_size=size,
        source=RESOLUTION_MATCH_SOURCE_SENTINEL,
    )


def select_resolution_catalog_row_for_requested_size(
    requested_size: Any,
    *,
    saved_custom_entries: Iterable[Any] | None = None,
) -> ResolutionCatalogSelection | None:
    """Map an accepted requested size to the single selected catalog row.

    Selection follows the accepted requested full dimensions only. Scale, fill,
    clamp, and effective-size previews are deliberately outside this mapping.
    """

    size = _strict_integer_pair(requested_size)
    if size == VIEWPORT_SENTINEL_DIMENSIONS:
        return ResolutionCatalogSelection(
            row=VIEWPORT_RESOLUTION_SENTINEL,
            requested_size=VIEWPORT_SENTINEL_DIMENSIONS,
            current_label=VIEWPORT_RESOLUTION_SENTINEL.label,
            source=RESOLUTION_MATCH_SOURCE_SENTINEL,
        )

    match = match_resolution_catalog_row_for_requested_size(
        size,
        saved_custom_entries=saved_custom_entries,
    )
    if match is None:
        return None

    return ResolutionCatalogSelection(
        row=match.row,
        requested_size=match.requested_size,
        current_label=match.label,
        source=match.source,
    )


def select_resolution_catalog_row_for_state(
    resolution_state: Any,
    *,
    saved_custom_entries: Iterable[Any] | None = None,
    render_scale: Any = None,
    effective_size: Any = None,
) -> ResolutionCatalogSelection | None:
    """Return selection for a state-like object, ignoring effective dimensions.

    ``render_scale`` and ``effective_size`` are accepted only to make the AC-09
    boundary explicit for callers and tests; neither affects the selected row.
    """

    del render_scale, effective_size
    requested_size = getattr(resolution_state, "requested_size", resolution_state)
    return select_resolution_catalog_row_for_requested_size(
        requested_size,
        saved_custom_entries=saved_custom_entries,
    )


def iter_builtin_resolution_presets() -> tuple[ResolutionPresetCatalogRow, ...]:
    """Return the stable SRD section 4.4 recognized preset library."""

    return BUILTIN_RESOLUTION_PRESETS


def iter_resolution_sentinel_rows() -> tuple[ResolutionSentinelCatalogRow, ...]:
    """Return the stable Viewport and Custom sentinel rows in SRD order."""

    return RESOLUTION_SENTINEL_ROWS


def resolution_preset_by_label(label: str) -> ResolutionPresetCatalogRow:
    """Return one recognized built-in preset by exact SRD label."""

    for row in BUILTIN_RESOLUTION_PRESETS:
        if row.label == label:
            return row
    raise KeyError(label)


def resolution_sentinel_by_label(label: str) -> ResolutionSentinelCatalogRow:
    """Return one sentinel row by exact SRD label."""

    for row in RESOLUTION_SENTINEL_ROWS:
        if row.label == label:
            return row
    raise KeyError(label)


def selected_resolution_sentinel_for_requested_size(
    requested_size: Any,
) -> ResolutionSentinelCatalogRow | None:
    """Map a requested size to the matching sentinel, if any.

    ``[0,0]`` maps to Viewport. A positive requested size that does not match
    a recognized built-in preset maps to Custom. The negative Custom sentinel
    value itself never maps as an applied requested size.
    """

    size = _strict_integer_pair(requested_size)
    if size == VIEWPORT_SENTINEL_DIMENSIONS:
        return VIEWPORT_RESOLUTION_SENTINEL
    positive_size = _strict_positive_size_pair(size)
    if positive_size is None:
        return None
    if positive_size in _PRESETS_BY_DIMENSIONS:
        return None
    return CUSTOM_RESOLUTION_SENTINEL


def current_resolution_label_for_requested_size(requested_size: Any) -> str | None:
    """Return the sentinel label for current requested-size readouts."""

    sentinel = selected_resolution_sentinel_for_requested_size(requested_size)
    return sentinel.label if sentinel is not None else None


def requested_size_for_sentinel_selection(
    sentinel: ResolutionSentinelCatalogRow | str,
    *,
    unsaved_size: Any = None,
    previous_requested_size: Any = VIEWPORT_SENTINEL_DIMENSIONS,
) -> tuple[int, int]:
    """Return the valid requested size produced by a sentinel-row action.

    The Custom sentinel value is an identity marker, not dimensions to write.
    Selecting it without a positive non-built-in unsaved size preserves the
    previous valid requested size or falls back to Viewport.
    """

    row = resolution_sentinel_by_label(sentinel) if isinstance(sentinel, str) else sentinel
    if row == VIEWPORT_RESOLUTION_SENTINEL:
        return VIEWPORT_SENTINEL_DIMENSIONS
    if row != CUSTOM_RESOLUTION_SENTINEL:
        raise KeyError(row)

    positive_unsaved_size = _strict_positive_size_pair(unsaved_size)
    if (
        positive_unsaved_size is not None
        and positive_unsaved_size not in _PRESETS_BY_DIMENSIONS
    ):
        return positive_unsaved_size

    previous = _strict_integer_pair(previous_requested_size)
    if previous == VIEWPORT_SENTINEL_DIMENSIONS:
        return VIEWPORT_SENTINEL_DIMENSIONS
    positive_previous = _strict_positive_size_pair(previous)
    if positive_previous is not None:
        return positive_previous
    return VIEWPORT_SENTINEL_DIMENSIONS


def default_visible_resolution_presets() -> tuple[ResolutionPresetCatalogRow, ...]:
    """Return the seven Kit fallback visible presets in SRD section 4.4 order."""

    return tuple(
        resolution_preset_by_label(label)
        for label in DEFAULT_VISIBLE_RESOLUTION_PRESET_LABELS
    )


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _coerce_size_pair(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    width = _coerce_positive_int(value[0])
    height = _coerce_positive_int(value[1])
    if width is None or height is None:
        return None
    return (width, height)


def _configured_preset_pairs(value: Any) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    pairs: list[tuple[int, int]] = []
    index = 0
    while index < len(value):
        item = value[index]
        if isinstance(item, (list, tuple)):
            pair = _coerce_size_pair(item)
            if pair is not None:
                pairs.append(pair)
            index += 1
            continue
        if index + 1 >= len(value) or isinstance(value[index + 1], (list, tuple)):
            index += 1
            continue
        pair = _coerce_size_pair((item, value[index + 1]))
        if pair is not None:
            pairs.append(pair)
        index += 2
    return tuple(pairs)


def _read_configured_preset_value(settings: Any) -> tuple[bool, Any]:
    getter = getattr(settings, "get", None)
    if not callable(getter):
        return (False, None)
    try:
        value = getter(SETTING_RESOLUTION_PRESETS, _MISSING)
    except TypeError:
        try:
            value = getter(SETTING_RESOLUTION_PRESETS)
        except (AttributeError, KeyError, TypeError):
            value = _MISSING
    except (AttributeError, KeyError):
        value = _MISSING
    if value is _MISSING:
        return (False, None)
    return (True, value)


def resolve_visible_resolution_presets(
    settings: Any = None,
    *,
    configured_value: Any = _MISSING,
) -> tuple[ResolutionPresetCatalogRow, ...]:
    """Resolve ``viewport.resolution.presets`` into visible recognized rows."""

    if configured_value is _MISSING:
        present = False
        if settings is not None:
            present, configured_value = _read_configured_preset_value(settings)
        if not present:
            return default_visible_resolution_presets()

    visible: list[ResolutionPresetCatalogRow] = []
    seen_dimensions: set[tuple[int, int]] = set()
    for dimensions in _configured_preset_pairs(configured_value):
        row = _PRESETS_BY_DIMENSIONS.get(dimensions)
        if row is None or dimensions in seen_dimensions:
            continue
        visible.append(row)
        seen_dimensions.add(dimensions)
    return tuple(visible)


def format_builtin_resolution_catalog_qa_lines(
    *,
    profile_label: str,
    preset_config_label: str,
    focus_label: str | None = None,
    rows: Iterable[ResolutionPresetCatalogRow] | None = None,
    row_heading: str = "Recognized built-in rows",
    include_badges: bool = False,
    saved_custom_entries: Iterable[Any] | None = None,
) -> tuple[str, ...]:
    """Format the real built-in catalog for the env-gated Area 2 QA scaffold."""

    catalog_rows = tuple(rows) if rows is not None else iter_builtin_resolution_presets()
    title = (
        "A2 Ratio Badge Metadata QA Scaffold"
        if include_badges
        else "A2 Built-In Resolution Catalog QA Scaffold"
    )
    lines = [
        title,
        f"Profile: {profile_label}",
        f"Preset Config: {preset_config_label}",
        f"{row_heading}: {len(catalog_rows)}",
    ]
    if include_badges:
        lines.extend(
            f"{index}. {row.label} {row.resolution_text} | "
            f"badge={row.ratio_badge_label or 'none'} | {row.kind} | "
            f"recognized={str(row.recognized).lower()}"
            for index, row in enumerate(catalog_rows, start=1)
        )
        custom_rows = iter_saved_custom_resolution_badge_rows(saved_custom_entries)
        if custom_rows:
            lines.append(f"Saved custom badge rows: {len(custom_rows)}")
            lines.extend(
                f"Custom {index}. {row.label} {row.resolution_text} | "
                f"badge={row.ratio_badge_label or 'none'} | {row.kind}"
                for index, row in enumerate(custom_rows, start=1)
            )
    else:
        lines.extend(
            f"{index}. {row.label} {row.dimension_text} | {row.kind} | "
            f"recognized={str(row.recognized).lower()}"
            for index, row in enumerate(catalog_rows, start=1)
        )
    if focus_label is not None:
        focused = resolution_preset_by_label(focus_label)
        if include_badges:
            ultra_wide = resolution_preset_by_label("Ultra Wide")
            super_ultra_wide = resolution_preset_by_label("Super Ultra Wide")
            lines.append(
                f"Focused: {focused.label} {focused.resolution_text} "
                f"badge={focused.ratio_badge_label or 'none'}"
            )
            lines.append(
                f"Wide checks: {ultra_wide.label} badge="
                f"{ultra_wide.ratio_badge_label}; {super_ultra_wide.label} "
                f"badge={super_ultra_wide.ratio_badge_label}"
            )
        else:
            lines.append(
                f"Focused: {focused.label} {focused.dimension_text} is recognized; "
                "over-max policy is future Area 7"
            )
    else:
        lines.append(
            "5K Wide is recognized; over-max disable/clamp policy is future Area 7"
        )
    if include_badges:
        lines.append("Ratio badges are metadata only; visual styling is Area 4")
    lines.append("Area 4 owns product menu rendering; no real menu rows yet")
    lines.append("QA scaffold only; Area 4 owns product menu rendering")
    return tuple(lines)


def format_resolution_sentinel_qa_lines(
    *,
    profile_label: str,
    requested_size: Any = VIEWPORT_SENTINEL_DIMENSIONS,
    unsaved_size: Any = None,
    attempted_sentinel_label: str | None = None,
) -> tuple[str, ...]:
    """Format sentinel metadata for the env-gated Area 2 QA scaffold."""

    selected = selected_resolution_sentinel_for_requested_size(requested_size)
    selected_label = selected.label if selected is not None else "None"
    lines = [
        "A2 Viewport and Custom Sentinel QA Scaffold",
        f"Profile: {profile_label}",
        "Sentinel rows: 2",
    ]
    for index, row in enumerate(iter_resolution_sentinel_rows(), start=1):
        selected_text = str(row == selected).lower()
        lines.append(
            f"{index}. {_sentinel_row_text(row)} | {row.kind} | "
            f"{row.meaning} | selected={selected_text}"
        )
    lines.extend(
        [
            f"Current Requested Size: {_requested_size_text(requested_size)}",
            f"Current Label: {selected_label}",
            f"Unsaved Positive Size: {_requested_size_text(unsaved_size)}"
            if _strict_positive_size_pair(unsaved_size) is not None
            else "Unsaved Positive Size: none",
        ]
    )
    if attempted_sentinel_label:
        if attempted_sentinel_label == CUSTOM_RESOLUTION_SENTINEL.label:
            lines.append(
                f"Attempted Sentinel: {attempted_sentinel_label}; "
                "[-1,-1] not applied as requested size"
            )
        else:
            lines.append(
                f"Attempted Sentinel: {attempted_sentinel_label}; "
                "accepted requested size is valid"
            )
    lines.append("Custom sentinel is not the Custom Resolution editor row")
    lines.append("Sentinels are distinct from presets and saved custom rows")
    lines.append("Area 4/5 owns the embedded Custom Resolution editor row")
    lines.append("A2-T04 only maps sentinel selection, no product menu yet")
    return tuple(lines)


def format_saved_custom_resolution_catalog_qa_lines(
    *,
    profile_label: str,
    custom_entries: Iterable[Any] | None,
) -> tuple[str, ...]:
    """Format saved custom catalog rows for the Area 2 QA scaffold."""

    rows = iter_saved_custom_resolution_catalog_rows(custom_entries)
    lines = [
        "A2 Saved Custom Resolution Catalog QA Scaffold",
        f"Profile: {profile_label}",
        "Source: Area-1 normalized viewport.resolution.custom.list",
        f"Saved custom catalog rows: {len(rows)}",
    ]
    lines.extend(
        f"{index}. {row.label} {row.resolution_text} | "
        f"badge={row.ratio_badge_label or 'none'} | {row.kind} | "
        f"source={row.source}"
        for index, row in enumerate(rows, start=1)
    )
    if not rows:
        lines.append("No saved custom catalog rows")
    lines.append("Saved rows are separate from built-ins and sentinels")
    lines.append("Area 1 owns storage and normalization")
    lines.append("Area 4 owns row rendering and delete affordances")
    lines.append("Area 5 owns save/delete behavior")
    return tuple(lines)


def format_resolution_catalog_match_qa_lines(
    *,
    profile_label: str,
    requested_size: Any,
    custom_entries: Iterable[Any] | None,
) -> tuple[str, ...]:
    """Format deterministic match priority for the Area 2 QA scaffold."""

    custom_rows = iter_saved_custom_resolution_catalog_rows(custom_entries)
    match = match_resolution_catalog_row_for_requested_size(
        requested_size,
        saved_custom_entries=custom_entries,
    )
    lines = [
        "A2 Saved Custom and Preset-Duplicate Match QA Scaffold",
        f"Profile: {profile_label}",
        f"Requested Size: {_requested_size_text(requested_size)}",
        f"Priority: {RESOLUTION_MATCH_PRIORITY_DESCRIPTION}",
        f"Saved custom candidates: {len(custom_rows)}",
    ]

    visible_rows: list[
        ResolutionPresetCatalogRow
        | ResolutionSavedCustomCatalogRow
        | ResolutionSentinelCatalogRow
    ] = [
        row
        for row in BUILTIN_RESOLUTION_PRESETS
        if row.dimensions == _strict_positive_size_pair(requested_size)
    ]
    visible_rows.extend(custom_rows)
    if match is not None and match.row == CUSTOM_RESOLUTION_SENTINEL:
        visible_rows.append(CUSTOM_RESOLUTION_SENTINEL)

    seen_keys: set[str] = set()
    row_index = 1
    for row in visible_rows:
        if row.key in seen_keys:
            continue
        seen_keys.add(row.key)
        selected = match is not None and row.key == match.key
        dimensions = (
            row.dimension_text
            if row == CUSTOM_RESOLUTION_SENTINEL
            else row.resolution_text
        )
        badge = row.ratio_badge_label or "none"
        lines.append(
            f"{row_index}. {row.label} {dimensions} | badge={badge} | "
            f"{row.kind} | selected={str(selected).lower()}"
        )
        row_index += 1

    if match is None:
        lines.append("Matched: none")
        lines.append("Selected Row Count: 0")
    else:
        lines.append(
            f"Matched: {match.label} | {match.kind} | source={match.source}"
        )
        lines.append("Selected Row Count: 1")

    if match is not None and match.row == CUSTOM_RESOLUTION_SENTINEL:
        lines.append("Exact match not found; Custom sentinel is selected")
    lines.append("Matching is exact width+height; no tolerance for near sizes")
    lines.append("Area 4/5 consumers use this priority; A2-T07 owns current label")
    return tuple(lines)


def format_resolution_catalog_selection_qa_lines(
    *,
    profile_label: str,
    accepted_requested_size: Any,
    custom_entries: Iterable[Any] | None,
    render_scale: float = 1.0,
    attempted_requested_size: Any = None,
    action_accepted: bool = True,
) -> tuple[str, ...]:
    """Format exactly-one selection proof for the Area 2 QA scaffold."""

    custom_rows = iter_saved_custom_resolution_catalog_rows(custom_entries)
    selection = select_resolution_catalog_row_for_requested_size(
        accepted_requested_size,
        saved_custom_entries=custom_entries,
    )
    visible_rows: list[
        ResolutionSentinelCatalogRow
        | ResolutionPresetCatalogRow
        | ResolutionSavedCustomCatalogRow
    ] = [VIEWPORT_RESOLUTION_SENTINEL]
    visible_rows.extend(BUILTIN_RESOLUTION_PRESETS)
    visible_rows.extend(custom_rows)
    visible_rows.append(CUSTOM_RESOLUTION_SENTINEL)

    selected_count = (
        sum(1 for row in visible_rows if selection is not None and row.key == selection.key)
    )
    lines = [
        "A2 Selected Row and Current Label QA Scaffold",
        f"Profile: {profile_label}",
        f"Accepted Requested Size: {_requested_size_text(accepted_requested_size)}",
        f"Current Label: {selection.current_label if selection else 'None'}",
        f"Render Scale Control: {render_scale:g}",
        f"Selection Key: {RESOLUTION_SELECTION_KEYING_DESCRIPTION}",
        "Effective size preview is ignored by selection; Area 3 owns math",
    ]
    if selection is None:
        lines.append("Selected Row Count: 0")
        lines.append("Selected Row: none")
    else:
        lines.append(f"Selected Row Count: {selected_count}")
        lines.append(
            f"Selected Row: {selection.label} | {selection.kind} | "
            f"source={selection.source} | selected=true"
        )
    if attempted_requested_size is not None:
        lines.append(
            f"Attempted Requested Size: {_requested_size_text(attempted_requested_size)} "
            f"| accepted={str(action_accepted).lower()}"
        )
        if not action_accepted:
            lines.append("Rejected action left previous accepted selection unchanged")

    for index, row in enumerate(visible_rows, start=1):
        selected = selection is not None and row.key == selection.key
        if row.kind == RESOLUTION_CATALOG_KIND_SENTINEL:
            dimensions = row.dimension_text
        else:
            dimensions = row.resolution_text
        lines.append(
            f"{index}. {row.label} {dimensions} | "
            f"badge={row.ratio_badge_label or 'none'} | {row.kind} | "
            f"selected={str(selected).lower()}"
        )

    lines.append("Area 4 renders checkmarks/current labels; Area 6 syncs live menus")
    lines.append("A2-T07 maps accepted state only; no optimistic selection")
    return tuple(lines)


__all__ = [
    "BUILTIN_RESOLUTION_PRESETS",
    "CUSTOM_RESOLUTION_SENTINEL",
    "CUSTOM_SENTINEL_DIMENSIONS",
    "DEFAULT_VISIBLE_RESOLUTION_PRESET_LABELS",
    "KNOWN_RESOLUTION_RATIO_BADGES",
    "RESOLUTION_CATALOG_KIND_CUSTOM",
    "RESOLUTION_CATALOG_KIND_PRESET",
    "RESOLUTION_CATALOG_KIND_SAVED_CUSTOM",
    "RESOLUTION_CATALOG_KIND_SENTINEL",
    "RESOLUTION_MATCH_PRIORITY_DESCRIPTION",
    "RESOLUTION_MATCH_SOURCE_BUILTIN",
    "RESOLUTION_MATCH_SOURCE_SAVED_CUSTOM",
    "RESOLUTION_MATCH_SOURCE_SENTINEL",
    "RESOLUTION_SELECTION_KEYING_DESCRIPTION",
    "RESOLUTION_PRESET_SOURCE_SRD_4_4",
    "RESOLUTION_RATIO_BADGE_TOLERANCE",
    "RESOLUTION_SAVED_CUSTOM_SOURCE_SETTING",
    "RESOLUTION_SENTINEL_CUSTOM_KEY",
    "RESOLUTION_SENTINEL_ROWS",
    "RESOLUTION_SENTINEL_SOURCE_SRD_4_3",
    "RESOLUTION_SENTINEL_VIEWPORT_KEY",
    "ResolutionBadgeMetadata",
    "ResolutionCatalogMatch",
    "ResolutionCatalogSelection",
    "ResolutionPresetCatalogRow",
    "ResolutionSavedCustomBadgeRow",
    "ResolutionSavedCustomCatalogRow",
    "ResolutionSentinelCatalogRow",
    "VIEWPORT_RESOLUTION_SENTINEL",
    "VIEWPORT_SENTINEL_DIMENSIONS",
    "current_resolution_label_for_requested_size",
    "default_visible_resolution_presets",
    "format_builtin_resolution_catalog_qa_lines",
    "format_resolution_catalog_match_qa_lines",
    "format_resolution_catalog_selection_qa_lines",
    "format_resolution_sentinel_qa_lines",
    "format_saved_custom_resolution_catalog_qa_lines",
    "iter_builtin_resolution_presets",
    "iter_resolution_sentinel_rows",
    "iter_saved_custom_resolution_badge_rows",
    "iter_saved_custom_resolution_catalog_rows",
    "match_resolution_catalog_row_for_requested_size",
    "requested_size_for_sentinel_selection",
    "resolution_preset_by_label",
    "resolution_badge_metadata",
    "resolution_sentinel_by_label",
    "resolve_visible_resolution_presets",
    "select_resolution_catalog_row_for_requested_size",
    "select_resolution_catalog_row_for_state",
    "selected_resolution_sentinel_for_requested_size",
]
