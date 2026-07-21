# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""3D viewport widget with a real tool toolbar and layered viewport body.

ViewportWidget hosts the RTX render surface and delegates GPU calls to
the RendererAdapter. A SceneView layer provides camera, pick gestures,
and the existing transform manipulator.
"""

import asyncio
import inspect
import math
import os
import sys
import time
import weakref
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

import omni.ui as ui
from omni.ui_scene import scene as sc
from ovui_data_adapters.common import (
    VIEWPORT_CAMERA_POSE_SOURCE,
    BoundCameraPose,
    RendererAdapter,
    is_viewport_camera_pose_change_event,
)

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.managed_window import ManagedWindow
from ovui_widgets.common.menu import (
    CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER,
    FILL_VIEWPORT_CHECKBOX_HOTKEY_MARKER,
    RENDER_SCALE_COMBO_HOTKEY_MARKER,
    SAVED_CUSTOM_DELETE_HOTKEY_MARKER,
    create_flat_menu,
    register_menu_control_callback,
    unregister_menu_control_callback,
)
from ovui_widgets.common.selection import SelectionChangedEvent
from ovui_widgets.viewport import _livestream_status_overlay as _ls_overlay
from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_flight_keyboard import (
    FLY_SPEED_SETTING,
    FlightModeKeyboard,
)
from ovui_widgets.viewport.camera_inertia import (
    DEFAULT_TIME_CONSTANT as DEFAULT_TUMBLE_INERTIA,
)
from ovui_widgets.viewport.camera_inertia import (
    TUMBLE_INERTIA_SETTING,
    TumbleInertia,
)
from ovui_widgets.viewport.camera_manipulator import (
    CameraManipulator,
    CameraManipulatorModel,
)
from ovui_widgets.viewport.camera_navigation_state import CameraNavigationState
from ovui_widgets.viewport.image_bridge import ImageBridge
from ovui_widgets.viewport.manipulator_registry import ACTIVE_TOOL_SETTING, ToolRegistry
from ovui_widgets.viewport.pick_gesture import (
    MOD_CTRL,
    MOD_NONE,
    MOD_SHIFT,
    GizmoAwarePickManager,
    PickGesture,
    PickRectGesture,
)
from ovui_widgets.viewport.prim_transform_model import PrimTransformModel
from ovui_widgets.viewport.resolution_catalog import (
    BUILTIN_RESOLUTION_PRESETS,
    CUSTOM_RESOLUTION_SENTINEL,
    RESOLUTION_CATALOG_KIND_PRESET,
    RESOLUTION_CATALOG_KIND_SAVED_CUSTOM,
    VIEWPORT_RESOLUTION_SENTINEL,
    VIEWPORT_SENTINEL_DIMENSIONS,
    format_builtin_resolution_catalog_qa_lines,
    format_resolution_catalog_match_qa_lines,
    format_resolution_catalog_selection_qa_lines,
    format_resolution_sentinel_qa_lines,
    format_saved_custom_resolution_catalog_qa_lines,
    iter_saved_custom_resolution_catalog_rows,
    match_resolution_catalog_row_for_requested_size,
    requested_size_for_sentinel_selection,
    resolve_visible_resolution_presets,
    select_resolution_catalog_row_for_requested_size,
    select_resolution_catalog_row_for_state,
)
from ovui_widgets.viewport.resolution_coordinates import (
    apply_aspect_fit_projection_transform,
    compute_aspect_fit_display_rect,
    map_widget_ndc_rect_to_render_ndc_rect,
    map_widget_ndc_to_render_ndc,
)
from ovui_widgets.viewport.resolution_effective import (
    FixedModeEffectiveResolution,
    ViewportModeEffectiveResolution,
    compute_fixed_mode_effective_resolution_for_state,
    compute_viewport_mode_effective_resolution_for_state,
    ensure_safe_renderer_request_size,
    format_viewport_effective_resolution_qa_lines,
)
from ovui_widgets.viewport.resolution_settings import (
    SETTING_CUSTOM_RESOLUTION_LIST,
    SETTING_DEFAULT_FILL_VIEWPORT,
    SETTING_DEFAULT_RESOLUTION,
    SETTING_DEFAULT_RESOLUTION_SCALE,
    SETTING_RENDER_SCALE_LIST,
    SETTING_RESOLUTION_PRESETS,
    ResolutionSettingsChange,
    ViewportResolutionSettings,
    add_shared_custom_resolution_entry,
    format_resolution_settings_qa_lines,
    normalize_loaded_custom_resolution_list,
    resolve_viewport_resolution_settings,
    subscribe_resolution_settings_changes,
    viewport_fill_viewport_key,
    viewport_resolution_key,
    viewport_resolution_scale_key,
    write_shared_custom_resolution_list,
    write_viewport_instance_fill_viewport,
    write_viewport_instance_resolution,
    write_viewport_instance_resolution_scale,
)
from ovui_widgets.viewport.resolution_state import (
    RESOLUTION_MODE_FIXED,
    RESOLUTION_MODE_VIEWPORT,
    AvailabilityChangedCallback,
    ResolutionClampLimits,
    ResolutionStateChangedCallback,
    ViewportAvailabilitySnapshot,
    ViewportAvailabilitySubscription,
    ViewportResolutionState,
    ViewportResolutionStateSubscription,
)
from ovui_widgets.viewport.toolbar_hooks import (
    ViewportStatusBadge,
    ViewportToolbarAction,
    ViewportToolbarHandle,
    ViewportToolbarMenu,
    ViewportToolbarRegistry,
)
from ovui_widgets.viewport.transform_manipulator import (
    TOOL_ROTATE,
    TOOL_SCALE,
    TOOL_TRANSLATE,
    VALID_TOOLS,
    TransformManipulator,
)
from ovui_widgets.viewport.viewport_hooks import (
    ViewportContributionRegistry,
    ViewportFrameContext,
    ViewportProbeContext,
    ViewportProbeResult,
)

_TOOLBAR_TOOL_SPECS = (
    (TOOL_TRANSLATE, "Move", "W", "viewport_tool_move"),
    (TOOL_ROTATE, "Rotate", "E", "viewport_tool_rotate"),
    (TOOL_SCALE, "Scale", "R", "viewport_tool_scale"),
)
_TOOLBAR_CAMERA_KEY = "camera"
_TOOLBAR_CAMERA_MENU_TITLE = "Camera"
_TOOLBAR_NO_CAMERAS_LABEL = "(no cameras)"
_TOOLBAR_ICON_PROVIDERS: dict[str, "ui.RasterImageProvider"] = {}
FOUNDATION_QA_PRE_TOOLS_PLACEHOLDER_ENV = (
    "OVUI_VIEWPORT_FOUNDATION_QA_PRETOOLS_PLACEHOLDER"
)
AREA1_SETTINGS_SCHEMA_QA_ENV = "OVUI_VIEWPORT_A1_SETTINGS_SCHEMA_QA"
AREA1_TWO_VIEWPORT_QA_ENV = "OVUI_VIEWPORT_A1_TWO_VIEWPORT_QA"
AREA1_PERSISTENCE_QA_ENV = "OVUI_VIEWPORT_A1_PERSISTENCE_QA"
AREA1_SETTINGS_NOTIFICATION_QA_ENV = "OVUI_VIEWPORT_A1_SETTINGS_NOTIFICATION_QA"
AREA2_CATALOG_QA_ENV = "OVUI_VIEWPORT_A2_CATALOG_QA"
AREA3_RENDER_QA_ENV = "OVUI_VIEWPORT_A3_RENDER_QA"
AREA3_INTERACTION_QA_ENV = "OVUI_VIEWPORT_A3_INTERACTION_QA"
AREA3_OPENUSD_SESSION_QA_ENV = "OVUI_VIEWPORT_A3_OPENUSD_SESSION_QA"
AREA7_MENU_FAILURE_QA_ENV = "OVUI_VIEWPORT_A7_MENU_FAILURE_QA"
AREA7_MISSING_ICON_QA_ENV = "OVUI_VIEWPORT_A7_MISSING_ICON_QA"
AREA7_OVUI_ONLY_RUNTIME_QA_ENV = "OVUI_VIEWPORT_A7_OVUI_ONLY_RUNTIME_QA"
VIEWPORT_RESOLUTION_ATTACHMENT_ID = "viewport.resolution"
_SETTINGS_TOOLBAR_WIDGET = "viewport_toolbar_settings"
_SETTINGS_TOOLBAR_ICON_NAME = "content_gear"
_SETTINGS_TOOLBAR_FALLBACK_ICON_NAME = "content_filter"
_SETTINGS_MENU_VIEWPORT_LABEL = "Viewport"
_VIEWPORT_MENU_RENDER_RESOLUTION_LABEL = "Render Resolution"
_VIEWPORT_MENU_CUSTOM_RESOLUTION_LABEL = "Custom Resolution"
_VIEWPORT_MENU_RENDER_SCALE_LABEL = "Render Scale"
_VIEWPORT_MENU_FILL_VIEWPORT_LABEL = "Fill Viewport"
_VIEWPORT_MENU_FILL_VIEWPORT_DISABLED_REASON = (
    "Disabled while Render Resolution is Viewport"
)
_RESOLUTION_UNAVAILABLE_NO_RENDERER_REASON = "Resolution unavailable: no renderer"
_RESOLUTION_UNAVAILABLE_SETTINGS_REASON = (
    "Resolution unavailable: settings service"
)
_RESOLUTION_UNAVAILABLE_NO_STAGE_REASON = "Resolution unavailable: no stage loaded"
_RESOLUTION_UNAVAILABLE_FIXED_UNSUPPORTED_REASON = (
    "Resolution unavailable: fixed resolution unsupported"
)
_RESOLUTION_OVER_MAX_PRESET_REASON_TEMPLATE = (
    "Resolution unavailable: max {max_width}x{max_height}"
)
_RESOLUTION_MAX_CLAMP_WARNING_TEMPLATE = "Clamped to maximum {max_width}x{max_height}."
_RESOLUTION_CORRUPT_CUSTOM_LIST_WARNING = "Some saved custom resolutions were ignored."
_RESOLUTION_MENU_FAILURE_REASON = "Resolution menu unavailable: data refresh failed"
_RESOLUTION_MISSING_ICON_PROFILE_LABEL = "A7 missing-icon profile active"
_RESOLUTION_OVUI_ONLY_PROFILE_LABEL = "A7 ovui-only runtime profile active"
_CUSTOM_RESOLUTION_SAVE_DIALOG_TITLE = "Save Custom Viewport Resolution"
_CUSTOM_RESOLUTION_SAVE_DIALOG_WIDTH = 400
_CUSTOM_RESOLUTION_SAVE_DIALOG_HEIGHT = 210
_KEY_ESCAPE = 256
_KEY_ENTER = 257
_KEY_KEYPAD_ENTER = 335
_IMGUI_KEY_ENTER = 525
_IMGUI_KEY_ESCAPE = 526
_IMGUI_KEY_KEYPAD_ENTER = 627
_CUSTOM_RESOLUTION_SAVE_DIALOG_EMPTY_NAME_ERROR = "Name is required."
_CUSTOM_RESOLUTION_SAVE_DIALOG_DUPLICATE_NAME_ERROR = "Name already exists."
_CUSTOM_RESOLUTION_SAVE_DIALOG_DUPLICATE_DIMENSIONS_ERROR = (
    "Resolution already exists."
)
_FOUNDATION_QA_PRE_TOOLS_PLACEHOLDER_WIDGET = (
    "viewport_toolbar_pre_tools_host_placeholder"
)


def _format_render_scale_percent(render_scale: float) -> str:
    percent = float(render_scale) * 100.0
    rounded = round(percent)
    if abs(percent - rounded) < 0.005:
        return f"{int(rounded)}%"
    return f"{percent:.2f}".rstrip("0").rstrip(".") + "%"


def _render_scale_combo_hotkey_payload(
    *,
    option_labels: tuple[str, ...],
    current_index: int,
    callback_token: str = "",
) -> str:
    callback_segment = f"|{callback_token}" if callback_token else ""
    return (
        f"{RENDER_SCALE_COMBO_HOTKEY_MARKER}|"
        f"{int(current_index)}{callback_segment}|{','.join(option_labels)}"
    )


def _custom_resolution_editor_hotkey_payload(
    *,
    callback_token: str = "",
    apply_callback_token: str = "",
    save_enabled_callback_token: str = "",
    default_size: tuple[int, int] | None = None,
    bounds: tuple[int, int, int, int] | None = None,
) -> str:
    default_segment = ""
    if default_size is not None:
        try:
            default_width, default_height = int(default_size[0]), int(default_size[1])
        except (TypeError, ValueError, IndexError):
            default_width = default_height = 0
        if default_width > 0 and default_height > 0:
            default_segment = f"|{default_width}|{default_height}"
    bounds_segment = ""
    if bounds is not None:
        try:
            min_width, min_height, max_width, max_height = (
                int(bounds[0]),
                int(bounds[1]),
                int(bounds[2]),
                int(bounds[3]),
            )
        except (TypeError, ValueError, IndexError):
            min_width = min_height = max_width = max_height = 0
        if (
            min_width > 0
            and min_height > 0
            and max_width >= min_width
            and max_height >= min_height
        ):
            bounds_segment = (
                f"|{min_width}|{min_height}|{max_width}|{max_height}"
            )
    if (
        not callback_token
        and not apply_callback_token
        and not save_enabled_callback_token
        and not default_segment
        and not bounds_segment
    ):
        return CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER
    if (
        callback_token
        and not apply_callback_token
        and not save_enabled_callback_token
        and not default_segment
        and not bounds_segment
    ):
        return f"{CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER}|{callback_token}"
    save_enabled_segment = (
        f"|{save_enabled_callback_token}" if save_enabled_callback_token else ""
    )
    return (
        f"{CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER}|"
        f"{callback_token}|{apply_callback_token}{default_segment}"
        f"{bounds_segment}{save_enabled_segment}"
    )


def _fill_viewport_checkbox_hotkey_payload(
    *,
    enabled: bool,
    checked: bool,
    callback_token: str = "",
) -> str:
    callback_segment = f"|{callback_token}" if callback_token else ""
    return (
        f"{FILL_VIEWPORT_CHECKBOX_HOTKEY_MARKER}|"
        f"{int(bool(enabled))}|{int(bool(checked))}{callback_segment}"
    )


def _saved_custom_delete_hotkey_payload(
    *,
    detail_text: str,
    callback_token: str = "",
) -> str:
    return (
        f"{SAVED_CUSTOM_DELETE_HOTKEY_MARKER}|"
        f"{callback_token}|{str(detail_text)}"
    )


DEFAULT_VIEWPORT_ID = "main"
_AREA1_QA_PROFILE_NO_SAVED = "No saved resolution settings"
_AREA1_QA_PROFILE_MISSING_KEYS = "Missing resolution keys"
_AREA1_QA_PROFILE_DPI_UNAVAILABLE = "DPI unavailable"
_AREA1_QA_PROFILE_SHARED_DEFAULTS_720P = "Shared defaults 1280x720"
_AREA1_QA_PROFILE_INSTANCE_SCALE_100 = "Instance scale override 100%"
_AREA1_QA_PROFILE_INSTANCE_SCALE_50 = "Instance scale override 50%"
_AREA1_QA_PROFILE_REMOVED = "Shared profile removed"
_AREA1_QA_PROFILE_INSTANCE_1080P_50 = "Viewport instance 1920x1080 50%"
_AREA1_QA_PROFILE_INSTANCE_FILL_TRUE = "Viewport instance Fill true"
_AREA1_QA_PROFILE_SHARED_CUSTOM = "Shared custom item added"
_AREA1_QA_PROFILE_CUSTOM_ENTRY_ADDED = "Custom list entry added"
_AREA1_QA_PROFILE_CUSTOM_ENTRY_REJECTED = "Rejected invalid custom list entry"
_AREA1_QA_PROFILE_VALID_CUSTOM_LIST = "Valid Custom List"
_AREA1_QA_PROFILE_MALFORMED_CUSTOM_LIST = "Malformed Custom List"
_AREA1_QA_PROFILE_ALL_CUSTOM_INVALID = "All Custom Entries Invalid"
_AREA1_QA_PROFILE_PERSISTENT = "Persistent Profile"
_AREA1_QA_PROFILE_INVALID_PERSISTED = "Invalid Persisted Profile"
_AREA6_QA_PROFILE_SCALE_OPTIONS_75 = "A6 render-scale options 100/75/50"
_AREA6_QA_PROFILE_SCALE_OPTIONS_25 = "A6 render-scale options 100/25"
_AREA6_QA_PROFILE_VIEWPORT_MODE = "A6 viewport mode [0,0]"
_AREA2_QA_PROFILE_INITIAL = "Initial catalog QA"
_AREA2_QA_PROFILE_FULL_LIBRARY = "Full recognized preset library"
_AREA2_QA_PROFILE_FIVE_K_FOCUSED = "5K Wide focused"
_AREA2_QA_PROFILE_EMPTY_PRESET_CONFIG = "Empty/absent preset config"
_AREA2_QA_PROFILE_DEFAULT_PRESET_ABSENT = "Default preset setting absent"
_AREA2_QA_PROFILE_FULL_PRESET_SETTING = "Full preset setting"
_AREA2_QA_PROFILE_MALFORMED_PRESET_LIST = "Malformed preset list"
_AREA2_QA_PROFILE_BADGE_DETAILS = "Ratio badge details"
_AREA2_QA_PROFILE_WIDE_BADGES = "Wide ratio badge focus"
_AREA2_QA_PROFILE_REVIEW_CUSTOM_BADGE = "Review custom ratio badge"
_AREA2_QA_PROFILE_NEAR_21_9_CUSTOM_BADGE = "Near 21:9 custom ratio badge"
_AREA2_QA_PROFILE_SENTINEL_VIEW = "Sentinel view"
_AREA2_QA_PROFILE_SENTINEL_VIEWPORT_SELECTED = "Viewport sentinel selected"
_AREA2_QA_PROFILE_SENTINEL_CUSTOM_SELECTED = "Custom sentinel selected"
_AREA2_QA_PROFILE_SENTINEL_CUSTOM_WITHOUT_SIZE = "Custom sentinel without size"
_AREA2_QA_PROFILE_SAVED_CUSTOM_CATALOG = "Saved custom catalog rows"
_AREA2_QA_PROFILE_TWO_SAVED_CUSTOMS = "Two saved custom catalog rows"
_AREA2_QA_PROFILE_MALFORMED_SAVED_CUSTOMS = "Malformed saved custom catalog rows"
_AREA2_QA_PROFILE_MATCH_HD_COPY = "Match HD Copy preset duplicate"
_AREA2_QA_PROFILE_MATCH_REVIEW = "Match saved custom Review"
_AREA2_QA_PROFILE_MATCH_NEAR_SIZE = "Match near non-exact size"
_AREA2_QA_PROFILE_MATCH_DUPLICATE_SAVED = "Match duplicate saved customs"
_AREA2_QA_PROFILE_SELECTION_INITIAL = "Selection QA initial"
_AREA2_QA_PROFILE_SELECTION_VIEWPORT = "Selection Viewport"
_AREA2_QA_PROFILE_SELECTION_HD1080P = "Selection HD1080P"
_AREA2_QA_PROFILE_SELECTION_SCALE_50 = "Selection scale 50%"
_AREA2_QA_PROFILE_SELECTION_REVIEW = "Selection Review"
_AREA2_QA_PROFILE_SELECTION_CUSTOM = "Selection Custom 1921x1080"
_AREA2_QA_PROFILE_SELECTION_REJECTED = "Selection rejected action"
_AREA3_QA_PROFILE_INITIAL = "Viewport render QA initial"
_AREA3_QA_PROFILE_FRAME_1280_720 = "Viewport frame 1280x720"
_AREA3_QA_PROFILE_FRAME_800_450 = "Viewport frame 800x450"
_AREA3_QA_PROFILE_FRAME_800_600 = "Viewport frame 800x600"
_AREA3_QA_PROFILE_MISSING_SETTINGS = "Missing resolution settings"
_AREA3_QA_PROFILE_FIXED_HD1080P_100 = "Fixed HD1080P 100%"
_AREA3_QA_PROFILE_FIXED_HD1080P_50 = "Fixed HD1080P 50%"
_AREA3_QA_PROFILE_FIXED_HD1080P_50_RESIZED = "Fixed HD1080P 50% resized frame"
_AREA3_QA_PROFILE_DPI_ENABLED_D2 = "DPI enabled D=2"
_AREA3_QA_PROFILE_DPI_UNAVAILABLE = "DPI unavailable"
_AREA3_QA_PROFILE_FIXED_FRACTIONAL_50 = "Fixed 1501x1001 50%"
_AREA3_QA_PROFILE_ICON_25 = "Icon 25% bounds"
_AREA3_QA_PROFILE_TINY_MIN_CLAMP = "Tiny 50x40 min clamp"
_AREA3_QA_PROFILE_UHD_200 = "UHD 200% max clamp"
_AREA3_QA_PROFILE_INVALID_REJECTED = "Invalid 0x-1 rejected"
_AREA3_QA_PROFILE_FRAME_1600_900 = "Viewport frame 1600x900"
_AREA3_QA_PROFILE_SQUARE_FILL_OFF = "Square 100% Fill off"
_AREA3_QA_PROFILE_SQUARE_FILL_ON = "Square 100% Fill on"
_AREA3_QA_PROFILE_SQUARE_FILL_ON_50 = "Square Fill on 50%"
_AREA3_QA_PROFILE_VIEWPORT_AFTER_FILL = "Viewport mode after Fill"
_AREA3_QA_PROFILE_OPENUSD_SESSION = "OpenUSD session RenderProduct"
_AREA3_QA_PROFILE_INTERACTION_INITIAL = "Interaction alignment QA"
_AREA3_QA_PROFILE_INTERACTION_SQUARE_FILL_OFF = "Interaction Square Fill off"
_AREA3_QA_PROFILE_INTERACTION_FILL_ON = "Interaction Fill on"
_AREA3_QA_OPENUSD_SESSION_STATUS = (
    "OpenUSD-backed profile: committed effective size authors the session "
    "RenderProduct; Area 8 owns final root-layer acceptance"
)
_AREA3_QA_INTERACTION_STATUS = (
    "A3-T08 interaction QA: clicks are mapped through the aspect-fit display "
    "rect; side spacing is outside render bounds and must not pick-as-stretched"
)
_AREA2_QA_DEFAULT_PRESET_CONFIG = "current Area-1 preset setting"
_AREA2_QA_EMPTY_PRESET_CONFIG = "viewport.resolution.presets empty/absent"
_AREA2_QA_DEFAULT_PRESET_ABSENT_CONFIG = "viewport.resolution.presets absent"
_AREA2_QA_FULL_PRESET_CONFIG = "viewport.resolution.presets full recognized dimensions"
_AREA2_QA_MALFORMED_PRESET_CONFIG = "viewport.resolution.presets malformed/unknown mixed list"
_AREA2_QA_BADGE_DETAILS_CONFIG = "ratio badge metadata for recognized rows"
_AREA2_QA_REVIEW_CUSTOM_CONFIG = "saved custom Review 1500x1000 badge profile"
_AREA2_QA_NEAR_21_9_CUSTOM_CONFIG = "saved custom Near 21:9 3440x1440 badge profile"
_AREA2_QA_SENTINEL_CONFIG = "Viewport [0,0] and Custom [-1,-1] sentinel rows"
_AREA2_QA_SAVED_CUSTOM_CATALOG_CONFIG = "Area-1 normalized saved custom rows"
_AREA2_QA_TWO_CUSTOMS_CONFIG = "Review 1500x1000 and Portrait 1080x1920"
_AREA2_QA_MALFORMED_CUSTOMS_CONFIG = "A1 malformed custom-list profile"
_AREA2_QA_MATCH_HD_COPY_CONFIG = "HD Copy 1920x1080 saved duplicate"
_AREA2_QA_MATCH_REVIEW_CONFIG = "Review 1500x1000 saved custom match"
_AREA2_QA_MATCH_NEAR_SIZE_CONFIG = "1921x1080 exact-match negative path"
_AREA2_QA_MATCH_DUPLICATE_CONFIG = "A1 duplicate saved custom profile"
_AREA2_QA_SELECTION_CONFIG = "accepted requested-size selection and label"
_AREA2_QA_UNSAVED_CUSTOM_SIZE = (1500, 1000)
_AREA2_QA_NEAR_HD1080P_SIZE = (1921, 1080)
_AREA2_QA_HD1080P_SIZE = (1920, 1080)
_AREA3_QA_FRACTIONAL_SIZE = (1501, 1001)
_AREA3_QA_ICON_SIZE = (512, 512)
_AREA3_QA_TINY_SIZE = (50, 40)
_AREA3_QA_UHD_SIZE = (3840, 2160)
_AREA3_QA_INVALID_SIZE = (0, -1)
_AREA3_QA_FILL_FRAME_SIZE = (1600, 900)
_AREA3_QA_SQUARE_SIZE = (1024, 1024)
_AREA2_QA_REJECTED_ACTION_SIZE = (-1, -1)
_AREA1_QA_SHARED_CUSTOM_ITEM = {
    "name": "Shared Review",
    "width": 1500,
    "height": 1000,
}
_AREA1_QA_VALID_CUSTOM_LIST = [
    {"name": "Preview Square", "width": 1500, "height": 1500},
    {"name": "Client 4K", "width": 3840, "height": 2160},
]
_AREA1_QA_MALFORMED_CUSTOM_LIST = [
    {"name": "Only Valid", "width": 1600, "height": 900},
    {"width": 1200, "height": 800},
    {"name": "   ", "width": 1200, "height": 800},
    {"name": 123, "width": 1200, "height": 800},
    {"name": "Zero Width", "width": 0, "height": 800},
    {"name": "Negative Height", "width": 1200, "height": -1},
    {"name": "String Width", "width": "1200", "height": 800},
    {"name": "Bool Width", "width": True, "height": 800},
    ["Unsupported", 1200, 800],
    {"name": "Only Valid", "width": 1700, "height": 900},
    {"name": "Duplicate Dimensions", "width": 1600, "height": 900},
]
_AREA1_QA_ALL_INVALID_CUSTOM_LIST = [
    {"name": "", "width": 1200, "height": 800},
    {"name": "Missing Width", "height": 800},
    {"name": "Missing Height", "width": 1200},
    {"name": "Float Width", "width": 1200.0, "height": 800},
    {"name": "False Width", "width": False, "height": 800},
    "unsupported",
]
_AREA1_QA_PERSISTENT_INVALID_CUSTOM_LIST = [
    {"name": "Valid Persisted", "width": 1600, "height": 900},
    {"name": "", "width": 1200, "height": 800},
    {"name": "Missing Width", "height": 800},
    {"name": "Non Positive", "width": 0, "height": 800},
    {"name": "String Width", "width": "1200", "height": 800},
    {"name": "Valid Persisted", "width": 1700, "height": 900},
    {"name": "Duplicate Dimensions", "width": 1600, "height": 900},
    ["Unsupported", 1200, 800],
]
_AREA6_QA_RENDER_SCALE_OPTIONS_75 = [1.0, 0.75, 0.5]
_AREA6_QA_RENDER_SCALE_OPTIONS_25 = [1.0, 0.25]
_AREA2_QA_MALFORMED_PRESET_SETTING = (
    [3840, 2160],
    [9999, 9999],
    "bad",
    [1280, 720],
    [1280, 720],
    [3440, 1440],
    [0, 720],
    [5120, 2880],
    [512, 512],
    [False, 512],
)
_AREA2_QA_REVIEW_CUSTOM = {
    "name": "Review",
    "width": 1500,
    "height": 1000,
}
_AREA2_QA_HD_COPY_CUSTOM = {
    "name": "HD Copy",
    "width": 1920,
    "height": 1080,
}
_AREA2_QA_DUPLICATE_REVIEW_CUSTOMS = [
    {"name": "Review", "width": 1500, "height": 1000},
    {"name": "Review", "width": 1700, "height": 1000},
    {"name": "Review Duplicate Dimensions", "width": 1500, "height": 1000},
]
_AREA2_QA_NEAR_21_9_CUSTOM = {
    "name": "Near 21:9",
    "width": 3440,
    "height": 1440,
}
_AREA2_QA_PORTRAIT_CUSTOM = {
    "name": "Portrait",
    "width": 1080,
    "height": 1920,
}
_AREA1_QA_SHARED_SETTINGS_DATA: dict[str, Any] = {}
_AREA1_QA_ACTIVE_VIEWPORTS: "weakref.WeakSet[Any]" = weakref.WeakSet()
_VIEWPORT_ID_ACTIVE: dict[str, weakref.ReferenceType[Any]] = {}
_RESOLUTION_HOST_CONTRIBUTION_TYPES = (
    ViewportToolbarAction,
    ViewportToolbarMenu,
    ViewportStatusBadge,
)


class _ResolutionSettingsSchemaQAStore:
    """Minimal settings surface used only by the visible Area-1 QA scaffold."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def unset(self, key: str) -> None:
        self._data.pop(key, None)


def _refresh_area1_settings_schema_qa_windows() -> None:
    for viewport in tuple(_AREA1_QA_ACTIVE_VIEWPORTS):
        refresh = getattr(viewport, "_refresh_resolution_settings_schema_qa_window", None)
        if callable(refresh):
            refresh()


def _toolbar_icon_provider(path: str) -> "ui.RasterImageProvider":
    provider = _TOOLBAR_ICON_PROVIDERS.get(path)
    if provider is None:
        provider = ui.RasterImageProvider(path)
        _TOOLBAR_ICON_PROVIDERS[path] = provider
    return provider


def _matrix_rows(matrix: Any) -> list[list[float]]:
    if hasattr(matrix, "tolist"):
        matrix = matrix.tolist()
    values = list(matrix)
    if len(values) == 16 and not isinstance(values[0], (list, tuple)):
        return [[float(values[row * 4 + col]) for col in range(4)] for row in range(4)]
    return [[float(value) for value in row] for row in values]


def _mat_vec_mul(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [
        sum(float(matrix[row][col]) * float(vector[col]) for col in range(4))
        for row in range(4)
    ]


def _mat_mul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [
        [
            sum(float(left[row][k]) * float(right[k][col]) for k in range(4))
            for col in range(4)
        ]
        for row in range(4)
    ]


def _invert_matrix_4x4(matrix: list[list[float]]) -> Optional[list[list[float]]]:
    size = 4
    augmented = [
        [float(matrix[row][col]) for col in range(size)]
        + [1.0 if row == col else 0.0 for col in range(size)]
        for row in range(size)
    ]
    for col in range(size):
        pivot_row = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot_row][col]) < 1.0e-12:
            return None
        if pivot_row != col:
            augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        augmented[col] = [value / pivot for value in augmented[col]]
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0.0:
                continue
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[col])
            ]
    return [row[size:] for row in augmented]


def _homogeneous_to_xyz(vector: list[float]) -> Optional[tuple[float, float, float]]:
    w = float(vector[3])
    if abs(w) < 1.0e-8:
        return None
    return (float(vector[0]) / w, float(vector[1]) / w, float(vector[2]) / w)


def _normalize3(vector: tuple[float, float, float]) -> Optional[tuple[float, float, float]]:
    length = math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)
    if length < 1.0e-12:
        return None
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _dot3(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _closest_point_on_axis_to_ray(
    axis_origin: tuple[float, float, float],
    axis: tuple[float, float, float],
    ray_origin: tuple[float, float, float],
    ray_direction: tuple[float, float, float],
) -> tuple[float, float, float]:
    unit_axis = _normalize3(axis) or (1.0, 0.0, 0.0)
    w0 = (
        axis_origin[0] - ray_origin[0],
        axis_origin[1] - ray_origin[1],
        axis_origin[2] - ray_origin[2],
    )
    a = _dot3(unit_axis, unit_axis)
    b = _dot3(unit_axis, ray_direction)
    c = _dot3(ray_direction, ray_direction)
    d = _dot3(unit_axis, w0)
    e = _dot3(ray_direction, w0)
    denom = a * c - b * b
    if abs(denom) < 1.0e-8:
        distance = -d / max(a, 1.0e-8)
    else:
        distance = (b * e - c * d) / denom
    return (
        axis_origin[0] + unit_axis[0] * distance,
        axis_origin[1] + unit_axis[1] * distance,
        axis_origin[2] + unit_axis[2] * distance,
    )


def _point_to_segment_distance(
    x: float,
    y: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length_sq = dx * dx + dy * dy
    if length_sq <= 1.0e-8:
        return math.hypot(x - sx, y - sy)
    t = max(0.0, min(1.0, ((x - sx) * dx + (y - sy) * dy) / length_sq))
    px = sx + t * dx
    py = sy + t * dy
    return math.hypot(x - px, y - py)


def _copy_matrix_map(value: Any) -> dict[str, list[list[float]]]:
    result: dict[str, list[list[float]]] = {}
    for path, matrix in dict(value or {}).items():
        result[str(path)] = [[float(cell) for cell in row] for row in matrix]
    return result


def _stream_matrices_close(
    left: list[list[float]],
    right: list[list[float]],
    *,
    tolerance: float = 1.0e-8,
) -> bool:
    if len(left) != len(right):
        return False
    for left_row, right_row in zip(left, right):
        if len(left_row) != len(right_row):
            return False
        for left_value, right_value in zip(left_row, right_row):
            if abs(float(left_value) - float(right_value)) > tolerance:
                return False
    return True


def _normalize_viewport_id(viewport_id: Optional[str]) -> str:
    if viewport_id is None:
        return DEFAULT_VIEWPORT_ID
    if not isinstance(viewport_id, str):
        raise TypeError("viewport_id must be a string")
    normalized = viewport_id.strip()
    if not normalized:
        raise ValueError("viewport_id must be a non-empty string")
    return normalized


def _prune_released_viewport_ids() -> None:
    for viewport_id, owner_ref in tuple(_VIEWPORT_ID_ACTIVE.items()):
        if owner_ref() is None:
            _VIEWPORT_ID_ACTIVE.pop(viewport_id, None)


def _allocate_viewport_id(owner: Any, viewport_id: Optional[str]) -> str:
    base_id = _normalize_viewport_id(viewport_id)
    _prune_released_viewport_ids()
    if base_id not in _VIEWPORT_ID_ACTIVE:
        _VIEWPORT_ID_ACTIVE[base_id] = weakref.ref(owner)
        return base_id

    suffix = 2
    while True:
        candidate = f"{base_id}_{suffix}"
        owner_ref = _VIEWPORT_ID_ACTIVE.get(candidate)
        if owner_ref is None or owner_ref() is None:
            _VIEWPORT_ID_ACTIVE[candidate] = weakref.ref(owner)
            return candidate
        suffix += 1


def _release_viewport_id(owner: Any, viewport_id: str) -> None:
    owner_ref = _VIEWPORT_ID_ACTIVE.get(viewport_id)
    if owner_ref is not None and owner_ref() is owner:
        _VIEWPORT_ID_ACTIVE.pop(viewport_id, None)


def _viewport_window_title(viewport_id: str) -> str:
    if viewport_id == DEFAULT_VIEWPORT_ID:
        return "Viewport"
    return f"Viewport###{viewport_id}"


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ViewportChromeOptions:
    """Server-side viewport chrome visibility configuration.

    All options default to ``True`` to preserve the desktop viewport. Backend
    streaming hosts can set individual fields to ``False`` to keep those
    widgets out of streamed pixels while still using the stock
    :class:`ViewportWidget` renderer, SceneView, camera gestures, pick
    gestures, transform manipulator, tool registry, and frame hooks.
    """

    show_toolbar: bool = True
    show_settings_button: bool = True
    show_text_hud: bool = True
    show_livestream_overlay: bool = True
    show_anchored_panels: bool = True

    @classmethod
    def coerce(
        cls,
        value: Optional["ViewportChromeOptions | dict[str, Any]"],
    ) -> "ViewportChromeOptions":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(**value)
        raise TypeError(
            "chrome_options must be ViewportChromeOptions, a dict, or None"
        )


DEFAULT_VIEWPORT_CHROME_OPTIONS = ViewportChromeOptions()


@dataclass(frozen=True)
class ViewportResolutionHostContext:
    """Owner context passed to the leading resolution toolbar attachment."""

    attachment_id: str
    owner: Any
    viewport_id: str

    @property
    def viewport(self) -> Any:
        """Alias for the owning viewport widget."""

        return self.owner


class ViewportResolutionHostAttachment:
    """Removal handle for the viewport resolution toolbar host attachment."""

    def __init__(
        self,
        owner: Any,
        *,
        attachment_id: str,
        viewport_id: str,
        toolbar_handle: ViewportToolbarHandle,
    ) -> None:
        self._owner_ref = weakref.ref(owner)
        self._attachment_id = attachment_id
        self._viewport_id = viewport_id
        self._toolbar_handle = toolbar_handle
        self._active = True

    @property
    def id(self) -> str:
        return self._attachment_id

    @property
    def attachment_id(self) -> str:
        return self._attachment_id

    @property
    def viewport_id(self) -> str:
        return self._viewport_id

    @property
    def active(self) -> bool:
        return self._active

    def remove(self) -> bool:
        if not self._active:
            return False
        owner = self._owner_ref()
        if owner is None:
            self._deactivate()
            return False
        return owner._remove_resolution_toolbar_host_attachment(self)

    def cancel(self) -> bool:
        return self.remove()

    def _remove_from_registry(self) -> bool:
        return self._toolbar_handle.remove()

    def _deactivate(self) -> None:
        self._active = False


@dataclass(frozen=True)
class ViewportToolState:
    """Backend-readable state for one built-in viewport transform tool."""

    id: str
    label: str
    hotkey: str
    icon_name: str
    active: bool
    enabled: bool
    tooltip: str = ""


@dataclass(frozen=True)
class ViewportCameraState:
    """Backend-readable state for one selectable viewport camera."""

    path: str
    label: str
    active: bool


@dataclass(frozen=True)
class ViewportContributionState:
    """Backend-readable state for toolbar/output contributions."""

    id: str
    label: str
    kind: str
    enabled: bool
    widget_name: str = ""
    tooltip: str = ""
    text: str = ""


@dataclass(frozen=True)
class ViewportHudState:
    """Backend-readable viewport HUD scalar values."""

    scene: str = ""
    fps: Optional[float] = None
    fps_text: str = ""
    resolution: Optional[tuple[int, int]] = None
    resolution_text: str = ""
    stream_state: Optional[str] = None
    stream_clients: Optional[int] = None
    stream_last_error: str = ""
    stream_text: str = ""
    stream_tooltip: str = ""


@dataclass(frozen=True)
class ViewportStateSnapshot:
    """Read-only viewport toolbar/HUD state for non-streamed UI surfaces."""

    active_tool: Optional[str]
    transform_controls_enabled: bool
    transform_controls_tooltip: str
    tools: tuple[ViewportToolState, ...]
    cameras: tuple[ViewportCameraState, ...]
    active_camera_path: Optional[str]
    toolbar_contributions: tuple[ViewportContributionState, ...]
    output_contributions: tuple[ViewportContributionState, ...]
    hud: ViewportHudState


def _shielded_report(module: str, label: str, exc: BaseException) -> None:
    try:
        ErrorReporter.log_error(module, label, exc)
    except BaseException:
        pass


class _LifecycleCleanup:
    """Non-raising cleanup accumulator: :meth:`run` attempts every step
    and records failures without ever raising; :meth:`report` emits the
    diagnostics afterwards and cannot reverse established safety state."""

    def __init__(self) -> None:
        self.failures: list[tuple[str, BaseException]] = []

    def run(self, label: str, fn: Any) -> bool:
        """Attempt one cleanup step; record (never raise) its failure."""
        if not callable(fn):
            return True
        try:
            fn()
            return True
        except BaseException as exc:  # noqa: BLE001 — must not raise
            try:
                self.failures.append((label, exc))
            except BaseException:
                pass
            return False

    def report(self, module: str) -> None:
        """Emit recorded failures; a failing reporter cannot re-raise."""
        for label, exc in list(self.failures):
            _shielded_report(module, label, exc)


def _owned_default_scene_view() -> "sc.SceneView":
    """Default scene view whose Python ``destroy()`` records itself, so
    health checks can observe a retained-reference destruction."""
    cls = getattr(_owned_default_scene_view, "_cls", None)
    if cls is None:
        class cls(sc.SceneView):  # type: ignore[misc]
            destroyed = False

            def destroy(self) -> None:
                self.destroyed = True
                super().destroy()

        _owned_default_scene_view._cls = cls
    return cls()


class _Generation:
    """One interaction generation: born unpublished, atomically
    published at build end, revoked at detach; holds its resources."""

    __slots__ = ("renderer", "alive", "resources", "_owner")

    # Every resource a usable viewport genuinely requires NOW.
    REQUIRED = ("_scene_view", "_camera_manipulator",
                "_transform_manipulator", "_pick_manager", "_tool_registry")

    def __init__(self, renderer: Any, owner: Any = None) -> None:
        self.renderer = renderer
        self.alive = False
        self.resources: tuple = ()
        self._owner = None if owner is None else weakref.ref(owner)

    def operational(self, owner: Any) -> bool:
        """The one health predicate: alive, current, every required
        resource present, identical, and not destroyed."""
        renderer = getattr(owner, "_renderer", None)
        model = getattr(owner, "_transform_model", None)
        model_ok = model is None or getattr(
            model, "renderer_adapter", None) is renderer
        if (not self.alive or renderer is None or not model_ok
                or self.renderer is not renderer or not self.resources):
            return False
        for name, held in self.resources:
            if (held is None or held is not getattr(owner, name, None)
                    or getattr(held, "destroyed", False)):
                return False
        return True

    @property
    def effective(self) -> bool:
        """Revocation boundary for callbacks: the same predicate, bound
        to the owner (ownerless tokens degrade to the publication flag)."""
        if not self.alive:
            return False
        if self._owner is None:
            return True
        owner = self._owner()
        return (owner is not None
                and not getattr(owner, "_destroyed", False)
                and getattr(owner, "_live_generation", None) is self
                and self.operational(owner))


class ViewportSurface:
    """Embeddable viewport body — rendered image / SceneView / optional chrome.

    ``ViewportSurface`` owns the stock viewport lifecycle without creating a
    ``ui.Window``. Hosts can install it into a caller-owned frame via
    :meth:`build_into` or build it in the current UI context via :meth:`build`.
    ``ViewportWidget`` remains the desktop ``ManagedWindow`` wrapper around
    this surface.
    """

    @staticmethod
    def _configured_max_fps() -> float:
        """Live Kit-compatible FPS cap (app.runLoops.main.rateLimitFrequency).

        Read on sparse, event-driven paths only (resize / resolution
        refreshes, the legacy ``_on_frame`` shim) — the production frame
        loop is paced by the ovui pump and the Application's
        subscription-updated FrameClock and never calls this.
        """
        from ovui_widgets.common.settings import (
            DEFAULT_RATE_LIMIT_FPS,
            RATE_LIMIT_FPS_SETTING_KEY,
            Settings,
            valid_rate_limit_fps,
        )
        return valid_rate_limit_fps(
            Settings.instance().get(
                RATE_LIMIT_FPS_SETTING_KEY, DEFAULT_RATE_LIMIT_FPS
            ),
            default=DEFAULT_RATE_LIMIT_FPS,
        )

    def set_shared_render_clock(self, clock: Any) -> None:
        """Install the host Application's render FrameClock.

        Event-driven direct renders then draw from the same cadence budget
        as the regular frame loop, so repeated resize/resolution events
        cannot push total renders past the configured cap.
        """
        self._shared_render_clock = clock

    def _direct_render_clock(self) -> Any:
        """The cadence gate for direct renders (shared, else local)."""
        if self._shared_render_clock is not None:
            return self._shared_render_clock
        if self._local_direct_render_clock is None:
            from ovui_widgets.app.frame_clock import FrameClock
            self._local_direct_render_clock = FrameClock(
                target_fps=self._configured_max_fps()
            )
        else:
            # Event-driven read: refresh the standalone clock's target so a
            # live setting change is honored without a subscription.
            self._local_direct_render_clock.target_fps = (
                self._configured_max_fps()
            )
        return self._local_direct_render_clock

    def _render_rate_limited(self) -> bool:
        """Render the latest state through the shared cadence gate.

        Returns True when a frame actually painted. When the gate is not
        due, the render is skipped — the regular paced frame loop paints
        the latest state at the next due tick, so nothing is lost and the
        rateLimitFrequency cap holds even under repeated resize /
        resolution events.
        """
        clock = self._direct_render_clock()
        now = time.perf_counter()
        render_dt = clock.should_render(now)
        if render_dt is None:
            return False
        rendered = bool(self.render(render_dt))
        if rendered:
            clock.commit(now)
        return rendered

    # Clamp the render resolution before handing it to the renderer adapter.
    # Floor at 64×64 so the renderer always has a sensible buffer to work
    # with (matches the viewport behavior); ceiling at 4K UHD to avoid
    # accidental gigantic GPU allocations when a user maximises onto a
    # high-DPI display. ImageWithProvider uses IWP_PRESERVE_ASPECT_FIT so
    # the on-screen image still fills the widget when these clamps kick in.
    MIN_RENDER_WIDTH = 64
    MIN_RENDER_HEIGHT = 64
    MAX_RENDER_WIDTH = 3840
    MAX_RENDER_HEIGHT = 2160
    TOOLBAR_HEIGHT = 24
    TOOLBAR_BUTTON_SIZE = 20
    TOOLBAR_ICON_SIZE = 13
    CAMERA_NAVIGATION_SETTLE_FRAMES = 2
    FPS_AVERAGE_WINDOW_SECONDS = 1.0

    def __init__(
        self,
        services: Any = None,
        renderer: Optional[RendererAdapter] = None,
        bus: Any = None,
        on_drop_fn: Optional[Callable[[Any], None]] = None,
        stage_adapter_provider: Optional[Callable[[], Any]] = None,
        chrome_options: Optional[ViewportChromeOptions | dict[str, Any]] = None,
        viewport_id: Optional[str] = None,
    ) -> None:
        self._chrome_options = ViewportChromeOptions.coerce(chrome_options)
        # Step 11.3/13: viewport seam atomic conversion.
        # ``services`` replaces the old ``app`` parameter. The two
        # other widget-injection seams are explicit per-widget
        # callbacks rather than members of the WidgetServices Protocol
        # (which stays at exactly three members per Plan Rev 2 §5.20):
        #
        # * ``on_drop_fn(event) -> None`` — single-argument drop
        #   delegate. Application binds ``target="viewport"`` via a
        #   lambda at the call site so the viewport widget itself
        #   has no notion of ``target`` strings.
        # * ``stage_adapter_provider() -> StageAdapter | None`` —
        #   bound method on Application that returns the live
        #   ``_stage_adapter`` for bbox / frame-selected camera
        #   computations. A lambda wrapping a single attribute access
        #   adds no value; the bound method is the canonical form.
        normalized_viewport_id = _normalize_viewport_id(viewport_id)
        self._services = services
        self._on_drop_fn = on_drop_fn
        self._stage_adapter_provider = stage_adapter_provider
        # Cadence gate for event-driven direct renders (resize / resolution
        # refresh). The Application injects its own FrameClock via
        # :meth:`set_shared_render_clock` so direct renders and the frame
        # loop share one rateLimitFrequency budget; standalone hosts get a
        # lazily-created local clock instead.
        self._shared_render_clock: Optional[Any] = None
        self._local_direct_render_clock: Optional[Any] = None
        self._renderer = renderer
        # Terminal teardown latch; everything else derives from the token.
        self._destroyed: bool = False
        # Token of the last COMPLETED build; revoked on rebuild/detach.
        self._live_generation: Optional[_Generation] = None
        # At most ONE viewport-owned renderer with unresolved shutdown.
        self._unresolved_predecessor: Optional[Any] = None
        self._width = 1280
        self._height = 720
        # Shared zero-copy state (strata#16 tier-2). When OVGEAR_ZERO_COPY=1
        # is set, both the renderer and the bridge route LdrColor through a
        # CUDA-mapped pointer; the bridge probes ovui's GPU backend on the
        # first frame and latches to tier-1 if the standalone build no-ops
        # set_bytes_data_from_gpu. If the renderer was built externally and
        # already carries its own state, reuse it; otherwise install ours.
        from ovui_data_adapters.common import ZeroCopyState
        self._zero_copy_state = ZeroCopyState.from_env()
        self._attach_zero_copy_state(renderer, adopt_existing=True)
        # The viewport drives a continuous frame loop, so it opts the
        # renderer into the depth-one LdrColor overlap (present frame N-1
        # while the GPU renders frame N). Adapters without the capability
        # (and one-shot render_frame consumers, which never opt in) keep the
        # historical synchronous behavior.
        self._enable_renderer_frame_overlap(renderer)
        self._bridge = ImageBridge(self._width, self._height, state=self._zero_copy_state)
        self._camera = CameraController()
        self._camera_model = CameraManipulatorModel()
        # Flight-mode keyboard — Step B.3. Constructed here (not in
        # ``_build_ui``) so the application can wire its key dispatcher
        # to ``_flight_keyboard.handle_key_event`` before the first
        # frame. The gesture list it polls is populated in ``_build_ui``
        # once the tumble/look gestures exist.
        # Step 11.3: read FLY_SPEED from the explicit
        # ``ovui_widgets.common.settings.Settings`` singleton wired
        # by ``Application.__init__`` in Step 10. Headless / mock
        # paths without a registered Settings fall back to the
        # default 1.0.
        fly_speed = 1.0
        try:
            from ovui_widgets.common.settings import Settings
            _settings = Settings._instance
            if _settings is not None:
                fly_speed = float(_settings.get(FLY_SPEED_SETTING, 1.0))
        except (AttributeError, TypeError, ValueError):
            fly_speed = 1.0
        self._flight_keyboard = FlightModeKeyboard(
            self._camera, model=self._camera_model, base_speed=fly_speed
        )
        # Tumble inertia — Step B.4. The ``tumble_inertia`` model item
        # drives the time constant so live setting changes propagate
        # without reinstancing. A setting value of 0.0 disables inertia
        # (``TumbleInertia.is_enabled`` returns False and ``start`` is
        # a no-op).
        # Step 11.3: read TUMBLE_INERTIA from the explicit
        # ``ovui_widgets.common.settings.Settings`` singleton.
        tumble_inertia_s = DEFAULT_TUMBLE_INERTIA
        try:
            from ovui_widgets.common.settings import Settings
            _settings = Settings._instance
            if _settings is not None:
                tumble_inertia_s = float(
                    _settings.get(TUMBLE_INERTIA_SETTING, DEFAULT_TUMBLE_INERTIA)
                )
        except (AttributeError, TypeError, ValueError):
            tumble_inertia_s = DEFAULT_TUMBLE_INERTIA
        self._camera_model.set_floats("tumble_inertia", [tumble_inertia_s])
        self._tumble_inertia = TumbleInertia(
            self._camera, model=self._camera_model
        )
        self._camera_manipulator: Optional[CameraManipulator] = None
        self._transform_manipulator: Optional[TransformManipulator] = None
        # Construct the transform model eagerly in ``__init__`` so it is
        # already present when :meth:`Application._load_stage` calls
        # :meth:`attach_stage`. Before this moved out of ``_build_ui``,
        # the frame's build function ran lazily on first render, so stage
        # load routinely happened while the model was still ``None`` —
        # ``attach_adapters`` was silently skipped and every
        # ``get_pivot_world()`` returned the fallback origin, parking the
        # gizmo at (0,0,0) regardless of selection. The model is pure
        # data (no UI), so there is no reason to tie it to frame build.
        self._transform_model: Optional[PrimTransformModel] = PrimTransformModel(
            renderer=renderer
        )
        self._tool_registry: Optional[ToolRegistry] = None
        # Last-rebuilt gizmo world-scale; used by ``_on_frame`` to decide
        # whether the camera moved enough since the previous rebuild to
        # justify invalidating the manipulator. Invalidating blindly
        # every frame destroys the shapes the gesture system captured
        # mouse input against, which broke drag and hover continuity.
        self._last_gizmo_scale: float = 0.0
        self._image: Optional[Any] = None
        self._scene_view: Optional[Any] = None
        self._manipulator_scene_view_factories: list[
            tuple[object, str, Callable[[], Any]]
        ] = []
        self._manipulator_scene_backend = "unbuilt"
        self._manipulator_scene_status: dict[str, Any] = {
            "backend": self._manipulator_scene_backend,
            "fallback_to_default_scene": False,
        }
        self._scene_name: Optional[str] = None
        self._prim_count: int = 0
        self._last_fps: Optional[float] = None
        self._fps_sample_intervals: deque[float] = deque()
        self._fps_sample_seconds = 0.0
        self._last_resolution: Optional[tuple[int, int]] = None
        self._resolution_state = ViewportResolutionState.default(
            clamp_limits=ResolutionClampLimits(
                min_width=self.MIN_RENDER_WIDTH,
                min_height=self.MIN_RENDER_HEIGHT,
                max_width=self.MAX_RENDER_WIDTH,
                max_height=self.MAX_RENDER_HEIGHT,
            )
        )
        self._resolution_state_observers: dict[
            int, ResolutionStateChangedCallback
        ] = {}
        self._resolution_state_next_observer_token = 1
        self._resolution_state_handles: weakref.WeakSet[
            ViewportResolutionStateSubscription
        ] = weakref.WeakSet()
        self._resolution_state_observers_closed = False
        self._resolution_availability_owner_alive = True
        self._resolution_availability = self._compute_resolution_availability()
        self._resolution_availability_observers: dict[
            int, AvailabilityChangedCallback
        ] = {}
        self._resolution_availability_next_observer_token = 1
        self._resolution_availability_handles: weakref.WeakSet[
            ViewportAvailabilitySubscription
        ] = weakref.WeakSet()
        self._resolution_availability_observers_closed = False
        self._last_image_frame: Optional[Any] = None
        self._fps_label: Optional[Any] = None
        self._prim_count_label: Optional[Any] = None
        self._scene_row: Optional[Any] = None
        self._fps_res_row: Optional[Any] = None
        self._scene_value_label: Optional[Any] = None
        self._fps_value_label: Optional[Any] = None
        self._resolution_label: Optional[Any] = None
        self._resolution_value_label: Optional[Any] = None
        self._fps_res_separator_label: Optional[Any] = None
        # Step 1.7: livestream status overlay. Top-right HUD block,
        # hidden when the renderer has no livestream tap (i.e.
        # ``OVGEAR_LIVESTREAM`` is unset or the SDK is missing).
        self._livestream_row: Optional[Any] = None
        self._livestream_value_label: Optional[Any] = None
        self._last_livestream_state: Optional[str] = None
        self._last_livestream_clients: Optional[int] = None
        self._last_livestream_error: str = ""
        self._last_livestream_text: str = ""
        self._last_livestream_tooltip: str = ""
        self._toolbar_frame: Optional[Any] = None
        self._toolbar_buttons: dict[str, Any] = {}
        self._toolbar_button_backgrounds: dict[str, Any] = {}
        self._pre_tools_toolbar_hooks = ViewportToolbarRegistry(self)
        self._resolution_toolbar_host_attachment: Optional[
            ViewportResolutionHostAttachment
        ] = None
        self._resolution_toolbar_host_closed = False
        self._resolution_settings_schema_qa_window: Optional[Any] = None
        self._resolution_settings_schema_qa_labels: list[Any] = []
        self._resolution_settings_schema_qa_name_field: Optional[Any] = None
        self._resolution_settings_schema_qa_width_field: Optional[Any] = None
        self._resolution_settings_schema_qa_height_field: Optional[Any] = None
        self._resolution_settings_schema_qa_profile = _AREA1_QA_PROFILE_NO_SAVED
        self._resolution_settings_schema_qa_data = _AREA1_QA_SHARED_SETTINGS_DATA
        self._resolution_settings_notification_qa_window: Optional[Any] = None
        self._resolution_settings_notification_qa_retired_windows: list[Any] = []
        self._resolution_settings_notification_qa_labels: list[Any] = []
        self._resolution_settings_notification_qa_subscription: Optional[Any] = None
        self._resolution_settings_notification_qa_change_count = 0
        self._resolution_settings_notification_qa_last_change = "No recent change"
        self._resolution_catalog_qa_window: Optional[Any] = None
        self._resolution_catalog_qa_labels: list[Any] = []
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_INITIAL
        self._resolution_catalog_qa_preset_config = _AREA2_QA_DEFAULT_PRESET_CONFIG
        self._resolution_catalog_qa_focus_label: Optional[str] = None
        self._resolution_catalog_qa_requested_size = VIEWPORT_SENTINEL_DIMENSIONS
        self._resolution_catalog_qa_unsaved_size: Optional[tuple[int, int]] = None
        self._resolution_catalog_qa_attempted_sentinel_label: Optional[str] = None
        self._resolution_catalog_qa_render_scale = 1.0
        self._resolution_catalog_qa_attempted_requested_size: Optional[tuple[int, int]] = None
        self._resolution_catalog_qa_action_accepted = True
        self._resolution_render_qa_window: Optional[Any] = None
        self._resolution_render_qa_labels: list[Any] = []
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_INITIAL
        self._resolution_menu_failure_qa_window: Optional[Any] = None
        self._resolution_menu_failure_qa_labels: list[Any] = []
        self._resolution_missing_icon_qa_window: Optional[Any] = None
        self._resolution_missing_icon_qa_labels: list[Any] = []
        self._resolution_ovui_only_qa_window: Optional[Any] = None
        self._resolution_ovui_only_qa_labels: list[Any] = []
        self._resolution_render_qa_frame_size: Optional[tuple[int, int]] = (
            (1280, 720)
            if (
                _env_flag_enabled(AREA3_RENDER_QA_ENV)
                or _env_flag_enabled(AREA3_INTERACTION_QA_ENV)
            )
            else None
        )
        self._resolution_render_qa_missing_settings = False
        self._resolution_render_qa_dpi_available: Optional[bool] = None
        self._resolution_render_qa_dpi_scale = 1.0
        self._resolution_render_qa_status_message = ""
        if _env_flag_enabled(AREA3_OPENUSD_SESSION_QA_ENV):
            self._resolution_render_qa_profile = _AREA3_QA_PROFILE_OPENUSD_SESSION
            self._resolution_render_qa_status_message = (
                _AREA3_QA_OPENUSD_SESSION_STATUS
            )
        if _env_flag_enabled(AREA3_INTERACTION_QA_ENV):
            self._resolution_render_qa_profile = _AREA3_QA_PROFILE_INTERACTION_INITIAL
            self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
            self._resolution_render_qa_status_message = _AREA3_QA_INTERACTION_STATUS
        self._last_viewport_mode_effective_resolution: Optional[
            ViewportModeEffectiveResolution
        ] = None
        self._last_viewport_mode_visible_frame_size: Optional[tuple[int, int]] = None
        self._last_fixed_mode_effective_resolution: Optional[
            FixedModeEffectiveResolution
        ] = None
        self._last_fill_viewport_visible_frame_size: Optional[tuple[int, int]] = None
        self._resolution_render_in_progress = False
        self._resolution_render_refresh_pending = False
        self._viewport_resize_render_refresh_pending = False
        self._last_render_resolution_apply_error: Optional[BaseException] = None
        self._selection_highlight_retry_paths: Optional[list[str]] = None
        self._resolution_settings_subscription: Optional[Any] = None
        self._resolution_settings_self_origin_values: dict[str, Any] = {}
        self._resolution_shared_settings_values: dict[str, Any] = {}
        self._settings_menu_reshow_pending = False
        self._settings_menu_dismiss_pending = False
        self._settings_menu_control_callback_tokens: set[str] = set()
        self._custom_resolution_save_dialog_window: Optional[Any] = None
        self._custom_resolution_save_dialog_name_field: Optional[Any] = None
        self._custom_resolution_save_dialog_resolution_label: Optional[Any] = None
        self._custom_resolution_save_dialog_error_label: Optional[Any] = None
        self._custom_resolution_save_dialog_save_button: Optional[Any] = None
        self._custom_resolution_save_dialog_size: Optional[tuple[int, int]] = None
        self._custom_resolution_save_handoff: Optional[Callable[[], Any]] = (
            self._open_custom_resolution_save_dialog
        )
        self._custom_resolution_field_pending_size: Optional[tuple[int, int]] = None
        self._custom_resolution_field_apply_pending = False
        self._saved_custom_delete_handoff: Optional[Callable[[Any], Any]] = (
            self._delete_saved_custom_resolution_row
        )
        self._toolbar_hooks = ViewportToolbarRegistry(self)
        self._viewport_hooks = ViewportContributionRegistry(self)
        self._camera_menu: Optional[Any] = None
        self._camera_menu_items: list[tuple[str, str, bool, Any]] = []
        self._active_camera_path: Optional[str] = None
        self._last_authored_camera_signature: Optional[tuple[Any, ...]] = None
        self._committing_active_camera_pose = False
        self._render_target_camera_snapshot: Optional[tuple[Any, ...]] = None
        self._camera_navigation_state = CameraNavigationState(
            stable_frame_threshold=self.CAMERA_NAVIGATION_SETTLE_FRAMES
        )
        self._pushing_to_bus = False
        self._receiving_from_bus = False
        # Step 11.3: ``services.selection_bus`` is the WidgetServices
        # member; bus override still wins.
        self._bus = bus or (
            services.selection_bus if services is not None else None
        )
        self._bus_sub = None
        self._manipulator_registry = None
        self._streamed_transform_drag: Optional[dict[str, Any]] = None
        if self._bus:
            self._bus_sub = self._bus.subscribe(self._on_bus_selection_changed)
        self._viewport_id = _allocate_viewport_id(self, normalized_viewport_id)
        self._viewport_id_released = False
        self._install_resolution_settings_subscription()
        try:
            chrome_options = self._get_chrome_options()
            if chrome_options.show_toolbar and chrome_options.show_settings_button:
                self._register_viewport_settings_toolbar_button()
            if _env_flag_enabled(
                FOUNDATION_QA_PRE_TOOLS_PLACEHOLDER_ENV
            ) or _env_flag_enabled(AREA1_SETTINGS_SCHEMA_QA_ENV) or _env_flag_enabled(
                AREA2_CATALOG_QA_ENV
            ) or _env_flag_enabled(
                AREA3_RENDER_QA_ENV
            ) or _env_flag_enabled(
                AREA3_INTERACTION_QA_ENV
            ):
                self._register_foundation_qa_pre_tools_placeholder()
            if _env_flag_enabled(AREA1_SETTINGS_SCHEMA_QA_ENV):
                self._build_resolution_settings_schema_qa_window()
            if _env_flag_enabled(AREA2_CATALOG_QA_ENV):
                self._build_resolution_catalog_qa_window()
            if _env_flag_enabled(AREA3_RENDER_QA_ENV) or _env_flag_enabled(
                AREA3_INTERACTION_QA_ENV
            ):
                self._build_resolution_render_qa_window()
            if _env_flag_enabled(AREA7_MENU_FAILURE_QA_ENV):
                self._build_resolution_menu_failure_qa_window()
            if self._resolution_missing_icon_profile_active():
                self._build_resolution_missing_icon_qa_window()
            if self._resolution_ovui_only_profile_active():
                self._build_resolution_ovui_only_qa_window()
        except Exception:
            self._destroy_resolution_settings_subscription()
            self._destroy_resolution_ovui_only_qa_window()
            self._destroy_resolution_missing_icon_qa_window()
            self._destroy_resolution_menu_failure_qa_window()
            self._destroy_resolution_render_qa_window()
            self._destroy_resolution_catalog_qa_window()
            self._destroy_resolution_settings_schema_qa_window()
            self._dispose_resolution_toolbar_host_attachment()
            self._release_viewport_identity()
            raise

    def _on_drop(self, event: Any) -> None:
        """Forward a viewport drop event to :meth:`Application._on_drop`.

        ovui delivers :class:`WidgetMouseDropEvent` whose ``mime_data``
        is the ``"\\n"``-joined URL payload the drag source produced
        (the content browser's internal / external drag MIME format —
        see :meth:`FileBrowserWidget._tree_drag_payload`). The widget
        itself has no USD-open surface; it delegates to the
        application-level dispatcher so the target-branch + stage-load
        logic stays in one place. Silent no-op when no application is
        wired (pure-test viewport instances).
        """
        # Step 11.3: route the drop through the explicit
        # ``on_drop_fn`` callback. Application binds ``target=
        # "viewport"`` via lambda at the call site so the
        # viewport widget no longer reaches into the app object.
        if self._on_drop_fn is not None:
            self._on_drop_fn(event)

    def build(self) -> None:
        """Build the viewport body in the current UI context."""

        self._build_ui()

    def build_into(self, frame: Any) -> None:
        """Install the viewport body into a caller-owned ``ui.Frame``.

        The caller keeps ownership of the frame/window. The installed build
        function is the same `_build_ui` path used by `ViewportWidget`, so the
        renderer image, SceneView, camera manipulator, transform manipulator,
        pick/marquee gestures, tool registry, contribution hooks, and chrome
        options cannot drift from the desktop widget.
        """

        if getattr(self, "_destroyed", False):
            # Terminal: never register a build callback on a caller frame.
            return
        set_build_fn = getattr(frame, "set_build_fn", None)
        if not callable(set_build_fn):
            raise TypeError("ViewportSurface.build_into() requires a frame with set_build_fn")
        set_build_fn(self._build_ui)

    def _build_ui(self) -> None:
        # A rebuild revokes the previous generation up front.
        if getattr(self, "_destroyed", False):
            return
        previous = getattr(self, "_live_generation", None)
        if previous is not None:
            previous.alive = False
        generation = _Generation(self._renderer, self)
        try:
            self._build_ui_body(generation)
        except BaseException:
            dispose = _LifecycleCleanup()
            self._detach_interaction_resources(dispose)
            dispose.report("ViewportWidget.build")
            raise
        generation.resources = tuple(
            (n, getattr(self, n, None)) for n in _Generation.REQUIRED)
        generation.alive = True
        self._live_generation = generation

    def _build_ui_body(self, generation: "_Generation") -> None:
        self._toolbar_buttons = {}
        self._toolbar_button_backgrounds = {}
        chrome = self._get_chrome_options()
        with ui.ZStack():
            with ui.ZStack():
                # Layer 1: rendered image via ByteImageProvider
                self._image = ui.ImageWithProvider(
                    self._bridge.provider,
                    fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
                    style_type_name_override="ViewportWidget.Image",
                )
                overlay_build_fn = getattr(self, "_scene_view_overlay_build_fn", None)
                if callable(overlay_build_fn):
                    overlay_build_fn()
                # Layer 2: SceneView for camera, pick gestures, and the real
                # transform manipulator. Optional scene backends can replace
                # the built-in SceneView through the factory hook below.
                # The old scene view holds native GL/CUDA + input routing.
                old_scene_view = getattr(self, "_scene_view", None)
                if old_scene_view is not None:
                    _LifecycleCleanup().run(
                        "old scene view destroy", old_scene_view.destroy)
                    self._scene_view = None
                if self._renderer is None:
                    # Rendererless: no overlay or pick/drag input.
                    self._scene_view = None
                    self._camera_manipulator = None
                    self._transform_manipulator = None
                    self._pick_manager = None
                    old_registry = getattr(self, "_tool_registry", None)
                    if old_registry is not None:
                        _LifecycleCleanup().run(
                            "old tool registry destroy", old_registry.destroy)
                    self._tool_registry = None
                    self._refresh_toolbar_state()
                else:
                    self._scene_view = self._create_manipulator_scene_view()
                    # ``content_clipping`` toolbar stacks shield clicks
                    # from the SceneView (menus must not pick underneath).
                    self._scene_view.child_windows_input = False
                    # Point pick and marquee: one variant per selection
                    # mode, routed by modifier-aware gesture dispatch.
                    _modes = (("replace", MOD_NONE), ("add", MOD_SHIFT),
                              ("remove", MOD_CTRL))
                    pick_replace, pick_add, pick_remove = (
                        PickGesture(
                            callback=self._make_pick_callback(mode),
                            modifiers=mods, generation=generation,
                        ) for mode, mods in _modes
                    )
                    pick_rect_replace, pick_rect_add, pick_rect_remove = (
                        PickRectGesture(
                            callback=self._make_pick_rect_callback(mode),
                            modifiers=mods, generation=generation,
                        ) for mode, mods in _modes
                    )
                    # Tie-breaker for LMB pick/marquee vs gizmo drags —
                    # stashed as a plain attribute (assigning ``.manager``
                    # starves the gizmo drag of on-move events).
                    self._pick_manager = GizmoAwarePickManager()
                    for g in (
                        pick_replace, pick_add, pick_remove,
                        pick_rect_replace, pick_rect_add, pick_rect_remove,
                    ):
                        g._viewport_pick_manager = self._pick_manager
                    # ``PrimTransformModel`` is constructed eagerly in
                    # ``__init__`` (attach_stage may run before the build).
                    initial_tool = self._get_active_tool()
                    if initial_tool not in VALID_TOOLS:
                        initial_tool = TOOL_TRANSLATE
                    with self._scene_view.scene:
                        self._camera_manipulator = CameraManipulator(
                            camera_controller=self._camera,
                            model=self._camera_model,
                            viewport_size_fn=self._get_viewport_size,
                            flight_keyboard=self._flight_keyboard,
                            tumble_inertia=self._tumble_inertia,
                            generation=generation,
                        )
                        self._transform_manipulator = TransformManipulator(
                            model=self._transform_model,
                            tool=initial_tool,
                            pivot_fn=self._transform_model.get_pivot_world,
                            size_fn=self._get_gizmo_world_scale,
                            generation=generation,
                        )
                        # Register the gizmo's persistent drags with the
                        # pick manager (introspection; dispatch is scene-order).
                        self._pick_manager.set_gizmo_gestures([
                            *self._transform_manipulator._translate_drags,
                            *self._transform_manipulator._rotate_drags,
                            *self._transform_manipulator._scale_drags,
                            self._transform_manipulator._uniform_scale_drag,
                        ])
                        # Screen with selection gestures added LAST: under
                        # LIFO gesture dispatch the gizmo shapes must capture
                        # LMB before the marquee, or an axis drag draws a
                        # selection rectangle instead of translating.
                        sc.Screen(gestures=[
                            pick_replace, pick_add, pick_remove,
                            pick_rect_replace, pick_rect_add,
                            pick_rect_remove,
                        ])
                        self._viewport_hooks.build_overlays(self._scene_view)
                    # W/E/R hotkeys + active-tool setting (not scene geometry).
                    settings = self._resolve_settings()
                    old_registry = getattr(self, "_tool_registry", None)
                    if old_registry is not None:
                        _LifecycleCleanup().run(
                            "old tool registry destroy", old_registry.destroy)
                    self._tool_registry = ToolRegistry(
                        settings=settings,
                        manipulator=self._transform_manipulator,
                        on_tool_changed=self._on_tool_changed,
                        generation=generation,
                    )
                    self._refresh_toolbar_state()
                # Layer 3: HUD overlay
                if chrome.show_text_hud or chrome.show_livestream_overlay:
                    self._build_hud()
                if chrome.show_anchored_panels:
                    self._viewport_hooks.build_anchored_panels(ui)
            # Existing transform-tool controls, restyled as a transparent
            # overlay instead of a separate boxed toolbar band.
            if chrome.show_toolbar:
                self._build_toolbar_row()
            else:
                self._toolbar_frame = None


    def _get_chrome_options(self) -> ViewportChromeOptions:
        return getattr(
            self,
            "_chrome_options",
            DEFAULT_VIEWPORT_CHROME_OPTIONS,
        )

    def _create_manipulator_scene_view(self) -> sc.SceneView:
        """Create the scene view used by the viewport manipulator layer."""

        registration = (
            self._manipulator_scene_view_factories[-1]
            if self._manipulator_scene_view_factories
            else None
        )
        requested_backend = registration[1] if registration is not None else "default"
        error: Exception | None = None
        if registration is not None:
            try:
                scene_view = registration[2]()
                if scene_view is None or not hasattr(scene_view, "scene"):
                    raise TypeError("scene-view factory did not return a SceneView")
            except Exception as exc:
                error = exc
                print(
                    "[ViewportSurface] scene-view factory "
                    f"{requested_backend!r} failed; using the default backend: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                scene_view = _owned_default_scene_view()
                backend = "default"
        else:
            scene_view = _owned_default_scene_view()
            backend = "default"

        if error is None:
            backend = requested_backend
        self._manipulator_scene_backend = backend
        self._manipulator_scene_status = {
            "backend": backend,
            "requested_backend": requested_backend,
            "fallback_to_default_scene": error is not None,
            "scene_view_type": type(scene_view).__name__,
            "scene_view_module": type(scene_view).__module__,
        }
        if error is not None:
            self._manipulator_scene_status["error"] = str(error)
        return scene_view

    def register_manipulator_scene_view_factory(
        self,
        factory: Callable[[], Any],
        *,
        name: str = "custom",
    ) -> Callable[[], None]:
        """Register an optional factory for the manipulator SceneView.

        The most recently registered factory is used. The returned callback
        removes only this registration, which lets independently installed
        application components cleanly unload themselves.
        """

        if not callable(factory):
            raise TypeError("scene-view factory must be callable")
        backend_name = str(name).strip() or "custom"
        token = object()
        registration = (token, backend_name, factory)
        self._manipulator_scene_view_factories.append(registration)

        def unregister() -> None:
            self._manipulator_scene_view_factories = [
                item
                for item in self._manipulator_scene_view_factories
                if item[0] is not token
            ]

        return unregister

    def get_manipulator_scene_backend_state(self) -> dict[str, Any]:
        """Return the live manipulator scene backend for tests/diagnostics."""
        state = dict(self._manipulator_scene_status)
        state.update(
            {
                "backend": self._manipulator_scene_backend,
                "transform_manipulator_present": self._transform_manipulator is not None,
                "camera_manipulator_present": self._camera_manipulator is not None,
            }
        )
        return state

    def handle_streamed_transform_pointer_event(
        self,
        *,
        event_type: str,
        x: int = 0,
        y: int = 0,
        button: int | None = None,
        pressed: bool | None = None,
        modifiers: int = 0,
        key_code: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Route streamed pointer input to the real transform manipulator.

        Browser/WebRTC input arrives in stream-pixel coordinates, outside
        ``omni.ui_scene``'s shape hit-test stack. This public viewport seam
        keeps the routing ovui-owned: it hit-tests the real translate handles
        from the current viewport camera and forwards captured movement into
        the existing persistent ``PrimTranslateChangedGesture`` instances.
        """

        w, h = self._streamed_input_extent(width, height)
        event = str(event_type)
        if event == "cancel":
            return self._cancel_streamed_transform_drag(reason="stream_disconnect")
        if event == "key_down" and int(key_code or 0) in (27, 256):
            return self._cancel_streamed_transform_drag(reason="escape")
        if self._streamed_transform_drag is None and event in {"button", "move"}:
            self._sync_transform_selection_from_bus()

        if event == "button":
            if int(button or 0) != 1:
                return self._streamed_transform_result(False, "ignored", reason="non_left_button")
            if pressed:
                return self._begin_streamed_transform_drag(int(x), int(y), int(modifiers), w, h)
            return self._end_streamed_transform_drag(int(x), int(y), w, h)
        if event == "move":
            return self._update_streamed_transform_drag(int(x), int(y), w, h)
        return self._streamed_transform_result(False, "ignored", reason="unsupported_event")

    def _sync_transform_selection_from_bus(self) -> None:
        """Ensure streamed transform hit-testing uses the live selection bus.

        Native input drain and protocol bootstrap can run between the viewport's
        selection publication and a streamed pointer press. The bus is the
        authoritative backend-owned selection source, so resynchronise the real
        transform model before hit-testing manipulator handles. This does not
        synthesize preview or commit state; it only feeds the existing ovui
        gesture/model path the current selection it already owns elsewhere.
        """

        if self._bus is None or self._transform_model is None:
            return
        get_snapshot = getattr(self._bus, "get_snapshot", None)
        if not callable(get_snapshot):
            return
        try:
            snapshot = get_snapshot()
            paths = list(snapshot.paths()) if snapshot is not None else []
        except Exception:
            return
        raw_paths = list(getattr(self._transform_model, "_raw_selected_paths", ()) or ())
        transformable_paths = list(getattr(self._transform_model, "_selected_paths", ()) or ())
        if raw_paths == paths and (not paths or transformable_paths):
            return
        try:
            self._transform_model.set_selection(paths)
        except Exception:
            return
        if self._transform_manipulator is not None:
            try:
                self._transform_manipulator.invalidate()
            except Exception:
                pass
            self._last_gizmo_scale = 0.0
        self._refresh_toolbar_state()

    def _begin_streamed_transform_drag(
        self,
        x: int,
        y: int,
        modifiers: int,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        if modifiers:
            return self._streamed_transform_result(False, "ignored", reason="modified_pointer")
        if self._transform_manipulator is None or self._transform_model is None:
            return self._streamed_transform_result(False, "unavailable", reason="manipulator_unavailable")
        if self._get_active_tool() != TOOL_TRANSLATE:
            return self._streamed_transform_result(False, "ignored", reason="non_translate_tool")
        if not self._transform_model.has_transformable_selection():
            return self._streamed_transform_result(False, "ignored", reason="no_transformable_selection")

        hit = self._hit_streamed_translate_handle(x, y, width, height)
        if hit is None:
            return self._streamed_transform_result(False, "miss", reason="no_handle_hit")

        handles = getattr(self._transform_manipulator, "translate_handles", None)
        gesture = None
        if handles is not None:
            getter = getattr(handles, "gesture_for_axis", None)
            if callable(getter):
                try:
                    gesture = getter(hit["axis"])
                except Exception:
                    gesture = None
        if gesture is None:
            axis_index = {"x": 0, "y": 1, "z": 2}.get(hit["axis"], 0)
            drags = getattr(self._transform_manipulator, "_translate_drags", ()) or ()
            if axis_index < len(drags):
                gesture = drags[axis_index]
        if gesture is None:
            return self._streamed_transform_result(False, "unavailable", reason="translate_gesture_unavailable")

        closest = self._stream_axis_closest_point(x, y, hit["axis_vector"], width, height)
        begin = getattr(gesture, "begin_with_line_closest_point", None)
        began = bool(begin(closest)) if callable(begin) else False
        if not began:
            return self._streamed_transform_result(False, "unavailable", reason="gesture_begin_rejected")

        self._streamed_transform_drag = {
            "gesture": gesture,
            "axis": hit["axis"],
            "axis_vector": hit["axis_vector"],
            "pointer_start": (x, y),
            "initial_transforms": _copy_matrix_map(getattr(self._transform_model, "_initial_transforms", {})),
            "undo_before": self._undo_can_undo(),
        }
        return self._streamed_transform_result(
            True,
            "begin",
            axis=hit["axis"],
            pointer=(x, y),
            drag_started=True,
            reason="real_translate_handle_hit",
        )

    def _update_streamed_transform_drag(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        drag = self._streamed_transform_drag
        if not drag:
            return self._streamed_transform_result(False, "ignored", reason="no_active_drag")
        closest = self._stream_axis_closest_point(x, y, drag["axis_vector"], width, height)
        update = getattr(drag["gesture"], "update_with_line_closest_point", None)
        updated = bool(update(closest)) if callable(update) else False
        live = _copy_matrix_map(getattr(self._transform_model, "_live_transforms", {}))
        return self._streamed_transform_result(
            True,
            "preview",
            axis=drag["axis"],
            pointer=(x, y),
            drag_started=True,
            preview_applied=updated and bool(live),
            live_paths=tuple(live),
            reason="real_translate_gesture_changed",
        )

    def _end_streamed_transform_drag(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        drag = self._streamed_transform_drag
        if not drag:
            return self._streamed_transform_result(False, "ignored", reason="no_active_drag")
        self._update_streamed_transform_drag(x, y, width, height)
        initial = _copy_matrix_map(drag.get("initial_transforms", {}))
        live = _copy_matrix_map(getattr(self._transform_model, "_live_transforms", {}))
        changed_paths = tuple(
            path for path, matrix in live.items()
            if path in initial and not _stream_matrices_close(initial[path], matrix)
        )
        end = getattr(drag["gesture"], "end_streamed_drag", None)
        committed = bool(end()) if callable(end) else False
        undo_after = self._undo_can_undo()
        self._streamed_transform_drag = None
        return self._streamed_transform_result(
            True,
            "commit",
            axis=drag["axis"],
            pointer=(x, y),
            pointer_start=drag.get("pointer_start"),
            drag_started=True,
            preview_applied=bool(live),
            committed=committed and bool(changed_paths),
            changed_paths=changed_paths,
            live_paths=tuple(live),
            command_history_added=committed and bool(changed_paths),
            usd_changed=committed and bool(changed_paths),
            undo_changed=undo_after != drag.get("undo_before"),
            reason="real_translate_gesture_ended",
        )

    def cancel_active_transform_drag(self, *, reason: str = "escape") -> bool:
        """Cancel whichever transform drag is active — streamed bridge
        input or a native gesture — so the eventual physical mouse-up
        cannot commit. ``True`` when an active drag was cancelled."""
        if self._streamed_transform_drag is not None:
            result = self._cancel_streamed_transform_drag(reason=reason)
            return bool(result.get("handled"))
        manipulator = self._transform_manipulator
        if manipulator is not None:
            for gesture in (
                *(getattr(manipulator, "_translate_drags", ()) or ()),
                *(getattr(manipulator, "_rotate_drags", ()) or ()),
                *(getattr(manipulator, "_scale_drags", ()) or ()),
                getattr(manipulator, "_uniform_scale_drag", None),
            ):
                if gesture is None or not getattr(gesture, "is_active", False):
                    continue
                cancel = (getattr(gesture, "cancel_streamed_drag", None)
                          or getattr(gesture, "cancel_active_drag", None))
                if callable(cancel) and bool(cancel()):
                    return True
        # A model-side drag with no active gesture still rolls back.
        model = self._transform_model
        if model is not None and getattr(model, "_drag_active", False):
            try:
                model.on_drag_cancelled()
            except Exception as exc:
                _shielded_report(
                    "ViewportWidget",
                    "drag cancellation reported an error; the drag "
                    "was finalized and the preview may need recovery", exc)
            return True
        return False

    def _cancel_streamed_transform_drag(self, *, reason: str) -> dict[str, Any]:
        drag = self._streamed_transform_drag
        if not drag:
            return self._streamed_transform_result(False, "ignored", reason="no_active_drag")
        cancel = getattr(drag["gesture"], "cancel_streamed_drag", None)
        canceled = bool(cancel()) if callable(cancel) else False
        self._streamed_transform_drag = None
        return self._streamed_transform_result(
            True,
            "cancel",
            axis=drag["axis"],
            pointer=None,
            pointer_start=drag.get("pointer_start"),
            drag_started=True,
            cancel_restored=canceled,
            reason=reason,
        )

    def _streamed_transform_result(
        self,
        handled: bool,
        phase: str,
        *,
        axis: str = "",
        pointer: tuple[int, int] | None = None,
        pointer_start: tuple[int, int] | None = None,
        drag_started: bool = False,
        preview_applied: bool = False,
        committed: bool = False,
        cancel_restored: bool = False,
        command_history_added: bool = False,
        usd_changed: bool = False,
        undo_changed: bool = False,
        changed_paths: tuple[str, ...] = (),
        live_paths: tuple[str, ...] = (),
        reason: str = "",
    ) -> dict[str, Any]:
        selected = tuple(getattr(self._transform_model, "_selected_paths", ()) or ())
        result = {
            "handled": bool(handled),
            "active": self._streamed_transform_drag is not None,
            "phase": phase,
            "axis": axis,
            "pointer": pointer,
            "pointer_start": pointer_start
            if pointer_start is not None
            else (
                self._streamed_transform_drag.get("pointer_start")
                if self._streamed_transform_drag is not None
                else pointer
            ),
            "drag_started": bool(drag_started),
            "preview_applied": bool(preview_applied),
            "committed": bool(committed),
            "cancel_restored": bool(cancel_restored),
            "command_history_added": bool(command_history_added),
            "usd_changed": bool(usd_changed),
            "property_changed": bool(committed and changed_paths),
            "undo_changed": bool(undo_changed),
            "changed_paths": list(changed_paths),
            "live_paths": list(live_paths),
            "selected_paths": list(selected),
            "active_tool": "move",
            "ovui_tool": TOOL_TRANSLATE,
            "reason": reason,
            "message": "Real ovui translate manipulator handled streamed input." if handled else "",
        }
        raw_selected = tuple(getattr(self._transform_model, "_raw_selected_paths", ()) or ())
        bus_paths: tuple[str, ...] = ()
        if self._bus is not None:
            try:
                snapshot = self._bus.get_snapshot()
                bus_paths = tuple(snapshot.paths()) if snapshot is not None else ()
            except Exception:
                bus_paths = ()
        result["raw_selected_paths"] = list(raw_selected)
        result["bus_paths"] = list(bus_paths)
        result["viewport_id"] = id(self)
        result["selection_bus_id"] = id(self._bus) if self._bus is not None else 0
        result["transform_model_id"] = id(self._transform_model) if self._transform_model is not None else 0
        return result

    def _hit_streamed_translate_handle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> dict[str, Any] | None:
        pivot = self._transform_model.get_pivot_world()
        scale = self._streamed_gizmo_scale()
        best: dict[str, Any] | None = None
        for name, axis in (
            ("x", (1.0, 0.0, 0.0)),
            ("y", (0.0, 1.0, 0.0)),
            ("z", (0.0, 0.0, 1.0)),
        ):
            start = self._project_stream_world(pivot, width, height)
            end_world = (
                float(pivot[0]) + axis[0] * scale * 1.2,
                float(pivot[1]) + axis[1] * scale * 1.2,
                float(pivot[2]) + axis[2] * scale * 1.2,
            )
            end = self._project_stream_world(end_world, width, height)
            if start is None or end is None:
                continue
            dist = _point_to_segment_distance(float(x), float(y), start, end)
            if best is None or dist < best["distance_px"]:
                best = {"axis": name, "axis_vector": axis, "distance_px": dist}
        if best is None:
            return None
        if float(best["distance_px"]) > 16.0:
            return None
        return best

    def get_streamed_transform_handle_projections(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Return real viewport-projected transform handle segments.

        Browser QA sends pointer events in stream-pixel coordinates. This
        readonly public diagnostic exposes the exact handle segments computed
        by the stock viewport for that coordinate space, using the same camera,
        pivot, and scale math as ``handle_streamed_transform_pointer_event``.
        It does not synthesize handles or transform state.
        """

        w, h = self._streamed_input_extent(width, height)
        selected = list(getattr(self._transform_model, "_selected_paths", ()) or ())
        raw_selected = list(getattr(self._transform_model, "_raw_selected_paths", ()) or ())
        if self._transform_model is None or not selected:
            return {
                "available": False,
                "reason": "no_transformable_selection",
                "width": w,
                "height": h,
                "selected_paths": selected,
                "raw_selected_paths": raw_selected,
                "viewport_id": id(self),
                "selection_bus_id": id(self._bus) if self._bus is not None else 0,
                "transform_model_id": id(self._transform_model) if self._transform_model is not None else 0,
                "axes": [],
            }
        pivot = tuple(float(value) for value in self._transform_model.get_pivot_world())
        scale = float(self._streamed_gizmo_scale())
        start = self._project_stream_world(pivot, w, h)
        axes = []
        for name, axis in (
            ("x", (1.0, 0.0, 0.0)),
            ("y", (0.0, 1.0, 0.0)),
            ("z", (0.0, 0.0, 1.0)),
        ):
            end_world = (
                pivot[0] + axis[0] * scale * 1.2,
                pivot[1] + axis[1] * scale * 1.2,
                pivot[2] + axis[2] * scale * 1.2,
            )
            end = self._project_stream_world(end_world, w, h)
            axes.append(
                {
                    "axis": name,
                    "start": list(start) if start is not None else None,
                    "end": list(end) if end is not None else None,
                }
            )
        return {
            "available": start is not None and any(axis["end"] is not None for axis in axes),
            "reason": "projected" if start is not None else "projection_unavailable",
            "width": w,
            "height": h,
            "selected_paths": selected,
            "raw_selected_paths": raw_selected,
            "viewport_id": id(self),
            "selection_bus_id": id(self._bus) if self._bus is not None else 0,
            "transform_model_id": id(self._transform_model) if self._transform_model is not None else 0,
            "pivot": list(pivot),
            "scale": scale,
            "axes": axes,
        }

    def _stream_axis_closest_point(
        self,
        x: int,
        y: int,
        axis: tuple[float, float, float],
        width: int,
        height: int,
    ) -> tuple[float, float, float]:
        pivot = self._transform_model.get_pivot_world()
        ray = self._stream_world_ray(x, y, width, height)
        if ray is None:
            return tuple(float(value) for value in pivot)
        origin, direction = ray
        return _closest_point_on_axis_to_ray(
            tuple(float(value) for value in pivot),
            axis,
            origin,
            direction,
        )

    def _streamed_gizmo_scale(self) -> float:
        try:
            scale = float(self._get_gizmo_world_scale())
        except Exception:
            scale = 0.0
        return scale if scale > 0.0 else 0.05

    def _streamed_input_extent(
        self,
        width: int | None,
        height: int | None,
    ) -> tuple[int, int]:
        if width and height:
            return max(1, int(width)), max(1, int(height))
        try:
            w, h = self._get_viewport_size()
        except Exception:
            w, h = self._width, self._height
        return max(1, int(w)), max(1, int(h))

    def _project_stream_world(
        self,
        point: tuple[float, float, float],
        width: int,
        height: int,
    ) -> tuple[float, float] | None:
        try:
            view, projection = self._camera.get_matrices(width, height)
            clip = _mat_vec_mul(_matrix_rows(projection), _mat_vec_mul(_matrix_rows(view), [point[0], point[1], point[2], 1.0]))
        except Exception:
            return None
        w = float(clip[3])
        if abs(w) < 1.0e-8:
            return None
        ndc_x = float(clip[0]) / w
        ndc_y = float(clip[1]) / w
        return (
            (ndc_x + 1.0) * 0.5 * float(width),
            (1.0 - ndc_y) * 0.5 * float(height),
        )

    def _stream_world_ray(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        try:
            view, projection = self._camera.get_matrices(width, height)
            view_projection = _mat_mul(_matrix_rows(projection), _matrix_rows(view))
            inv = _invert_matrix_4x4(view_projection)
        except Exception:
            inv = None
        if inv is None:
            return None
        denom_w = max(1.0, float(width - 1))
        denom_h = max(1.0, float(height - 1))
        ndc_x = (float(x) / denom_w) * 2.0 - 1.0
        ndc_y = 1.0 - (float(y) / denom_h) * 2.0
        near = _homogeneous_to_xyz(_mat_vec_mul(inv, [ndc_x, ndc_y, -1.0, 1.0]))
        far = _homogeneous_to_xyz(_mat_vec_mul(inv, [ndc_x, ndc_y, 1.0, 1.0]))
        if near is None or far is None:
            return None
        direction = _normalize3((far[0] - near[0], far[1] - near[1], far[2] - near[2]))
        if direction is None:
            return None
        return near, direction

    def _undo_can_undo(self) -> bool:
        undo = getattr(self._transform_model, "_undo", None)
        can_undo = getattr(undo, "can_undo", None)
        if callable(can_undo):
            try:
                return bool(can_undo())
            except Exception:
                return False
        return False

    def _iter_toolbar_tool_specs(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(spec for spec in _TOOLBAR_TOOL_SPECS if spec[0] in VALID_TOOLS)

    def _resolution_missing_icon_profile_active(self) -> bool:
        """Return whether A7-T08 should use labeled icon fallbacks."""

        if _env_flag_enabled(AREA7_MISSING_ICON_QA_ENV):
            return True
        renderer = self.renderer_adapter
        return bool(getattr(renderer, "resolution_missing_icon_profile", False))

    def _resolution_ovui_only_profile_active(self) -> bool:
        """Return whether the visible ovui-only runtime QA profile is active."""

        if _env_flag_enabled(AREA7_OVUI_ONLY_RUNTIME_QA_ENV):
            return True
        renderer = self.renderer_adapter
        return bool(getattr(renderer, "resolution_ovui_only_runtime_profile", False))

    def _settings_toolbar_icon_path(self) -> str | None:
        """Resolve the Settings glyph, falling back to a labeled button."""

        icon_names = (
            (_SETTINGS_TOOLBAR_FALLBACK_ICON_NAME,)
            if self._resolution_missing_icon_profile_active()
            else (_SETTINGS_TOOLBAR_ICON_NAME, _SETTINGS_TOOLBAR_FALLBACK_ICON_NAME)
        )
        try:
            from ovui_widgets.common.style.urls import get_icon_path
        except (ImportError, ModuleNotFoundError):
            return None
        for icon_name in icon_names:
            try:
                icon_path = get_icon_path(icon_name)
            except (KeyError, OSError, TypeError, ValueError):
                continue
            if icon_path and os.path.exists(icon_path):
                return icon_path
        return None

    def _resolution_icon_fallback_kwargs(self, *affordances: str) -> dict[str, Any]:
        """QA-visible fallback affordance metadata for existing menu controls."""

        if not self._resolution_missing_icon_profile_active():
            return {}
        fallback_affordances = tuple(
            str(affordance) for affordance in affordances if affordance
        )
        if not fallback_affordances:
            return {}
        return {
            "icon_fallback_profile": _RESOLUTION_MISSING_ICON_PROFILE_LABEL,
            "icon_fallback_affordances": fallback_affordances,
        }

    @staticmethod
    def _resolution_inspector_suffix(value: Any) -> str:
        """Return a deterministic suffix for inspector target identifiers."""

        suffix = "".join(
            character.lower() if character.isalnum() else "_"
            for character in str(value or "")
        ).strip("_")
        while "__" in suffix:
            suffix = suffix.replace("__", "_")
        return suffix or "item"

    @classmethod
    def _resolution_inspector_target(cls, prefix: str, value: Any) -> str:
        return f"{prefix}_{cls._resolution_inspector_suffix(value)}"

    @staticmethod
    def _resolution_keyboard_metadata(
        *,
        target: str,
        label: str,
        focus_order: int,
        activation_keys: tuple[str, ...] = ("Enter", "Space"),
        dismiss_keys: tuple[str, ...] = ("Escape",),
        reason: str = "",
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "inspector_target": target,
            "accessibility_label": label,
            "visible_label": label,
            "keyboard_focus_order": int(focus_order),
            "keyboard_activation_keys": tuple(activation_keys),
            "keyboard_dismiss_keys": tuple(dismiss_keys),
            "focus_visible": True,
            "stable_geometry": True,
        }
        if reason:
            metadata.update(
                {
                    "disabled_focusable": True,
                    "disabled_reason_visible": reason,
                    "disabled_reason_tooltip": reason,
                }
            )
        return metadata

    def _register_viewport_settings_toolbar_button(self) -> None:
        """Install the product Settings gear in the leading toolbar host."""

        def _build(
            context: ViewportResolutionHostContext,
        ) -> ViewportToolbarMenu:
            return ViewportToolbarMenu(
                id=context.attachment_id,
                label="Settings",
                order=0,
                tooltip="Settings",
                icon_path=self._settings_toolbar_icon_path(),
                widget_name=_SETTINGS_TOOLBAR_WIDGET,
                build_fn=lambda owner, ui_module: owner._build_settings_toolbar_menu(
                    ui_module
                ),
            )

        self.attach_resolution_toolbar_host(_build)

    def _build_settings_toolbar_menu(self, ui_module: Any) -> None:
        """Build the first-hop Settings menu for this viewport."""

        self._refresh_resolution_settings_for_menu_open()
        with ui_module.Menu(
            _SETTINGS_MENU_VIEWPORT_LABEL,
            identifier="viewport_settings_viewport_menu",
            tooltip=_SETTINGS_MENU_VIEWPORT_LABEL,
            **self._resolution_keyboard_metadata(
                target="viewport_settings_viewport_menu",
                label=_SETTINGS_MENU_VIEWPORT_LABEL,
                focus_order=1,
            ),
        ):
            self._build_viewport_settings_submenu(ui_module)

    def _current_render_resolution_menu_label(self) -> str:
        """Return the Area-2 current label for the menu snapshot."""

        selection = self._current_render_resolution_catalog_selection()
        if selection is not None:
            return selection.current_label
        return str(self._resolution_state.selected_label or "Viewport")

    def _current_render_resolution_catalog_selection(self) -> Any:
        """Return the Area-2 selection snapshot for render-resolution rows."""

        saved_custom_entries: Iterable[Any] = self.get_resolution_settings().custom_list
        return select_resolution_catalog_row_for_state(
            self._resolution_state,
            saved_custom_entries=saved_custom_entries,
        )

    def _refresh_resolution_settings_for_menu_open(self) -> None:
        """Capture current shared settings before rebuilding reopened menus."""

        settings = self._resolve_settings()
        if settings is None:
            return
        self._sync_resolution_shared_settings_snapshot(self.get_resolution_settings())

    def _resolution_custom_list_warning_message(self) -> str:
        """Return a non-blocking warning for malformed saved-custom data."""

        settings = self._resolve_settings()
        getter = getattr(settings, "get", None)
        if not callable(getter):
            return ""
        missing = object()
        raw_value = getter(SETTING_CUSTOM_RESOLUTION_LIST, missing)
        if raw_value is missing:
            return ""
        normalized_entries = normalize_loaded_custom_resolution_list(raw_value)
        if not isinstance(raw_value, (list, tuple)):
            return _RESOLUTION_CORRUPT_CUSTOM_LIST_WARNING
        if len(normalized_entries) < len(raw_value):
            return _RESOLUTION_CORRUPT_CUSTOM_LIST_WARNING
        return ""

    def _resolution_menu_failure_reason(self) -> str:
        """Return the active A7 menu-data failure reason, if any."""

        if _env_flag_enabled(AREA7_MENU_FAILURE_QA_ENV):
            return _RESOLUTION_MENU_FAILURE_REASON
        renderer = self._renderer
        if renderer is None:
            return ""
        for attribute_name in (
            "resolution_menu_failure_reason",
            "resolution_menu_data_failure_reason",
            "render_resolution_menu_failure_reason",
        ):
            try:
                value = getattr(renderer, attribute_name)
            except AttributeError:
                continue
            except Exception:
                return _RESOLUTION_MENU_FAILURE_REASON
            if callable(value):
                try:
                    value = value()
                except Exception:
                    return _RESOLUTION_MENU_FAILURE_REASON
            if value is True:
                return _RESOLUTION_MENU_FAILURE_REASON
            if value:
                return str(value)
        for attribute_name in (
            "fail_resolution_menu_data",
            "fail_render_resolution_menu",
        ):
            try:
                value = getattr(renderer, attribute_name)
            except AttributeError:
                continue
            except Exception:
                return _RESOLUTION_MENU_FAILURE_REASON
            if callable(value):
                try:
                    value = value()
                except Exception:
                    return _RESOLUTION_MENU_FAILURE_REASON
            if value:
                return _RESOLUTION_MENU_FAILURE_REASON
        return ""

    def _resolution_menu_fallback_reason(self, reason: Any = "") -> str:
        text = str(reason or "").strip()
        return text or _RESOLUTION_MENU_FAILURE_REASON

    def _resolution_max_reason_text(self) -> str:
        limits = self._resolution_state.clamp_limits
        return _RESOLUTION_OVER_MAX_PRESET_REASON_TEMPLATE.format(
            max_width=limits.max_width,
            max_height=limits.max_height,
        )

    def _resolution_max_clamp_warning_text(self) -> str:
        limits = self._resolution_state.clamp_limits
        return _RESOLUTION_MAX_CLAMP_WARNING_TEMPLATE.format(
            max_width=limits.max_width,
            max_height=limits.max_height,
        )

    def _resolution_native_preset_disabled_reason(self, row: Any) -> str:
        """Return the A7 over-max reason for native preset rows."""

        if getattr(row, "kind", "") != RESOLUTION_CATALOG_KIND_PRESET:
            return ""
        dimensions = getattr(row, "dimensions", None)
        if dimensions is None:
            return ""
        try:
            width, height = int(dimensions[0]), int(dimensions[1])
        except (TypeError, ValueError, IndexError):
            return ""
        limits = self._resolution_state.clamp_limits
        if width > limits.max_width or height > limits.max_height:
            return self._resolution_max_reason_text()
        return ""

    def _renderer_supports_fixed_resolution_requests(self) -> bool:
        """Return whether the renderer explicitly supports fixed requests.

        Existing adapters do not need to advertise this; unsupported profiles
        opt out with a small capability fact on the renderer adapter.
        """

        renderer = self._renderer
        if renderer is None:
            return True
        for attribute_name in (
            "supports_fixed_resolution",
            "supports_fixed_resolution_requests",
            "supports_fixed_render_resolution",
            "fixed_resolution_supported",
        ):
            try:
                value = getattr(renderer, attribute_name)
            except AttributeError:
                continue
            except Exception:
                return False
            if callable(value):
                try:
                    value = value()
                except Exception:
                    return False
            return bool(value)
        return True

    def _resolution_fixed_unsupported_reason(self) -> str:
        """Return the A7 unsupported-fixed adapter reason when explicit."""

        if self._resolution_unavailable_reason():
            return ""
        if self._renderer_supports_fixed_resolution_requests():
            return ""
        return _RESOLUTION_UNAVAILABLE_FIXED_UNSUPPORTED_REASON

    def _fixed_resolution_controls_disabled_reason(self) -> str:
        """Return the reason for controls that can apply fixed dimensions."""

        return (
            self._resolution_unavailable_reason()
            or self._resolution_fixed_unsupported_reason()
        )

    def _render_resolution_row_requires_fixed_request(self, row: Any) -> bool:
        """Return true for rows that would ask the renderer for fixed size."""

        if row == VIEWPORT_RESOLUTION_SENTINEL:
            return False
        if row == CUSTOM_RESOLUTION_SENTINEL:
            return True
        requested_size = self._requested_size_for_render_resolution_row(row)
        return (
            requested_size is not None
            and requested_size != VIEWPORT_SENTINEL_DIMENSIONS
        )

    def _render_resolution_row_disabled_reason(self, row: Any) -> str:
        """Return the visible disabled reason for one Render Resolution row."""

        fixed_unsupported_reason = (
            self._resolution_fixed_unsupported_reason()
            if self._render_resolution_row_requires_fixed_request(row)
            else ""
        )
        return (
            self._resolution_unavailable_reason()
            or fixed_unsupported_reason
            or self._resolution_native_preset_disabled_reason(row)
        )

    def _resolution_max_clamp_warning_message(self) -> str:
        """Return a non-blocking warning when accepted state clamps at max."""

        if not self._resolution_state.is_fixed_mode:
            return ""
        try:
            if self._resolution_state.fill_viewport:
                visible_frame_size = self._visible_viewport_frame_size_for_render()
                if visible_frame_size is None:
                    return ""
                effective = self._compute_fixed_mode_effective_resolution(
                    visible_frame_size
                )
            else:
                effective = compute_fixed_mode_effective_resolution_for_state(
                    self._resolution_state
                )
        except Exception:
            return ""
        limits = self._resolution_state.clamp_limits
        scaled_width, scaled_height = effective.scaled_size
        if scaled_width > limits.max_width or scaled_height > limits.max_height:
            return self._resolution_max_clamp_warning_text()
        return ""

    def _resolution_unavailable_reason(self) -> str:
        """Return the Area-7 disabled reason for resolution-changing controls."""

        availability = self.get_resolution_availability()
        if not availability.renderer_available:
            return _RESOLUTION_UNAVAILABLE_NO_RENDERER_REASON
        if self._resolution_settings_unavailable_for_policy(availability):
            return _RESOLUTION_UNAVAILABLE_SETTINGS_REASON
        if not self._resolution_stage_available_for_policy():
            return _RESOLUTION_UNAVAILABLE_NO_STAGE_REASON
        return ""

    def _resolution_settings_unavailable_for_policy(self, availability: Any) -> bool:
        """Return whether this widget is in the explicit missing-settings profile.

        Some isolated widget tests intentionally omit the service bundle and do
        not represent the visible missing-settings app profile. Only an
        installed service bundle with ``settings=None`` activates the Area-7
        settings-service degraded policy.
        """

        if availability.settings_available:
            return False
        return self._services is not None and hasattr(self._services, "settings")

    def _resolution_stage_available_for_policy(self) -> bool:
        """Return whether the explicit app stage provider has a loaded stage.

        Test and standalone widget paths often omit a stage provider entirely.
        That is not the no-stage app profile; only an installed provider that
        reports no adapter, or an adapter with a null ``stage`` attribute,
        activates the Area-7 no-stage degraded policy.
        """

        if self._stage_adapter_provider is None:
            return True
        try:
            adapter = self._get_stage_adapter()
        except Exception:
            return False
        if adapter is None:
            return False
        if hasattr(adapter, "stage") and getattr(adapter, "stage", None) is None:
            return False
        return True

    def _resolution_controls_available(self) -> bool:
        return not bool(self._resolution_unavailable_reason())

    def _fixed_resolution_controls_available(self) -> bool:
        return not bool(self._fixed_resolution_controls_disabled_reason())

    def _custom_resolution_editor_default_size(self) -> tuple[int, int]:
        """Return the accepted positive dimensions shown in the inline editor."""

        for requested_size in (
            self.get_resolution_settings().resolution,
            self._resolution_state.requested_size,
        ):
            try:
                width, height = int(requested_size[0]), int(requested_size[1])
            except (TypeError, ValueError, IndexError):
                continue
            if width > 0 and height > 0:
                return width, height
        return 1920, 1080

    def _custom_resolution_editor_bounds(self) -> tuple[int, int, int, int]:
        """Return user-facing custom field bounds from A1/A3 owners."""

        limits = self._resolution_state.clamp_limits
        min_width = limits.min_width
        min_height = limits.min_height
        try:
            resolved_min = self.get_resolution_settings().min_resolution
            candidate_min_width = int(resolved_min[0])
            candidate_min_height = int(resolved_min[1])
        except (TypeError, ValueError, IndexError):
            candidate_min_width = candidate_min_height = 0
        if candidate_min_width > 0 and candidate_min_height > 0:
            min_width = candidate_min_width
            min_height = candidate_min_height

        max_width = max(min_width, limits.max_width)
        max_height = max(min_height, limits.max_height)
        return (min_width, min_height, max_width, max_height)

    def _coerce_custom_resolution_field_size(
        self,
        width: Any,
        height: Any,
    ) -> tuple[int, int] | None:
        try:
            requested_size = (int(width), int(height))
        except (TypeError, ValueError):
            return None
        if requested_size[0] <= 0 or requested_size[1] <= 0:
            return None
        return requested_size

    def _custom_resolution_save_enabled_for_dimensions(
        self,
        width: Any,
        height: Any,
    ) -> bool:
        """Return true only for valid dimensions that do not duplicate catalog rows."""

        if not self._fixed_resolution_controls_available():
            return False
        requested_size = self._coerce_custom_resolution_field_size(width, height)
        if requested_size is None:
            return False
        match = match_resolution_catalog_row_for_requested_size(
            requested_size,
            saved_custom_entries=self.get_resolution_settings().custom_list,
        )
        return (
            match is not None
            and getattr(match.row, "key", None) == CUSTOM_RESOLUTION_SENTINEL.key
        )

    def _active_custom_resolution_save_size(self) -> tuple[int, int] | None:
        """Return the accepted custom size that may open the save dialog."""

        requested_size = self._coerce_custom_resolution_field_size(
            *self._custom_resolution_editor_default_size()
        )
        if requested_size is None:
            return None
        if not self._custom_resolution_save_enabled_for_dimensions(*requested_size):
            return None
        return requested_size

    @staticmethod
    def _set_string_field_value(field: Any, value: str) -> None:
        model = getattr(field, "model", None)
        if model is None:
            return
        try:
            model.set_value(str(value))
        except (AttributeError, TypeError, ValueError):
            return

    @staticmethod
    def _get_string_field_value(field: Any) -> str:
        model = getattr(field, "model", None)
        if model is None:
            return ""
        try:
            return str(model.get_value_as_string())
        except (AttributeError, TypeError, ValueError):
            return ""

    @staticmethod
    def _set_label_text(label: Any, value: str) -> None:
        if label is None:
            return
        try:
            label.text = str(value)
        except (AttributeError, TypeError):
            pass

    def _set_custom_resolution_save_dialog_error(self, message: str) -> None:
        self._set_label_text(self._custom_resolution_save_dialog_error_label, message)

    def _custom_resolution_save_dialog_name_exists(self, name: str) -> bool:
        for entry in self.get_resolution_settings().custom_list:
            try:
                entry_name = str(entry.get("name", "")).strip()
            except AttributeError:
                continue
            if entry_name == name:
                return True
        return False

    def _refresh_custom_resolution_save_dialog(
        self,
        requested_size: tuple[int, int],
    ) -> None:
        """Refresh visible dialog content for the active custom dimensions."""

        self._custom_resolution_save_dialog_size = requested_size
        width, height = requested_size
        resolution_text = f"{width} x {height}"
        label = self._custom_resolution_save_dialog_resolution_label
        if label is not None:
            try:
                label.text = resolution_text
            except (AttributeError, TypeError):
                pass
        field = self._custom_resolution_save_dialog_name_field
        if field is not None:
            self._set_string_field_value(field, "")
        self._set_custom_resolution_save_dialog_error("")
        save_button = self._custom_resolution_save_dialog_save_button
        if save_button is not None:
            try:
                save_button.enabled = True
            except (AttributeError, TypeError):
                pass

    def _close_custom_resolution_save_dialog(self) -> bool:
        """Dismiss the save dialog without mutating resolution state."""

        window = self._custom_resolution_save_dialog_window
        if window is not None:
            try:
                window.visible = False
            except (AttributeError, TypeError):
                pass
        return False

    def _destroy_custom_resolution_save_dialog(self) -> None:
        window = self._custom_resolution_save_dialog_window
        self._custom_resolution_save_dialog_window = None
        self._custom_resolution_save_dialog_name_field = None
        self._custom_resolution_save_dialog_resolution_label = None
        self._custom_resolution_save_dialog_error_label = None
        self._custom_resolution_save_dialog_save_button = None
        self._custom_resolution_save_dialog_size = None
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            try:
                window.visible = False
            except Exception:
                pass

    def _open_custom_resolution_save_dialog(self) -> bool:
        """Open the Area-5 save dialog from the enabled inline save icon."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        requested_size = self._active_custom_resolution_save_size()
        if requested_size is None:
            return False

        window = self._custom_resolution_save_dialog_window
        if window is not None:
            self._refresh_custom_resolution_save_dialog(requested_size)
            try:
                window.visible = True
            except (AttributeError, TypeError):
                pass
            set_top_modal = getattr(window, "set_top_modal", None)
            if callable(set_top_modal):
                try:
                    set_top_modal(True)
                except Exception:
                    pass
            self._focus_custom_resolution_save_dialog_name_field()
            return True

        flags = (
            getattr(ui, "WINDOW_FLAGS_MODAL", 0)
            | getattr(ui, "WINDOW_FLAGS_NO_RESIZE", 0)
            | getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
            | getattr(ui, "WINDOW_FLAGS_NO_SCROLLBAR", 0)
            | getattr(ui, "WINDOW_FLAGS_NO_COLLAPSE", 0)
        )
        window = ui.Window(
            _CUSTOM_RESOLUTION_SAVE_DIALOG_TITLE,
            width=_CUSTOM_RESOLUTION_SAVE_DIALOG_WIDTH,
            height=_CUSTOM_RESOLUTION_SAVE_DIALOG_HEIGHT,
            flags=flags,
        )
        self._custom_resolution_save_dialog_window = window
        try:
            window.position_x = 520
            window.position_y = 220
        except Exception:
            pass

        with window.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=6)
                with ui.HStack(height=24, spacing=6):
                    ui.Spacer(width=10)
                    ui.Label(
                        _CUSTOM_RESOLUTION_SAVE_DIALOG_TITLE,
                        alignment=ui.Alignment.LEFT_CENTER,
                        identifier="viewport_custom_resolution_save_dialog_title",
                    )
                    ui.Spacer()
                    ui.Button(
                        "X",
                        width=26,
                        height=22,
                        identifier="viewport_custom_resolution_save_dialog_close",
                        tooltip="Close",
                        clicked_fn=self._close_custom_resolution_save_dialog,
                    )
                    ui.Spacer(width=8)

                with ui.HStack(height=30, spacing=8):
                    ui.Spacer(width=10)
                    ui.Label("Name *", width=78, alignment=ui.Alignment.RIGHT_CENTER)
                    name_field = ui.StringField(
                        width=170,
                        height=24,
                        identifier="viewport_custom_resolution_save_dialog_name",
                        tooltip="Required name",
                    )
                    self._custom_resolution_save_dialog_name_field = name_field
                    set_key_pressed_fn = getattr(name_field, "set_key_pressed_fn", None)
                    if callable(set_key_pressed_fn):
                        set_key_pressed_fn(
                            self._custom_resolution_save_dialog_key_pressed
                        )
                    ui.Label(
                        "(required)",
                        width=76,
                        alignment=ui.Alignment.LEFT_CENTER,
                    )
                    ui.Spacer(width=10)

                with ui.HStack(height=24, spacing=8):
                    ui.Spacer(width=10)
                    ui.Label(
                        "Resolution",
                        width=78,
                        alignment=ui.Alignment.RIGHT_CENTER,
                    )
                    resolution_label = ui.Label(
                        "",
                        identifier=(
                            "viewport_custom_resolution_save_dialog_resolution"
                        ),
                        alignment=ui.Alignment.LEFT_CENTER,
                    )
                    self._custom_resolution_save_dialog_resolution_label = (
                        resolution_label
                    )
                    ui.Spacer(width=10)

                with ui.HStack(height=20, spacing=8):
                    ui.Spacer(width=10)
                    ui.Spacer(width=78)
                    error_label = ui.Label(
                        "",
                        identifier="viewport_custom_resolution_save_dialog_error",
                        alignment=ui.Alignment.LEFT_CENTER,
                    )
                    self._custom_resolution_save_dialog_error_label = error_label
                    ui.Spacer(width=10)

                with ui.HStack(height=30, spacing=8):
                    ui.Spacer()
                    save_button = ui.Button(
                        "Save",
                        width=82,
                        height=24,
                        identifier="viewport_custom_resolution_save_dialog_save",
                        tooltip="Save custom resolution",
                        clicked_fn=self._save_custom_resolution_from_dialog,
                    )
                    self._custom_resolution_save_dialog_save_button = save_button
                    try:
                        save_button.enabled = True
                    except (AttributeError, TypeError):
                        pass
                    ui.Button(
                        "Cancel",
                        width=82,
                        height=24,
                        identifier="viewport_custom_resolution_save_dialog_cancel",
                        tooltip="Cancel",
                        clicked_fn=self._close_custom_resolution_save_dialog,
                    )
                    ui.Spacer(width=10)
                ui.Spacer()

        self._refresh_custom_resolution_save_dialog(requested_size)
        set_top_modal = getattr(window, "set_top_modal", None)
        if callable(set_top_modal):
            try:
                set_top_modal(True)
            except Exception:
                pass
        self._focus_custom_resolution_save_dialog_name_field()
        return True

    def _focus_custom_resolution_save_dialog_name_field(self) -> None:
        """Focus the save dialog name field when the platform exposes it."""

        field = self._custom_resolution_save_dialog_name_field
        focus_keyboard = getattr(field, "focus_keyboard", None)
        if callable(focus_keyboard):
            try:
                focus_keyboard()
            except Exception:
                pass

    def _custom_resolution_save_dialog_key_pressed(
        self,
        key: int,
        _modifier: int,
        pressed: bool,
    ) -> None:
        """Keyboard affordances for the existing Save Custom dialog."""

        if not pressed:
            return
        try:
            key_code = int(key)
        except (TypeError, ValueError):
            return
        if key_code in (
            _KEY_ENTER,
            _KEY_KEYPAD_ENTER,
            _IMGUI_KEY_ENTER,
            _IMGUI_KEY_KEYPAD_ENTER,
        ):
            self._save_custom_resolution_from_dialog()
        elif key_code in (_KEY_ESCAPE, _IMGUI_KEY_ESCAPE):
            self._close_custom_resolution_save_dialog()

    def _save_custom_resolution_from_dialog(self) -> bool:
        """Validate and append the active custom resolution from the save dialog."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        requested_size = self._custom_resolution_save_dialog_size
        if requested_size is None:
            return False

        name = self._get_string_field_value(
            self._custom_resolution_save_dialog_name_field
        ).strip()
        if not name:
            self._set_custom_resolution_save_dialog_error(
                _CUSTOM_RESOLUTION_SAVE_DIALOG_EMPTY_NAME_ERROR
            )
            return False
        if self._custom_resolution_save_dialog_name_exists(name):
            self._set_custom_resolution_save_dialog_error(
                _CUSTOM_RESOLUTION_SAVE_DIALOG_DUPLICATE_NAME_ERROR
            )
            return False
        if not self._custom_resolution_save_enabled_for_dimensions(*requested_size):
            self._set_custom_resolution_save_dialog_error(
                _CUSTOM_RESOLUTION_SAVE_DIALOG_DUPLICATE_DIMENSIONS_ERROR
            )
            return False

        width, height = requested_size
        try:
            add_shared_custom_resolution_entry(
                self._resolve_settings(),
                {"name": name, "width": width, "height": height},
            )
        except Exception as exc:
            self._last_render_resolution_apply_error = exc
            self._set_custom_resolution_save_dialog_error(str(exc))
            return False

        self._last_render_resolution_apply_error = None
        self._accept_resolution_settings_snapshot(self.get_resolution_settings())
        self._close_custom_resolution_save_dialog()
        return True

    def _commit_custom_resolution_field_size(
        self,
        requested_size: tuple[int, int],
    ) -> bool:
        """Accept typed unsaved dimensions through Area-1/Area-3 owners."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        settings = self._resolve_settings()
        key = viewport_resolution_key(self._viewport_id)
        value = list(requested_size)
        self._mark_resolution_settings_self_origin(key, value)
        try:
            write_viewport_instance_resolution(
                settings,
                self._viewport_id,
                value,
            )
        except Exception as exc:
            self._clear_resolution_settings_self_origin(key)
            self._last_render_resolution_apply_error = exc
            return False
        self._clear_resolution_settings_self_origin(key)

        self._last_render_resolution_apply_error = None
        self._accept_resolution_settings_snapshot(self.get_resolution_settings())
        self._request_render_resolution_apply_refresh()
        return True

    def _apply_custom_resolution_field_values(self, width: Any, height: Any) -> bool:
        """Schedule typed Width/Height end-edit as an unsaved custom apply."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        requested_size = self._coerce_custom_resolution_field_size(width, height)
        if requested_size is None:
            return False

        self._custom_resolution_field_pending_size = requested_size
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pending_size = self._custom_resolution_field_pending_size
            self._custom_resolution_field_pending_size = None
            return self._commit_custom_resolution_field_size(pending_size)

        if self._custom_resolution_field_apply_pending:
            return True
        self._custom_resolution_field_apply_pending = True

        async def _apply_after_one_frame() -> None:
            try:
                await ui.next_frame()
                if self._resolution_sync_is_disposed():
                    return
                pending_size = self._custom_resolution_field_pending_size
                self._custom_resolution_field_pending_size = None
                if pending_size is not None:
                    self._commit_custom_resolution_field_size(pending_size)
            finally:
                self._custom_resolution_field_apply_pending = False

        loop.create_task(_apply_after_one_frame())
        return True

    def _render_scale_combo_snapshot(
        self,
    ) -> tuple[tuple[float, ...], tuple[str, ...], int, str]:
        """Return Area-1 render-scale values/labels and accepted selection."""

        resolved = self.get_resolution_settings()
        current_scale = float(resolved.resolution_scale)
        scale_values: list[float] = []
        for value in resolved.render_scale_list:
            try:
                scale = float(value)
            except (TypeError, ValueError):
                continue
            if scale <= 0.0:
                continue
            if any(abs(scale - existing) <= 1.0e-9 for existing in scale_values):
                continue
            scale_values.append(scale)

        if not any(abs(current_scale - scale) <= 1.0e-9 for scale in scale_values):
            scale_values.insert(0, current_scale)
        if not scale_values:
            scale_values.append(1.0)

        option_labels = tuple(
            _format_render_scale_percent(scale) for scale in scale_values
        )
        current_index = next(
            (
                index
                for index, scale in enumerate(scale_values)
                if abs(current_scale - scale) <= 1.0e-9
            ),
            0,
        )
        return (
            tuple(scale_values),
            option_labels,
            current_index,
            option_labels[current_index],
        )

    def _fill_viewport_checkbox_snapshot(self) -> tuple[bool, bool]:
        """Return visible enabled/checked state for the Fill Viewport row."""

        selection = self._current_render_resolution_catalog_selection()
        viewport_selected = (
            selection is not None
            and getattr(selection, "key", None) == VIEWPORT_RESOLUTION_SENTINEL.key
        )
        if viewport_selected:
            return False, False
        if not self._fixed_resolution_controls_available():
            return False, bool(self.get_resolution_settings().fill_viewport)
        return True, bool(self.get_resolution_settings().fill_viewport)

    def _iter_render_resolution_builtin_rows(self) -> tuple[Any, ...]:
        """Return Area-2 Viewport and visible built-in rows for menu rendering."""

        return (
            VIEWPORT_RESOLUTION_SENTINEL,
            *resolve_visible_resolution_presets(self._resolve_settings()),
        )

    def _iter_render_resolution_saved_custom_rows(self) -> tuple[Any, ...]:
        """Return Area-2 saved-custom rows from the normalized Area-1 list."""

        return iter_saved_custom_resolution_catalog_rows(
            self.get_resolution_settings().custom_list
        )

    def _iter_render_resolution_rows(self) -> tuple[Any, ...]:
        """Return all A4-T05 render-resolution rows in display order."""

        return (
            *self._iter_render_resolution_builtin_rows(),
            CUSTOM_RESOLUTION_SENTINEL,
            *self._iter_render_resolution_saved_custom_rows(),
        )

    def _render_resolution_menu_detail_text(
        self,
        row: Any,
        *,
        delete_affordance: bool = False,
    ) -> str:
        """Format Area-2 row metadata for the right side of a radio row."""

        dimension_text = getattr(row, "resolution_text", "") or getattr(
            row,
            "dimension_text",
            "",
        )
        badge_text = getattr(row, "ratio_badge_label", None)
        if badge_text:
            detail_text = f"{dimension_text}  {badge_text}"
        else:
            detail_text = str(dimension_text)
        if delete_affordance:
            return f"{detail_text}  x"
        return detail_text

    def _requested_size_for_render_resolution_row(
        self,
        row: Any,
    ) -> tuple[int, int] | None:
        """Return the accepted requested size for one Render Resolution row."""

        if row == VIEWPORT_RESOLUTION_SENTINEL:
            return VIEWPORT_SENTINEL_DIMENSIONS
        if row == CUSTOM_RESOLUTION_SENTINEL:
            selection = select_resolution_catalog_row_for_requested_size(
                self._resolution_state.requested_size,
                saved_custom_entries=self.get_resolution_settings().custom_list,
            )
            if (
                selection is not None
                and getattr(selection.row, "key", None) == CUSTOM_RESOLUTION_SENTINEL.key
            ):
                return selection.requested_size
            return None

        dimensions = getattr(row, "dimensions", None)
        if dimensions is None:
            return None
        try:
            width, height = dimensions
        except (TypeError, ValueError):
            return None
        return (int(width), int(height))

    def _accept_resolution_settings_snapshot(
        self,
        resolved: ViewportResolutionSettings,
    ) -> None:
        """Sync accepted viewport state from Area-1 resolved settings."""

        try:
            requested_width, requested_height = resolved.resolution
        except (TypeError, ValueError):
            requested_size = VIEWPORT_SENTINEL_DIMENSIONS
        else:
            requested_size = (int(requested_width), int(requested_height))
        if (
            requested_size != VIEWPORT_SENTINEL_DIMENSIONS
            and not self._renderer_supports_fixed_resolution_requests()
        ):
            requested_size = VIEWPORT_SENTINEL_DIMENSIONS
        mode = (
            RESOLUTION_MODE_VIEWPORT
            if requested_size == VIEWPORT_SENTINEL_DIMENSIONS
            else RESOLUTION_MODE_FIXED
        )
        fill_viewport = (
            bool(resolved.fill_viewport)
            if mode == RESOLUTION_MODE_FIXED
            else False
        )
        selected = select_resolution_catalog_row_for_state(
            self._resolution_state.with_changes(
                mode=mode,
                requested_size=requested_size,
                scale=resolved.resolution_scale,
                fill_viewport=fill_viewport,
                uses_dpi=bool(resolved.resolution_uses_dpi),
                effective_size=None,
            ),
            saved_custom_entries=resolved.custom_list,
        )
        self.set_resolution_state(
            mode=mode,
            requested_size=requested_size,
            scale=resolved.resolution_scale,
            fill_viewport=fill_viewport,
            uses_dpi=bool(resolved.resolution_uses_dpi),
            selected_label=(
                selected.current_label if selected is not None else "Custom"
            ),
            effective_size=None,
        )

    def _per_viewport_resolution_setting_keys(self) -> tuple[str, str, str]:
        """Return the concrete per-viewport Area-1 keys owned by A6-T01."""

        return (
            viewport_resolution_key(self._viewport_id),
            viewport_resolution_scale_key(self._viewport_id),
            viewport_fill_viewport_key(self._viewport_id),
        )

    def _shared_resolution_setting_keys(self) -> tuple[str, str, str]:
        """Return the shared Area-1 keys whose menus A6-T02 refreshes."""

        return (
            SETTING_CUSTOM_RESOLUTION_LIST,
            SETTING_RESOLUTION_PRESETS,
            SETTING_RENDER_SCALE_LIST,
        )

    def _install_resolution_settings_subscription(self) -> None:
        """Watch this viewport's resolution settings and accept external changes."""

        self._destroy_resolution_settings_subscription()
        settings = self._resolve_settings()
        if settings is None:
            return
        if not callable(getattr(settings, "subscribe", None)):
            resolved = self.get_resolution_settings()
            self._accept_resolution_settings_snapshot(resolved)
            self._sync_resolution_shared_settings_snapshot(resolved)
            return
        try:
            self._resolution_settings_subscription = (
                subscribe_resolution_settings_changes(
                    settings,
                    self._viewport_id,
                    self._on_resolution_settings_change,
                )
            )
        except (TypeError, ValueError):
            self._resolution_settings_subscription = None
        resolved = self.get_resolution_settings()
        self._accept_resolution_settings_snapshot(resolved)
        self._sync_resolution_shared_settings_snapshot(resolved)

    def _destroy_resolution_settings_subscription(self) -> None:
        """Cancel the live Area-1 settings watcher for this viewport."""

        subscription = self._resolution_settings_subscription
        self._resolution_settings_subscription = None
        self._resolution_settings_self_origin_values.clear()
        self._resolution_shared_settings_values.clear()
        if subscription is None:
            return
        cancel = getattr(subscription, "cancel", None)
        if callable(cancel):
            cancel()

    def _resolution_sync_is_disposed(self) -> bool:
        """Return whether Area-6 synchronization must ignore late callbacks."""

        return bool(self._resolution_state_observers_closed) or bool(
            self._viewport_id_released
        )

    def _cancel_resolution_sync_pending_work(self) -> None:
        """Detach lifecycle-owned sync hooks without owning UI rendering."""

        self._resolution_render_refresh_pending = False
        self._viewport_resize_render_refresh_pending = False
        self._settings_menu_reshow_pending = False
        self._settings_menu_dismiss_pending = False
        self._custom_resolution_field_apply_pending = False
        self._custom_resolution_field_pending_size = None
        self._last_viewport_mode_visible_frame_size = None
        self._last_fill_viewport_visible_frame_size = None
        self._dismiss_settings_toolbar_menu()
        self._destroy_custom_resolution_save_dialog()
        self._clear_settings_menu_control_callbacks()

    def _copy_resolution_settings_value(self, value: Any) -> Any:
        if isinstance(value, tuple):
            return [self._copy_resolution_settings_value(item) for item in value]
        if isinstance(value, list):
            return [self._copy_resolution_settings_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._copy_resolution_settings_value(inner)
                for key, inner in value.items()
            }
        return value

    def _mark_resolution_settings_self_origin(self, key: str, value: Any) -> None:
        self._resolution_settings_self_origin_values[key] = (
            self._copy_resolution_settings_value(value)
        )

    def _clear_resolution_settings_self_origin(self, key: str) -> None:
        self._resolution_settings_self_origin_values.pop(key, None)

    def _consume_resolution_settings_self_origin(
        self,
        change: ResolutionSettingsChange,
    ) -> bool:
        expected = self._resolution_settings_self_origin_values.get(change.key)
        if expected is None:
            return False
        self._clear_resolution_settings_self_origin(change.key)
        return expected == change.value

    def _resolution_settings_snapshot_matches_state(
        self,
        resolved: ViewportResolutionSettings,
    ) -> bool:
        try:
            requested_width, requested_height = resolved.resolution
        except (TypeError, ValueError):
            requested_size = VIEWPORT_SENTINEL_DIMENSIONS
        else:
            requested_size = (int(requested_width), int(requested_height))
        mode = (
            RESOLUTION_MODE_VIEWPORT
            if requested_size == VIEWPORT_SENTINEL_DIMENSIONS
            else RESOLUTION_MODE_FIXED
        )
        fill_viewport = (
            bool(resolved.fill_viewport)
            if mode == RESOLUTION_MODE_FIXED
            else False
        )
        state = self._resolution_state
        return (
            state.mode == mode
            and state.requested_size == requested_size
            and state.scale == resolved.resolution_scale
            and state.fill_viewport is fill_viewport
            and state.uses_dpi is bool(resolved.resolution_uses_dpi)
        )

    def _shared_resolution_setting_snapshot_value(
        self,
        resolved: ViewportResolutionSettings,
        key: str,
    ) -> Any:
        if key == SETTING_CUSTOM_RESOLUTION_LIST:
            return resolved.custom_list
        if key == SETTING_RESOLUTION_PRESETS:
            return resolved.presets
        if key == SETTING_RENDER_SCALE_LIST:
            return resolved.render_scale_list
        return None

    def _sync_resolution_shared_settings_snapshot(
        self,
        resolved: ViewportResolutionSettings,
    ) -> None:
        for key in self._shared_resolution_setting_keys():
            self._resolution_shared_settings_values[key] = (
                self._copy_resolution_settings_value(
                    self._shared_resolution_setting_snapshot_value(resolved, key)
                )
            )

    def _record_resolution_shared_setting_change(
        self,
        change: ResolutionSettingsChange,
    ) -> bool:
        if change.key in self._resolution_shared_settings_values:
            if self._resolution_shared_settings_values[change.key] == change.value:
                return False
        self._resolution_shared_settings_values[change.key] = (
            self._copy_resolution_settings_value(change.value)
        )
        return True

    def _on_shared_resolution_settings_change(
        self,
        change: ResolutionSettingsChange,
    ) -> None:
        """Refresh shared catalog/options without re-owning Area-1/Area-2."""

        if self._resolution_sync_is_disposed():
            return
        if not self._record_resolution_shared_setting_change(change):
            return
        resolved = self.get_resolution_settings()
        self._last_render_resolution_apply_error = None
        self._accept_resolution_settings_snapshot(resolved)
        self._sync_resolution_shared_settings_snapshot(resolved)
        self._request_settings_menu_reshow()

    def _on_resolution_settings_change(
        self,
        change: ResolutionSettingsChange,
    ) -> None:
        """Propagate accepted external per-viewport settings without echoes."""

        if self._resolution_sync_is_disposed():
            return
        if change.key in self._shared_resolution_setting_keys():
            self._on_shared_resolution_settings_change(change)
            return
        if change.key not in self._per_viewport_resolution_setting_keys():
            return
        if self._consume_resolution_settings_self_origin(change):
            return
        resolved = self.get_resolution_settings()
        if self._resolution_settings_snapshot_matches_state(resolved):
            return
        self._last_render_resolution_apply_error = None
        self._accept_resolution_settings_snapshot(resolved)
        self._request_render_resolution_apply_refresh()
        self._request_settings_menu_reshow()

    def _request_render_resolution_apply_refresh(self) -> None:
        """Refresh the render after a row click has updated accepted state."""

        if self._resolution_sync_is_disposed():
            return

        def _render_once() -> None:
            if self._resolution_sync_is_disposed():
                return
            try:
                self._render_rate_limited()
            except Exception as exc:
                self._last_render_resolution_apply_error = exc

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _render_once()
            return

        if self._resolution_render_refresh_pending:
            return
        self._resolution_render_refresh_pending = True

        async def _render_next_frame() -> None:
            try:
                await ui.next_frame()
                if self._resolution_sync_is_disposed():
                    return
                _render_once()
            finally:
                self._resolution_render_refresh_pending = False

        loop.create_task(_render_next_frame())

    def _request_scale_fill_menu_refresh(self) -> None:
        """Reopen the Settings menu after an embedded control accepts state."""

        self._request_settings_menu_reshow()

    def _request_settings_menu_dismiss(self) -> None:
        """Close the retained Settings menu after the active UI event settles."""

        if self._resolution_sync_is_disposed():
            return
        if not self._settings_toolbar_menu_is_open():
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._dismiss_settings_toolbar_menu()
            return

        if self._settings_menu_dismiss_pending:
            return
        self._settings_menu_dismiss_pending = True

        async def _dismiss_after_control_event() -> None:
            try:
                await ui.next_frame()
                if self._resolution_sync_is_disposed():
                    return
                self._dismiss_settings_toolbar_menu()
            except Exception as exc:
                self._last_render_resolution_apply_error = exc
            finally:
                self._settings_menu_dismiss_pending = False

        loop.create_task(_dismiss_after_control_event())

    def _request_settings_menu_reshow(self) -> None:
        """Refresh the already-open Settings menu or invalidate it safely."""

        if self._resolution_sync_is_disposed():
            return
        if not self._settings_toolbar_menu_is_open():
            return
        if self._settings_menu_reshow_pending:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if self._resolution_sync_is_disposed():
                return
            if not self._pre_tools_toolbar_hooks.reshow_menu(
                VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ):
                self._dismiss_settings_toolbar_menu()
            return

        self._settings_menu_reshow_pending = True

        async def _reshow_after_control_dismissal() -> None:
            try:
                await ui.next_frame()
                await ui.next_frame()
                if self._resolution_sync_is_disposed():
                    return
                if not self._settings_toolbar_menu_is_open():
                    return
                if not self._pre_tools_toolbar_hooks.reshow_menu(
                    VIEWPORT_RESOLUTION_ATTACHMENT_ID
                ):
                    self._dismiss_settings_toolbar_menu()
            except Exception as exc:
                self._last_render_resolution_apply_error = exc
            finally:
                self._settings_menu_reshow_pending = False

        loop.create_task(_reshow_after_control_dismissal())

    def _settings_toolbar_menu_is_open(self) -> bool:
        """Return whether the Settings menu surface is retained and usable."""

        menu = self._pre_tools_toolbar_hooks._menus.get(
            VIEWPORT_RESOLUTION_ATTACHMENT_ID
        )
        if menu is None:
            return False
        if bool(getattr(menu, "destroyed", False)):
            return False
        if bool(getattr(menu, "hidden", False)):
            return False
        return True

    def _clear_settings_menu_control_callbacks(self) -> None:
        """Release callback tokens for rebuilt Settings-menu controls."""

        for token in tuple(self._settings_menu_control_callback_tokens):
            unregister_menu_control_callback(token)
        self._settings_menu_control_callback_tokens.clear()

    def _register_settings_menu_control_callback(
        self,
        callback: Callable[..., Any] | None,
    ) -> str:
        token = register_menu_control_callback(callback)
        if token:
            self._settings_menu_control_callback_tokens.add(token)
        return token

    def set_custom_resolution_save_handoff(
        self,
        callback: Callable[[], Any] | None,
    ) -> None:
        """Install Area-5 save behavior for the inline Custom Resolution icon."""

        self._custom_resolution_save_handoff = (
            callback if callable(callback) else self._open_custom_resolution_save_dialog
        )

    def set_saved_custom_delete_handoff(
        self,
        callback: Callable[[Any], Any] | None,
    ) -> None:
        """Install Area-5 delete behavior for saved custom resolution rows."""

        self._saved_custom_delete_handoff = (
            callback if callable(callback) else self._delete_saved_custom_resolution_row
        )

    def _handoff_custom_resolution_save(self) -> bool:
        """Invoke the Area-5 save handoff without faking saved state."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        callback = self._custom_resolution_save_handoff
        if not callable(callback):
            return False
        try:
            accepted = bool(callback())
        except Exception as exc:
            self._last_render_resolution_apply_error = exc
            return False
        if accepted:
            self._last_render_resolution_apply_error = None
        return accepted

    def _handoff_saved_custom_delete(self, row: Any) -> bool:
        """Invoke the Area-5 delete handoff without removing rows in Area 4."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        callback = self._saved_custom_delete_handoff
        if not callable(callback):
            self._request_settings_menu_reshow()
            return False
        try:
            accepted = bool(callback(row))
        except Exception as exc:
            self._last_render_resolution_apply_error = exc
            self._request_settings_menu_reshow()
            return False
        if accepted:
            self._last_render_resolution_apply_error = None
        else:
            self._request_settings_menu_reshow()
        return accepted

    def _delete_saved_custom_resolution_row(self, row: Any) -> bool:
        """Remove exactly one saved custom row through the shared Area-1 list."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        if getattr(row, "kind", None) != RESOLUTION_CATALOG_KIND_SAVED_CUSTOM:
            return False
        name = getattr(row, "label", None)
        dimensions = getattr(row, "dimensions", None)
        if name is None or dimensions is None:
            return False
        try:
            width, height = int(dimensions[0]), int(dimensions[1])
        except (TypeError, ValueError, IndexError):
            return False
        target_name = str(name)

        remaining: list[dict[str, Any]] = []
        removed = False
        for entry in self.get_resolution_settings().custom_list:
            try:
                entry_name = str(entry["name"])
                entry_width = int(entry["width"])
                entry_height = int(entry["height"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not removed
                and entry_name == target_name
                and entry_width == width
                and entry_height == height
            ):
                removed = True
                continue
            remaining.append(
                {"name": entry_name, "width": entry_width, "height": entry_height}
            )
        if not removed:
            return False

        try:
            write_shared_custom_resolution_list(self._resolve_settings(), remaining)
        except Exception as exc:
            self._last_render_resolution_apply_error = exc
            return False
        self._accept_resolution_settings_snapshot(self.get_resolution_settings())
        self._last_render_resolution_apply_error = None
        self._request_settings_menu_reshow()
        return True

    def _apply_render_resolution_row_selection(self, row: Any) -> bool:
        """Accept a Render Resolution row click and refresh state-driven visuals."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._resolution_controls_available():
            return False
        if self._render_resolution_row_disabled_reason(row):
            return False
        requested_size = self._requested_size_for_render_resolution_row(row)
        if requested_size is None:
            return False

        current_selection = self._current_render_resolution_catalog_selection()
        already_selected = (
            current_selection is not None
            and getattr(current_selection.row, "key", None) == getattr(row, "key", None)
            and self._resolution_state.requested_size == requested_size
        )
        settings = self._resolve_settings()
        key = viewport_resolution_key(self._viewport_id)
        value = list(requested_size)
        self._mark_resolution_settings_self_origin(key, value)
        try:
            write_viewport_instance_resolution(
                settings,
                self._viewport_id,
                value,
            )
        except Exception as exc:
            self._clear_resolution_settings_self_origin(key)
            self._last_render_resolution_apply_error = exc
            return False
        self._clear_resolution_settings_self_origin(key)
        self._last_render_resolution_apply_error = None
        if already_selected:
            self._request_settings_menu_dismiss()
            return True

        self._accept_resolution_settings_snapshot(self.get_resolution_settings())
        self._request_render_resolution_apply_refresh()
        self._request_settings_menu_dismiss()
        return True

    def _apply_render_scale_menu_selection(
        self,
        scale_values: tuple[float, ...],
        selected_index: int,
    ) -> bool:
        """Accept a Render Scale combo selection and refresh from state."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        try:
            scale = float(scale_values[int(selected_index)])
        except (IndexError, TypeError, ValueError):
            return False
        if scale <= 0.0:
            return False
        settings = self._resolve_settings()
        key = viewport_resolution_scale_key(self._viewport_id)
        self._mark_resolution_settings_self_origin(key, scale)
        try:
            write_viewport_instance_resolution_scale(
                settings,
                self._viewport_id,
                scale,
            )
        except Exception as exc:
            self._clear_resolution_settings_self_origin(key)
            self._last_render_resolution_apply_error = exc
            return False
        self._clear_resolution_settings_self_origin(key)
        self._last_render_resolution_apply_error = None
        self._accept_resolution_settings_snapshot(self.get_resolution_settings())
        self._request_render_resolution_apply_refresh()
        self._request_settings_menu_dismiss()
        return True

    def _apply_fill_viewport_menu_toggle(self, checked: bool) -> bool:
        """Accept an enabled Fill Viewport checkbox toggle."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._fixed_resolution_controls_available():
            return False
        fill_enabled, _ = self._fill_viewport_checkbox_snapshot()
        if not fill_enabled:
            return False
        settings = self._resolve_settings()
        key = viewport_fill_viewport_key(self._viewport_id)
        value = bool(checked)
        self._mark_resolution_settings_self_origin(key, value)
        try:
            write_viewport_instance_fill_viewport(
                settings,
                self._viewport_id,
                value,
            )
        except Exception as exc:
            self._clear_resolution_settings_self_origin(key)
            self._last_render_resolution_apply_error = exc
            return False
        self._clear_resolution_settings_self_origin(key)
        self._last_render_resolution_apply_error = None
        self._accept_resolution_settings_snapshot(self.get_resolution_settings())
        self._request_render_resolution_apply_refresh()
        self._request_settings_menu_dismiss()
        return True

    def _build_render_resolution_submenu(self, ui_module: Any) -> None:
        """Build render-resolution radio rows from Area-2 data."""

        selection = self._current_render_resolution_catalog_selection()
        selected_key = selection.key if selection is not None else None
        for row_index, row in enumerate(self._iter_render_resolution_rows()):
            disabled_reason = self._render_resolution_row_disabled_reason(row)
            row_enabled = not bool(disabled_reason)
            has_delete_affordance = (
                getattr(row, "kind", "") == RESOLUTION_CATALOG_KIND_SAVED_CUSTOM
            )
            row_target = self._resolution_inspector_target(
                "viewport_render_resolution_row",
                getattr(row, "label", ""),
            )
            delete_target = f"{row_target}_delete"
            row_selection_fn = (
                lambda selected_row=row: self._apply_render_resolution_row_selection(
                    selected_row
                )
            )
            row_callback_token = ""
            delete_handoff_fn: Callable[[], bool] | None = None
            delete_callback_token = ""
            if has_delete_affordance:
                row_callback_token = self._register_settings_menu_control_callback(
                    row_selection_fn
                )
                delete_handoff_fn = (
                    lambda selected_row=row: self._handoff_saved_custom_delete(
                        selected_row
                    )
                )
                delete_callback_token = self._register_settings_menu_control_callback(
                    delete_handoff_fn
                )
            detail_text = self._render_resolution_menu_detail_text(row)
            visible_detail_text = (
                f"{detail_text}  {disabled_reason}"
                if disabled_reason
                else detail_text
            )
            row_fallbacks = ["badge text"]
            if has_delete_affordance:
                row_fallbacks.append("delete label x")
            row_fallback_kwargs = self._resolution_icon_fallback_kwargs(
                *row_fallbacks
            )
            if row_fallback_kwargs:
                row_fallback_kwargs.update(
                    {
                        "badge_fallback_label": detail_text,
                        "badge_fallback_tooltip": detail_text,
                    }
                )
                if has_delete_affordance:
                    row_fallback_kwargs.update(
                        {
                            "delete_fallback_label": "x",
                            "delete_fallback_tooltip": (
                                disabled_reason or f"Delete {row.label}"
                            ),
                        }
                    )
            hotkey_text = visible_detail_text
            if has_delete_affordance and row_enabled:
                hotkey_text = _saved_custom_delete_hotkey_payload(
                    detail_text=visible_detail_text,
                    callback_token=delete_callback_token,
                )
            row_tooltip = (
                disabled_reason
                or f"{row.label} {detail_text}".strip()
                or str(row.label)
            )
            ui_module.MenuItem(
                row.label,
                enabled=row_enabled,
                checkable=not has_delete_affordance,
                checked=(row.key == selected_key),
                hotkey_text=hotkey_text,
                tooltip=row_tooltip,
                disabled_reason=disabled_reason,
                hide_on_click=False,
                triggered_fn=(
                    None if has_delete_affordance or not row_enabled else row_selection_fn
                ),
                row_callback_token=row_callback_token,
                row_handoff_fn=(
                    row_selection_fn
                    if has_delete_affordance and row_enabled
                    else None
                ),
                delete_affordance=has_delete_affordance,
                delete_tooltip=disabled_reason or f"Delete {row.label}",
                delete_callback_token=delete_callback_token,
                delete_handoff_fn=(delete_handoff_fn if row_enabled else None),
                delete_inspector_target=delete_target,
                keyboard_delete_activation_keys=("Tab", "Enter", "Space"),
                **self._resolution_keyboard_metadata(
                    target=row_target,
                    label=str(row.label),
                    focus_order=10 + row_index,
                    reason=disabled_reason,
                ),
                **row_fallback_kwargs,
            )

    def _build_viewport_settings_failure_fallback(
        self,
        ui_module: Any,
        reason: Any,
    ) -> None:
        """Build the localized A7 fallback when resolution menu data is unavailable."""

        fallback_reason = self._resolution_menu_fallback_reason(reason)
        fallback_kwargs: dict[str, Any] = {
            "enabled": False,
            "tooltip": fallback_reason,
            "disabled_reason": fallback_reason,
            "hotkey_text": fallback_reason,
            "hide_on_click": False,
            "triggered_fn": None,
        }
        with ui_module.Menu(
            _VIEWPORT_MENU_RENDER_RESOLUTION_LABEL,
            identifier="viewport_render_resolution_menu",
            hotkey_text="Unavailable",
            tooltip=fallback_reason,
            **self._resolution_keyboard_metadata(
                target="viewport_render_resolution_menu",
                label=_VIEWPORT_MENU_RENDER_RESOLUTION_LABEL,
                focus_order=2,
                reason=fallback_reason,
            ),
        ):
            ui_module.MenuItem(
                "Resolution unavailable",
                **fallback_kwargs,
                **self._resolution_keyboard_metadata(
                    target="viewport_render_resolution_row_unavailable",
                    label="Resolution unavailable",
                    focus_order=10,
                    reason=fallback_reason,
                ),
            )
        ui_module.MenuItem(
            _VIEWPORT_MENU_CUSTOM_RESOLUTION_LABEL,
            custom_resolution_editor=True,
            custom_resolution_disabled_reason=fallback_reason,
            custom_resolution_save_handoff=False,
            custom_resolution_applies_on_end_edit=False,
            custom_resolution_controls=(),
            **fallback_kwargs,
            **self._resolution_keyboard_metadata(
                target="viewport_custom_resolution_editor",
                label=_VIEWPORT_MENU_CUSTOM_RESOLUTION_LABEL,
                focus_order=30,
                reason=fallback_reason,
            ),
        )
        ui_module.MenuItem(
            _VIEWPORT_MENU_RENDER_SCALE_LABEL,
            render_scale_combo=True,
            render_scale_options=(),
            render_scale_values=(),
            render_scale_current_index=0,
            render_scale_current_label="Unavailable",
            render_scale_applies_on_change=False,
            **fallback_kwargs,
            **self._resolution_keyboard_metadata(
                target="viewport_render_scale_control",
                label=_VIEWPORT_MENU_RENDER_SCALE_LABEL,
                focus_order=40,
                reason=fallback_reason,
            ),
        )
        ui_module.MenuItem(
            _VIEWPORT_MENU_FILL_VIEWPORT_LABEL,
            fill_viewport_checkbox=True,
            fill_viewport_enabled=False,
            fill_viewport_checked=False,
            fill_viewport_disabled_reason=fallback_reason,
            fill_viewport_applies_on_change=False,
            **fallback_kwargs,
            **self._resolution_keyboard_metadata(
                target="viewport_fill_viewport_control",
                label=_VIEWPORT_MENU_FILL_VIEWPORT_LABEL,
                focus_order=50,
                reason=fallback_reason,
            ),
        )

    def _build_viewport_settings_submenu(self, ui_module: Any) -> None:
        """Build the SRD-order Viewport submenu row shell."""

        self._clear_settings_menu_control_callbacks()
        failure_reason = self._resolution_menu_failure_reason()
        if failure_reason:
            self._build_viewport_settings_failure_fallback(ui_module, failure_reason)
            return
        try:
            self._build_viewport_settings_submenu_content(ui_module)
        except Exception as exc:
            self._last_render_resolution_apply_error = exc
            self._clear_settings_menu_control_callbacks()
            self._build_viewport_settings_failure_fallback(
                ui_module,
                _RESOLUTION_MENU_FAILURE_REASON,
            )

    def _build_viewport_settings_submenu_content(self, ui_module: Any) -> None:
        """Build the normal SRD-order Viewport submenu row shell."""

        fixed_controls_disabled_reason = (
            self._fixed_resolution_controls_disabled_reason()
        )
        controls_enabled = not bool(fixed_controls_disabled_reason)
        current_label = self._current_render_resolution_menu_label()
        custom_list_warning = self._resolution_custom_list_warning_message()
        max_clamp_warning = self._resolution_max_clamp_warning_message()
        tooltip_messages = tuple(
            message
            for message in (custom_list_warning, max_clamp_warning)
            if message
        )
        render_resolution_menu_kwargs: dict[str, Any] = {
            "identifier": "viewport_render_resolution_menu",
            "hotkey_text": current_label,
            **self._resolution_keyboard_metadata(
                target="viewport_render_resolution_menu",
                label=_VIEWPORT_MENU_RENDER_RESOLUTION_LABEL,
                focus_order=2,
            ),
        }
        if tooltip_messages:
            render_resolution_menu_kwargs["tooltip"] = " ".join(tooltip_messages)
        render_resolution_menu_fallback_kwargs = self._resolution_icon_fallback_kwargs(
            "warning text" if tooltip_messages else "",
        )
        if render_resolution_menu_fallback_kwargs and tooltip_messages:
            render_resolution_menu_fallback_kwargs.update(
                {
                    "warning_fallback_label": "Warning",
                    "warning_fallback_tooltip": " ".join(tooltip_messages),
                }
            )
        with ui_module.Menu(
            _VIEWPORT_MENU_RENDER_RESOLUTION_LABEL,
            **render_resolution_menu_kwargs,
            **render_resolution_menu_fallback_kwargs,
        ):
            self._build_render_resolution_submenu(ui_module)
        custom_save_handoff_fn = self._handoff_custom_resolution_save
        custom_save_callback_token = self._register_settings_menu_control_callback(
            custom_save_handoff_fn
        )
        custom_save_enabled_fn = self._custom_resolution_save_enabled_for_dimensions
        custom_save_enabled_callback_token = (
            self._register_settings_menu_control_callback(custom_save_enabled_fn)
        )
        custom_apply_fn = self._apply_custom_resolution_field_values
        custom_apply_callback_token = self._register_settings_menu_control_callback(
            custom_apply_fn
        )
        custom_default_width, custom_default_height = (
            self._custom_resolution_editor_default_size()
        )
        (
            custom_min_width,
            custom_min_height,
            custom_max_width,
            custom_max_height,
        ) = self._custom_resolution_editor_bounds()
        custom_icon_fallback_kwargs = self._resolution_icon_fallback_kwargs(
            "link toggle label L",
            "ratio combo text labels",
            "save label S",
        )
        if custom_icon_fallback_kwargs:
            custom_icon_fallback_kwargs.update(
                {
                    "custom_resolution_icon_fallbacks": (
                        "link toggle label L",
                        "ratio combo text labels",
                        "save label S",
                    ),
                    "link_toggle_fallback_label": "L",
                    "link_toggle_fallback_tooltip": (
                        fixed_controls_disabled_reason or "Link width and height"
                    ),
                    "save_icon_fallback_label": "S",
                    "save_icon_fallback_tooltip": (
                        fixed_controls_disabled_reason or "Save custom resolution"
                    ),
                }
            )
        ui_module.MenuItem(
            _VIEWPORT_MENU_CUSTOM_RESOLUTION_LABEL,
            hide_on_click=False,
            enabled=controls_enabled,
            tooltip=fixed_controls_disabled_reason,
            disabled_reason=fixed_controls_disabled_reason,
            hotkey_text=_custom_resolution_editor_hotkey_payload(
                callback_token=custom_save_callback_token,
                apply_callback_token=custom_apply_callback_token,
                save_enabled_callback_token=custom_save_enabled_callback_token,
                default_size=(custom_default_width, custom_default_height),
                bounds=(
                    custom_min_width,
                    custom_min_height,
                    custom_max_width,
                    custom_max_height,
                ),
            ),
            custom_resolution_editor=True,
            custom_resolution_default_width=custom_default_width,
            custom_resolution_default_height=custom_default_height,
            custom_resolution_min_width=custom_min_width,
            custom_resolution_min_height=custom_min_height,
            custom_resolution_max_width=custom_max_width,
            custom_resolution_max_height=custom_max_height,
            custom_resolution_ratio_options=(
                "16:9",
                "4:3",
                "1:1",
                "21:9",
                "32:9",
            ),
            custom_resolution_controls=(
                "width_field",
                "height_field",
                "link_toggle",
                "ratio_combo",
                "save_icon",
                "width_label",
                "height_label",
            ),
            save_icon_opens_modal=True,
            custom_resolution_save_handoff=True,
            custom_resolution_save_handoff_fn=custom_save_handoff_fn,
            custom_resolution_save_callback_token=custom_save_callback_token,
            custom_resolution_save_enabled_fn=custom_save_enabled_fn,
            custom_resolution_save_enabled_callback_token=(
                custom_save_enabled_callback_token
            ),
            custom_resolution_applies_on_end_edit=True,
            custom_resolution_apply_fn=custom_apply_fn,
            custom_resolution_apply_callback_token=custom_apply_callback_token,
            custom_resolution_disabled_reason=fixed_controls_disabled_reason,
            custom_resolution_title_identifier="viewport_custom_resolution_title",
            custom_resolution_width_identifier="viewport_custom_resolution_width_field",
            custom_resolution_width_label_identifier=(
                "viewport_custom_resolution_width_label"
            ),
            custom_resolution_height_identifier=(
                "viewport_custom_resolution_height_field"
            ),
            custom_resolution_height_label_identifier=(
                "viewport_custom_resolution_height_label"
            ),
            custom_resolution_link_identifier="viewport_custom_resolution_link_toggle",
            custom_resolution_ratio_identifier="viewport_custom_resolution_ratio_combo",
            custom_resolution_save_identifier="viewport_custom_resolution_save_button",
            keyboard_control_order=(
                "viewport_custom_resolution_width_field",
                "viewport_custom_resolution_height_field",
                "viewport_custom_resolution_link_toggle",
                "viewport_custom_resolution_ratio_combo",
                "viewport_custom_resolution_save_button",
            ),
            **self._resolution_keyboard_metadata(
                target="viewport_custom_resolution_editor",
                label=_VIEWPORT_MENU_CUSTOM_RESOLUTION_LABEL,
                focus_order=30,
                reason=fixed_controls_disabled_reason,
            ),
            **custom_icon_fallback_kwargs,
        )
        (
            scale_option_values,
            scale_option_labels,
            scale_current_index,
            scale_current_label,
        ) = self._render_scale_combo_snapshot()

        def _on_render_scale_changed(
            selected_index: int,
            values: tuple[float, ...] = scale_option_values,
        ) -> bool:
            return self._apply_render_scale_menu_selection(values, selected_index)

        render_scale_callback_token = self._register_settings_menu_control_callback(
            _on_render_scale_changed
        )
        ui_module.MenuItem(
            _VIEWPORT_MENU_RENDER_SCALE_LABEL,
            hide_on_click=False,
            enabled=controls_enabled,
            tooltip=fixed_controls_disabled_reason or max_clamp_warning or "Render Scale",
            disabled_reason=fixed_controls_disabled_reason,
            hotkey_text=_render_scale_combo_hotkey_payload(
                option_labels=scale_option_labels,
                current_index=scale_current_index,
                callback_token=render_scale_callback_token,
            ),
            render_scale_combo=True,
            render_scale_values=scale_option_values,
            render_scale_options=scale_option_labels,
            render_scale_current_index=scale_current_index,
            render_scale_current_label=scale_current_label,
            render_scale_applies_on_change=controls_enabled,
            render_scale_changed_fn=_on_render_scale_changed,
            render_scale_identifier="viewport_render_scale_combo",
            render_scale_label_identifier="viewport_render_scale_label",
            **self._resolution_keyboard_metadata(
                target="viewport_render_scale_control",
                label=_VIEWPORT_MENU_RENDER_SCALE_LABEL,
                focus_order=40,
                reason=fixed_controls_disabled_reason,
            ),
            **self._resolution_icon_fallback_kwargs(
                "warning text" if max_clamp_warning else "",
            ),
        )
        fill_enabled, fill_checked = self._fill_viewport_checkbox_snapshot()
        fill_changed_fn = self._apply_fill_viewport_menu_toggle
        fill_callback_token = self._register_settings_menu_control_callback(
            fill_changed_fn
        )
        fill_icon_fallback_kwargs = self._resolution_icon_fallback_kwargs(
            "checkbox label"
        )
        if fill_icon_fallback_kwargs:
            fill_icon_fallback_kwargs.update(
                {
                    "checkbox_fallback_label": "checkbox",
                    "checkbox_fallback_tooltip": (
                        fixed_controls_disabled_reason
                        or _VIEWPORT_MENU_FILL_VIEWPORT_DISABLED_REASON
                    ),
                }
            )
        ui_module.MenuItem(
            _VIEWPORT_MENU_FILL_VIEWPORT_LABEL,
            hide_on_click=False,
            enabled=fill_enabled,
            tooltip=(
                fixed_controls_disabled_reason
                or ("" if fill_enabled else _VIEWPORT_MENU_FILL_VIEWPORT_DISABLED_REASON)
            ),
            disabled_reason=fixed_controls_disabled_reason,
            hotkey_text=_fill_viewport_checkbox_hotkey_payload(
                enabled=fill_enabled,
                checked=fill_checked,
                callback_token=fill_callback_token,
            ),
            fill_viewport_checkbox=True,
            fill_viewport_enabled=fill_enabled,
            fill_viewport_checked=fill_checked,
            fill_viewport_disabled_reason=(
                fixed_controls_disabled_reason
                or _VIEWPORT_MENU_FILL_VIEWPORT_DISABLED_REASON
            ),
            fill_viewport_applies_on_change=fill_enabled,
            fill_viewport_changed_fn=fill_changed_fn,
            fill_viewport_identifier="viewport_fill_viewport_checkbox",
            fill_viewport_label_identifier="viewport_fill_viewport_label",
            **self._resolution_keyboard_metadata(
                target="viewport_fill_viewport_control",
                label=_VIEWPORT_MENU_FILL_VIEWPORT_LABEL,
                focus_order=50,
                reason=(
                    fixed_controls_disabled_reason
                    or ("" if fill_enabled else _VIEWPORT_MENU_FILL_VIEWPORT_DISABLED_REASON)
                ),
            ),
            **fill_icon_fallback_kwargs,
            triggered_fn=(
                (
                    lambda accepted_checked=not fill_checked: fill_changed_fn(
                        accepted_checked
                    )
                )
                if fill_enabled
                else None
            ),
        )

    def _dismiss_settings_toolbar_menu(self) -> bool:
        """Close the Settings menu if it is currently retained."""

        if VIEWPORT_RESOLUTION_ATTACHMENT_ID not in self._pre_tools_toolbar_hooks._menus:
            return False
        self._pre_tools_toolbar_hooks._destroy_menu(VIEWPORT_RESOLUTION_ATTACHMENT_ID)
        return True

    def _register_foundation_qa_pre_tools_placeholder(self) -> None:
        self.attach_resolution_toolbar_host(
            lambda context: ViewportToolbarAction(
                id=context.attachment_id,
                label="QA",
                order=0,
                tooltip="Foundation QA pre-tools host placeholder",
                widget_name=_FOUNDATION_QA_PRE_TOOLS_PLACEHOLDER_WIDGET,
                callback=lambda owner: owner._open_resolution_settings_notification_qa_window(),
            ),
        )

    def _build_resolution_settings_schema_qa_window(self) -> None:
        if self._resolution_settings_schema_qa_window is not None:
            return

        if not _AREA1_QA_ACTIVE_VIEWPORTS:
            _AREA1_QA_SHARED_SETTINGS_DATA.clear()
        _AREA1_QA_ACTIVE_VIEWPORTS.add(self)
        if self._resolution_settings_schema_qa_uses_persistent_store():
            self._resolution_settings_schema_qa_profile = (
                _AREA1_QA_PROFILE_PERSISTENT
            )

        flags = getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
        two_viewport_qa = _env_flag_enabled(AREA1_TWO_VIEWPORT_QA_ENV)
        window_title = "A1 Settings Schema QA"
        if two_viewport_qa:
            window_title = f"A1 Settings Schema QA {self._viewport_id}"
        self._resolution_settings_schema_qa_labels = []
        window = ui.Window(
            window_title,
            width=610 if two_viewport_qa else 620,
            height=420 if two_viewport_qa else 640,
            flags=flags,
        )
        self._resolution_settings_schema_qa_window = window
        try:
            if two_viewport_qa:
                window.position_x = 10 if self._viewport_id == DEFAULT_VIEWPORT_ID else 660
                window.position_y = 288
            else:
                window.position_x = 640
                window.position_y = 72
        except Exception:
            pass

        label_height = 14 if two_viewport_qa else 18
        with window.frame:
            with ui.VStack(spacing=4):
                ui.Spacer(height=4)
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "No Saved Settings",
                        width=150,
                        clicked_fn=lambda: self._set_resolution_settings_schema_qa_profile(
                            _AREA1_QA_PROFILE_NO_SAVED
                        ),
                    )
                    ui.Button(
                        "Missing Keys",
                        width=128,
                        clicked_fn=lambda: self._set_resolution_settings_schema_qa_profile(
                            _AREA1_QA_PROFILE_MISSING_KEYS
                        ),
                    )
                    ui.Button(
                        "DPI Unavailable",
                        width=144,
                        clicked_fn=lambda: self._set_resolution_settings_schema_qa_profile(
                            _AREA1_QA_PROFILE_DPI_UNAVAILABLE
                        ),
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Shared 720p",
                        width=120,
                        clicked_fn=self._apply_resolution_settings_schema_qa_shared_720p_profile,
                    )
                    ui.Button(
                        "Scale 100%",
                        width=116,
                        clicked_fn=self._apply_resolution_settings_schema_qa_scale_100_override,
                    )
                    ui.Button(
                        "Remove Profile",
                        width=132,
                        clicked_fn=self._clear_resolution_settings_schema_qa_profile,
                    )
                    ui.Button(
                        "Scale 50%",
                        width=108,
                        clicked_fn=self._apply_resolution_settings_schema_qa_scale_50_override,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Set 1080p 50%",
                        width=132,
                        clicked_fn=self._apply_resolution_settings_schema_qa_1080p_50,
                    )
                    ui.Button(
                        "Fill On",
                        width=92,
                        clicked_fn=self._apply_resolution_settings_schema_qa_fill_on,
                    )
                    ui.Button(
                        "Add Shared Review",
                        width=156,
                        clicked_fn=self._apply_resolution_settings_schema_qa_shared_custom,
                    )
                    ui.Button(
                        "Set Viewport",
                        width=122,
                        clicked_fn=self._apply_resolution_settings_schema_qa_viewport_mode,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Scale Options 75",
                        width=150,
                        clicked_fn=self._apply_resolution_settings_schema_qa_scale_options_75,
                    )
                    ui.Button(
                        "Scale Options 25",
                        width=150,
                        clicked_fn=self._apply_resolution_settings_schema_qa_scale_options_25,
                    )
                    ui.Spacer()
                if self._resolution_settings_schema_qa_uses_persistent_store():
                    with ui.HStack(height=28, spacing=6):
                        ui.Spacer(width=8)
                        ui.Button(
                            "Persistent Profile",
                            width=162,
                            clicked_fn=(
                                self._apply_resolution_settings_schema_qa_persistent_profile
                            ),
                        )
                        ui.Button(
                            "Invalid Persisted",
                            width=156,
                            clicked_fn=(
                                self._apply_resolution_settings_schema_qa_invalid_persisted_profile
                            ),
                        )
                        ui.Spacer()
                else:
                    with ui.HStack(height=28, spacing=6):
                        ui.Spacer(width=8)
                        ui.Button(
                            "Valid Custom",
                            width=122,
                            clicked_fn=self._apply_resolution_settings_schema_qa_valid_custom_list,
                        )
                        ui.Button(
                            "Malformed Custom",
                            width=158,
                            clicked_fn=self._apply_resolution_settings_schema_qa_malformed_custom_list,
                        )
                        ui.Button(
                            "All Invalid",
                            width=118,
                            clicked_fn=self._apply_resolution_settings_schema_qa_all_custom_invalid,
                        )
                        ui.Spacer()
                if not two_viewport_qa:
                    with ui.HStack(height=28, spacing=6):
                        ui.Spacer(width=8)
                        ui.Label("Name", width=42)
                        self._resolution_settings_schema_qa_name_field = ui.StringField(
                            width=170,
                            height=22,
                        )
                        ui.Label("W", width=16)
                        self._resolution_settings_schema_qa_width_field = ui.StringField(
                            width=74,
                            height=22,
                        )
                        ui.Label("H", width=16)
                        self._resolution_settings_schema_qa_height_field = ui.StringField(
                            width=74,
                            height=22,
                        )
                        ui.Button(
                            "Add Custom",
                            width=112,
                            clicked_fn=self._apply_resolution_settings_schema_qa_custom_fields,
                        )
                        ui.Spacer()
                ui.Separator(height=2)
                with ui.HStack():
                    ui.Spacer(width=10)
                    with ui.VStack(spacing=2):
                        for _ in range(19):
                            label = ui.Label("", height=label_height, word_wrap=True)
                            self._resolution_settings_schema_qa_labels.append(label)
                    ui.Spacer(width=10)
                ui.Spacer(height=8)
        self._refresh_resolution_settings_schema_qa_window()

    def _resolution_settings_schema_qa_uses_persistent_store(self) -> bool:
        return _env_flag_enabled(AREA1_PERSISTENCE_QA_ENV)

    def _resolution_settings_schema_qa_store(self) -> Any:
        if self._resolution_settings_schema_qa_uses_persistent_store():
            settings = self._resolve_settings()
            if settings is not None:
                return settings
        return _ResolutionSettingsSchemaQAStore(
            self._resolution_settings_schema_qa_data
        )

    def _set_resolution_settings_schema_qa_profile(self, profile: str) -> None:
        if (
            not self._resolution_settings_schema_qa_uses_persistent_store()
            and profile in {
                _AREA1_QA_PROFILE_NO_SAVED,
                _AREA1_QA_PROFILE_MISSING_KEYS,
                _AREA1_QA_PROFILE_DPI_UNAVAILABLE,
            }
        ):
            self._resolution_settings_schema_qa_data.clear()
        self._resolution_settings_schema_qa_profile = profile
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_shared_720p_profile(self) -> None:
        self._resolution_settings_schema_qa_data.clear()
        self._resolution_settings_schema_qa_data.update(
            {
                SETTING_DEFAULT_RESOLUTION: [1280, 720],
                SETTING_DEFAULT_RESOLUTION_SCALE: 0.5,
                SETTING_DEFAULT_FILL_VIEWPORT: True,
            }
        )
        self._resolution_settings_schema_qa_profile = (
            _AREA1_QA_PROFILE_SHARED_DEFAULTS_720P
        )
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_scale_100_override(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        write_viewport_instance_resolution_scale(
            qa_store,
            self._viewport_id,
            1.0,
        )
        self._resolution_settings_schema_qa_profile = (
            _AREA1_QA_PROFILE_INSTANCE_SCALE_100
        )
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_scale_50_override(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        write_viewport_instance_resolution_scale(
            qa_store,
            self._viewport_id,
            0.5,
        )
        self._resolution_settings_schema_qa_profile = (
            _AREA1_QA_PROFILE_INSTANCE_SCALE_50
        )
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_1080p_50(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        write_viewport_instance_resolution(qa_store, self._viewport_id, [1920, 1080])
        write_viewport_instance_resolution_scale(qa_store, self._viewport_id, 0.5)
        self._resolution_settings_schema_qa_profile = (
            _AREA1_QA_PROFILE_INSTANCE_1080P_50
        )
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_fill_on(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        write_viewport_instance_fill_viewport(qa_store, self._viewport_id, True)
        self._resolution_settings_schema_qa_profile = (
            _AREA1_QA_PROFILE_INSTANCE_FILL_TRUE
        )
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_shared_custom(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        write_shared_custom_resolution_list(
            qa_store,
            [_AREA1_QA_SHARED_CUSTOM_ITEM],
        )
        self._resolution_settings_schema_qa_profile = _AREA1_QA_PROFILE_SHARED_CUSTOM
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_viewport_mode(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        write_viewport_instance_resolution(qa_store, self._viewport_id, [0, 0])
        targets: list[Any] = []
        owner_ref = _VIEWPORT_ID_ACTIVE.get(self._viewport_id)
        if owner_ref is not None:
            owner = owner_ref()
            if owner is not None:
                targets.append(owner)
        for viewport in tuple(_AREA1_QA_ACTIVE_VIEWPORTS):
            if not any(viewport is existing for existing in targets):
                targets.append(viewport)
        for viewport in targets:
            if getattr(viewport, "viewport_id", None) != self._viewport_id:
                continue
            product_store = viewport._resolve_settings()
            if product_store is None:
                continue
            write_viewport_instance_resolution(
                product_store,
                viewport.viewport_id,
                [0, 0],
            )
            viewport._last_render_resolution_apply_error = None
            viewport._accept_resolution_settings_snapshot(
                viewport.get_resolution_settings()
            )
            viewport._request_render_resolution_apply_refresh()
            viewport._request_settings_menu_reshow()
        self._resolution_settings_schema_qa_profile = _AREA6_QA_PROFILE_VIEWPORT_MODE
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_scale_options_profile(
        self,
        profile: str,
        options: list[float],
    ) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        setter = getattr(qa_store, "set", None)
        if not callable(setter):
            return
        setter(SETTING_RENDER_SCALE_LIST, list(options))
        self._resolution_settings_schema_qa_profile = profile
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_scale_options_75(self) -> None:
        self._apply_resolution_settings_schema_qa_scale_options_profile(
            _AREA6_QA_PROFILE_SCALE_OPTIONS_75,
            _AREA6_QA_RENDER_SCALE_OPTIONS_75,
        )

    def _apply_resolution_settings_schema_qa_scale_options_25(self) -> None:
        self._apply_resolution_settings_schema_qa_scale_options_profile(
            _AREA6_QA_PROFILE_SCALE_OPTIONS_25,
            _AREA6_QA_RENDER_SCALE_OPTIONS_25,
        )

    def _copy_resolution_settings_schema_qa_custom_list(
        self,
        custom_list: list[Any],
    ) -> list[Any]:
        copied: list[Any] = []
        for entry in custom_list:
            if isinstance(entry, dict):
                copied.append(dict(entry))
            elif isinstance(entry, list):
                copied.append(list(entry))
            else:
                copied.append(entry)
        return copied

    def _apply_resolution_settings_schema_qa_custom_profile(
        self,
        profile: str,
        custom_list: list[Any],
    ) -> None:
        self._resolution_settings_schema_qa_data.clear()
        self._resolution_settings_schema_qa_data[SETTING_CUSTOM_RESOLUTION_LIST] = (
            self._copy_resolution_settings_schema_qa_custom_list(custom_list)
        )
        self._resolution_settings_schema_qa_profile = profile
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_valid_custom_list(self) -> None:
        self._apply_resolution_settings_schema_qa_custom_profile(
            _AREA1_QA_PROFILE_VALID_CUSTOM_LIST,
            _AREA1_QA_VALID_CUSTOM_LIST,
        )

    def _apply_resolution_settings_schema_qa_malformed_custom_list(self) -> None:
        self._apply_resolution_settings_schema_qa_custom_profile(
            _AREA1_QA_PROFILE_MALFORMED_CUSTOM_LIST,
            _AREA1_QA_MALFORMED_CUSTOM_LIST,
        )

    def _apply_resolution_settings_schema_qa_all_custom_invalid(self) -> None:
        self._apply_resolution_settings_schema_qa_custom_profile(
            _AREA1_QA_PROFILE_ALL_CUSTOM_INVALID,
            _AREA1_QA_ALL_INVALID_CUSTOM_LIST,
        )

    def _apply_resolution_settings_schema_qa_persistent_profile(self) -> None:
        self._resolution_settings_schema_qa_profile = _AREA1_QA_PROFILE_PERSISTENT
        _refresh_area1_settings_schema_qa_windows()

    def _apply_resolution_settings_schema_qa_invalid_persisted_profile(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        setter = getattr(qa_store, "set", None)
        if not callable(setter):
            return
        setter(
            SETTING_CUSTOM_RESOLUTION_LIST,
            self._copy_resolution_settings_schema_qa_custom_list(
                _AREA1_QA_PERSISTENT_INVALID_CUSTOM_LIST
            ),
        )
        setter(viewport_resolution_key(self._viewport_id), ["invalid"])
        setter(viewport_resolution_scale_key(self._viewport_id), "invalid")
        setter(viewport_fill_viewport_key(self._viewport_id), "invalid")
        self._resolution_settings_schema_qa_profile = (
            _AREA1_QA_PROFILE_INVALID_PERSISTED
        )
        _refresh_area1_settings_schema_qa_windows()

    def _resolution_settings_schema_qa_field_text(self, field: Any) -> str:
        model = getattr(field, "model", None)
        getter = getattr(model, "get_value_as_string", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return ""
        return ""

    def _set_resolution_settings_schema_qa_field_text(
        self,
        field: Any,
        value: str,
    ) -> None:
        model = getattr(field, "model", None)
        setter = getattr(model, "set_value", None)
        if callable(setter):
            try:
                setter(value)
            except Exception:
                pass

    def _parse_resolution_settings_schema_qa_dimension(self, text: str) -> Any:
        stripped = text.strip()
        try:
            return int(stripped)
        except ValueError:
            return text

    def _apply_resolution_settings_schema_qa_custom_fields(self) -> None:
        qa_store = self._resolution_settings_schema_qa_store()
        entry = {
            "name": self._resolution_settings_schema_qa_field_text(
                self._resolution_settings_schema_qa_name_field
            ),
            "width": self._parse_resolution_settings_schema_qa_dimension(
                self._resolution_settings_schema_qa_field_text(
                    self._resolution_settings_schema_qa_width_field
                )
            ),
            "height": self._parse_resolution_settings_schema_qa_dimension(
                self._resolution_settings_schema_qa_field_text(
                    self._resolution_settings_schema_qa_height_field
                )
            ),
        }
        try:
            add_shared_custom_resolution_entry(qa_store, entry)
        except ValueError:
            self._resolution_settings_schema_qa_profile = (
                _AREA1_QA_PROFILE_CUSTOM_ENTRY_REJECTED
            )
        else:
            self._resolution_settings_schema_qa_profile = (
                _AREA1_QA_PROFILE_CUSTOM_ENTRY_ADDED
            )
            for field in (
                self._resolution_settings_schema_qa_name_field,
                self._resolution_settings_schema_qa_width_field,
                self._resolution_settings_schema_qa_height_field,
            ):
                self._set_resolution_settings_schema_qa_field_text(field, "")
        _refresh_area1_settings_schema_qa_windows()

    def _open_resolution_settings_notification_qa_window(self) -> None:
        if not _env_flag_enabled(AREA1_SETTINGS_NOTIFICATION_QA_ENV):
            return
        if self._resolution_settings_notification_qa_window is not None:
            self._refresh_resolution_settings_notification_qa_window()
            return

        flags = getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
        window = ui.Window(
            "A1 Settings Notifications QA",
            width=590,
            height=150,
            flags=flags,
        )
        self._resolution_settings_notification_qa_window = window
        self._resolution_settings_notification_qa_labels = []
        try:
            window.position_x = 24
            window.position_y = 520
        except Exception:
            pass

        with window.frame:
            with ui.VStack(spacing=4):
                ui.Spacer(height=4)
                with ui.HStack(height=28, spacing=6):
                    ui.Label("A1 Settings Notification QA Surface", width=350)
                    ui.Button(
                        "Close Subscriber",
                        width=150,
                        clicked_fn=self._close_resolution_settings_notification_qa_window,
                    )
                    ui.Spacer()
                ui.Label(f"Viewport ID: {self._viewport_id}", height=18)
                for _ in range(3):
                    label = ui.Label("", height=18, word_wrap=True)
                    self._resolution_settings_notification_qa_labels.append(label)

        self._resolution_settings_notification_qa_last_change = "No recent change"
        self._resolution_settings_notification_qa_change_count = 0
        settings = self._resolution_settings_schema_qa_store()
        try:
            detected_available, _detected_scale = self._detect_resolution_dpi_scale()
            self._resolution_settings_notification_qa_subscription = (
                subscribe_resolution_settings_changes(
                    settings,
                    self._viewport_id,
                    self._on_resolution_settings_notification_qa_change,
                    dpi_scale_available=detected_available,
                )
            )
        except ValueError as exc:
            self._resolution_settings_notification_qa_last_change = (
                f"Subscription unavailable: {exc}"
            )
        self._refresh_resolution_settings_notification_qa_window()

    def _format_resolution_settings_notification_qa_value(self, value: Any) -> str:
        text = repr(value)
        return text if len(text) <= 220 else text[:217] + "..."

    def _on_resolution_settings_notification_qa_change(
        self,
        change: ResolutionSettingsChange,
    ) -> None:
        if self._resolution_settings_notification_qa_window is None:
            return
        self._resolution_settings_notification_qa_change_count += 1
        normalized_value = self._format_resolution_settings_notification_qa_value(
            change.value
        )
        self._resolution_settings_notification_qa_last_change = (
            f"{change.key} -> {normalized_value}"
        )
        self._refresh_resolution_settings_notification_qa_window()

    def _refresh_resolution_settings_notification_qa_window(self) -> None:
        labels = self._resolution_settings_notification_qa_labels
        if not labels:
            return
        lines = (
            f"Last Change: {self._resolution_settings_notification_qa_last_change}",
            f"Accepted Change Count: {self._resolution_settings_notification_qa_change_count}",
            "QA scaffold only; Area 6 owns menu/HUD live refresh",
        )
        for label, text in zip(labels, lines):
            try:
                label.text = text
            except Exception:
                pass
        for label in labels[len(lines):]:
            try:
                label.text = ""
            except Exception:
                pass

    def _cancel_resolution_settings_notification_qa_subscription(self) -> None:
        subscription = self._resolution_settings_notification_qa_subscription
        self._resolution_settings_notification_qa_subscription = None
        if subscription is not None:
            cancel = getattr(subscription, "cancel", None)
            if callable(cancel):
                cancel()

    def _close_resolution_settings_notification_qa_window(self) -> None:
        self._cancel_resolution_settings_notification_qa_subscription()
        window = self._resolution_settings_notification_qa_window
        self._resolution_settings_notification_qa_window = None
        self._resolution_settings_notification_qa_labels = []
        if window is None:
            return
        try:
            window.visible = False
        except Exception:
            pass
        self._resolution_settings_notification_qa_retired_windows.append(window)

    def _destroy_resolution_settings_notification_qa_window(self) -> None:
        self._cancel_resolution_settings_notification_qa_subscription()
        windows = []
        window = self._resolution_settings_notification_qa_window
        if window is not None:
            windows.append(window)
        windows.extend(self._resolution_settings_notification_qa_retired_windows)
        self._resolution_settings_notification_qa_window = None
        self._resolution_settings_notification_qa_retired_windows = []
        self._resolution_settings_notification_qa_labels = []
        for window in windows:
            try:
                window.destroy()
            except Exception:
                try:
                    window.visible = False
                except Exception:
                    pass

    def _build_resolution_catalog_qa_window(self) -> None:
        if self._resolution_catalog_qa_window is not None:
            return

        flags = getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
        window = ui.Window(
            "A2 Resolution Catalog QA",
            width=760,
            height=640,
            flags=flags,
        )
        self._resolution_catalog_qa_window = window
        self._resolution_catalog_qa_labels = []
        try:
            window.position_x = 24
            window.position_y = 70
        except Exception:
            pass

        with window.frame:
            with ui.VStack(spacing=4):
                ui.Spacer(height=4)
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Full Recognized Library",
                        width=190,
                        clicked_fn=self._show_resolution_catalog_qa_full_library,
                    )
                    ui.Button(
                        "Focus 5K Wide",
                        width=132,
                        clicked_fn=self._focus_resolution_catalog_qa_five_k_wide,
                    )
                    ui.Button(
                        "Empty Preset Config",
                        width=160,
                        clicked_fn=self._apply_resolution_catalog_qa_empty_preset_config,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Default Absent",
                        width=142,
                        clicked_fn=self._show_resolution_catalog_qa_default_absent,
                    )
                    ui.Button(
                        "Full Preset Setting",
                        width=168,
                        clicked_fn=self._show_resolution_catalog_qa_full_preset_setting,
                    )
                    ui.Button(
                        "Malformed Presets",
                        width=168,
                        clicked_fn=self._show_resolution_catalog_qa_malformed_preset_list,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Badge Details",
                        width=132,
                        clicked_fn=self._show_resolution_catalog_qa_badge_details,
                    )
                    ui.Button(
                        "Wide Badges",
                        width=128,
                        clicked_fn=self._focus_resolution_catalog_qa_wide_badges,
                    )
                    ui.Button(
                        "Review 1500x1000",
                        width=154,
                        clicked_fn=self._show_resolution_catalog_qa_review_custom_badge,
                    )
                    ui.Button(
                        "Near 21:9 Custom",
                        width=164,
                        clicked_fn=self._show_resolution_catalog_qa_near_21_9_custom_badge,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Sentinel View",
                        width=132,
                        clicked_fn=self._show_resolution_catalog_qa_sentinel_view,
                    )
                    ui.Button(
                        "Choose Viewport",
                        width=144,
                        clicked_fn=self._choose_resolution_catalog_qa_viewport_sentinel,
                    )
                    ui.Button(
                        "Set 1500x1000",
                        width=140,
                        clicked_fn=self._choose_resolution_catalog_qa_unsaved_custom,
                    )
                    ui.Button(
                        "Custom No Size",
                        width=142,
                        clicked_fn=self._try_resolution_catalog_qa_custom_without_size,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Saved Catalog",
                        width=132,
                        clicked_fn=self._show_resolution_catalog_qa_saved_custom_catalog,
                    )
                    ui.Button(
                        "Two Customs",
                        width=132,
                        clicked_fn=self._show_resolution_catalog_qa_two_saved_customs,
                    )
                    ui.Button(
                        "Malformed Customs",
                        width=172,
                        clicked_fn=self._show_resolution_catalog_qa_malformed_saved_customs,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Match HD Copy",
                        width=140,
                        clicked_fn=self._show_resolution_catalog_qa_match_hd_copy,
                    )
                    ui.Button(
                        "Match Review",
                        width=132,
                        clicked_fn=self._show_resolution_catalog_qa_match_review,
                    )
                    ui.Button(
                        "Match 1921x1080",
                        width=156,
                        clicked_fn=self._show_resolution_catalog_qa_match_near_size,
                    )
                    ui.Button(
                        "Match Duplicates",
                        width=156,
                        clicked_fn=self._show_resolution_catalog_qa_match_duplicates,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Selection QA",
                        width=124,
                        clicked_fn=self._show_resolution_catalog_qa_selection_initial,
                    )
                    ui.Button(
                        "Select Viewport",
                        width=136,
                        clicked_fn=self._select_resolution_catalog_qa_viewport,
                    )
                    ui.Button(
                        "Select HD1080P",
                        width=142,
                        clicked_fn=self._select_resolution_catalog_qa_hd1080p,
                    )
                    ui.Button(
                        "Scale 50%",
                        width=112,
                        clicked_fn=self._select_resolution_catalog_qa_scale_50,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Select Review",
                        width=132,
                        clicked_fn=self._select_resolution_catalog_qa_review,
                    )
                    ui.Button(
                        "Select 1921x1080",
                        width=156,
                        clicked_fn=self._select_resolution_catalog_qa_custom,
                    )
                    ui.Button(
                        "Rejected Action",
                        width=150,
                        clicked_fn=self._reject_resolution_catalog_qa_action,
                    )
                    ui.Spacer()
                ui.Separator(height=2)
                with ui.HStack():
                    ui.Spacer(width=10)
                    with ui.VStack(spacing=1):
                        for _ in range(30):
                            label = ui.Label("", height=14, word_wrap=True)
                            self._resolution_catalog_qa_labels.append(label)
                    ui.Spacer(width=10)
                ui.Spacer(height=8)
        self._refresh_resolution_catalog_qa_window()

    def _set_resolution_catalog_qa_preset_config_value(self, value: Any) -> None:
        store = self._resolution_settings_schema_qa_store()
        setter = getattr(store, "set", None)
        if callable(setter):
            setter(SETTING_RESOLUTION_PRESETS, value)

    def _unset_resolution_catalog_qa_preset_config_value(self) -> None:
        store = self._resolution_settings_schema_qa_store()
        unsetter = getattr(store, "unset", None)
        if callable(unsetter):
            unsetter(SETTING_RESOLUTION_PRESETS)

    def _set_resolution_catalog_qa_custom_list(self, entries: list[dict[str, Any]]) -> None:
        store = self._resolution_settings_schema_qa_store()
        write_shared_custom_resolution_list(store, [])
        for entry in entries:
            add_shared_custom_resolution_entry(store, entry)

    def _show_resolution_catalog_qa_full_library(self) -> None:
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_FULL_LIBRARY
        self._resolution_catalog_qa_preset_config = _AREA2_QA_DEFAULT_PRESET_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._refresh_resolution_catalog_qa_window()

    def _focus_resolution_catalog_qa_five_k_wide(self) -> None:
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_FIVE_K_FOCUSED
        self._resolution_catalog_qa_focus_label = "5K Wide"
        self._refresh_resolution_catalog_qa_window()

    def _apply_resolution_catalog_qa_empty_preset_config(self) -> None:
        self._set_resolution_catalog_qa_preset_config_value([])
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_EMPTY_PRESET_CONFIG
        self._resolution_catalog_qa_preset_config = _AREA2_QA_EMPTY_PRESET_CONFIG
        self._resolution_catalog_qa_focus_label = None
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_default_absent(self) -> None:
        self._unset_resolution_catalog_qa_preset_config_value()
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_DEFAULT_PRESET_ABSENT
        self._resolution_catalog_qa_preset_config = _AREA2_QA_DEFAULT_PRESET_ABSENT_CONFIG
        self._resolution_catalog_qa_focus_label = None
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_full_preset_setting(self) -> None:
        configured_value: list[int] = []
        for row in BUILTIN_RESOLUTION_PRESETS:
            configured_value.extend(row.dimensions)
        self._set_resolution_catalog_qa_preset_config_value(configured_value)
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_FULL_PRESET_SETTING
        self._resolution_catalog_qa_preset_config = _AREA2_QA_FULL_PRESET_CONFIG
        self._resolution_catalog_qa_focus_label = None
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_malformed_preset_list(self) -> None:
        self._set_resolution_catalog_qa_preset_config_value(
            _AREA2_QA_MALFORMED_PRESET_SETTING
        )
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_MALFORMED_PRESET_LIST
        self._resolution_catalog_qa_preset_config = _AREA2_QA_MALFORMED_PRESET_CONFIG
        self._resolution_catalog_qa_focus_label = None
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_badge_details(self) -> None:
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_BADGE_DETAILS
        self._resolution_catalog_qa_preset_config = _AREA2_QA_BADGE_DETAILS_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._refresh_resolution_catalog_qa_window()

    def _focus_resolution_catalog_qa_wide_badges(self) -> None:
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_WIDE_BADGES
        self._resolution_catalog_qa_preset_config = _AREA2_QA_BADGE_DETAILS_CONFIG
        self._resolution_catalog_qa_focus_label = "Ultra Wide"
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_review_custom_badge(self) -> None:
        self._set_resolution_catalog_qa_custom_list([_AREA2_QA_REVIEW_CUSTOM])
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_REVIEW_CUSTOM_BADGE
        self._resolution_catalog_qa_preset_config = _AREA2_QA_REVIEW_CUSTOM_CONFIG
        self._resolution_catalog_qa_focus_label = None
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_near_21_9_custom_badge(self) -> None:
        self._set_resolution_catalog_qa_custom_list([_AREA2_QA_NEAR_21_9_CUSTOM])
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_NEAR_21_9_CUSTOM_BADGE
        self._resolution_catalog_qa_preset_config = _AREA2_QA_NEAR_21_9_CUSTOM_CONFIG
        self._resolution_catalog_qa_focus_label = None
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_sentinel_view(self) -> None:
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SENTINEL_VIEW
        self._resolution_catalog_qa_preset_config = _AREA2_QA_SENTINEL_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_requested_size = VIEWPORT_SENTINEL_DIMENSIONS
        self._resolution_catalog_qa_unsaved_size = None
        self._resolution_catalog_qa_attempted_sentinel_label = None
        self._refresh_resolution_catalog_qa_window()

    def _choose_resolution_catalog_qa_viewport_sentinel(self) -> None:
        self._resolution_catalog_qa_profile = (
            _AREA2_QA_PROFILE_SENTINEL_VIEWPORT_SELECTED
        )
        self._resolution_catalog_qa_preset_config = _AREA2_QA_SENTINEL_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_requested_size = (
            requested_size_for_sentinel_selection(VIEWPORT_RESOLUTION_SENTINEL)
        )
        self._resolution_catalog_qa_unsaved_size = None
        self._resolution_catalog_qa_attempted_sentinel_label = "Viewport"
        self._refresh_resolution_catalog_qa_window()

    def _choose_resolution_catalog_qa_unsaved_custom(self) -> None:
        self._resolution_catalog_qa_profile = (
            _AREA2_QA_PROFILE_SENTINEL_CUSTOM_SELECTED
        )
        self._resolution_catalog_qa_preset_config = _AREA2_QA_SENTINEL_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_unsaved_size = _AREA2_QA_UNSAVED_CUSTOM_SIZE
        self._resolution_catalog_qa_requested_size = (
            requested_size_for_sentinel_selection(
                CUSTOM_RESOLUTION_SENTINEL,
                unsaved_size=self._resolution_catalog_qa_unsaved_size,
                previous_requested_size=self._resolution_catalog_qa_requested_size,
            )
        )
        self._resolution_catalog_qa_attempted_sentinel_label = "Custom"
        self._refresh_resolution_catalog_qa_window()

    def _try_resolution_catalog_qa_custom_without_size(self) -> None:
        self._resolution_catalog_qa_profile = (
            _AREA2_QA_PROFILE_SENTINEL_CUSTOM_WITHOUT_SIZE
        )
        self._resolution_catalog_qa_preset_config = _AREA2_QA_SENTINEL_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_unsaved_size = None
        self._resolution_catalog_qa_requested_size = (
            requested_size_for_sentinel_selection(
                CUSTOM_RESOLUTION_SENTINEL,
                unsaved_size=None,
                previous_requested_size=VIEWPORT_SENTINEL_DIMENSIONS,
            )
        )
        self._resolution_catalog_qa_attempted_sentinel_label = "Custom"
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_saved_custom_catalog(self) -> None:
        self._resolution_catalog_qa_profile = (
            _AREA2_QA_PROFILE_SAVED_CUSTOM_CATALOG
        )
        self._resolution_catalog_qa_preset_config = (
            _AREA2_QA_SAVED_CUSTOM_CATALOG_CONFIG
        )
        self._resolution_catalog_qa_focus_label = None
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_two_saved_customs(self) -> None:
        self._set_resolution_catalog_qa_custom_list(
            [_AREA2_QA_REVIEW_CUSTOM, _AREA2_QA_PORTRAIT_CUSTOM]
        )
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_TWO_SAVED_CUSTOMS
        self._resolution_catalog_qa_preset_config = _AREA2_QA_TWO_CUSTOMS_CONFIG
        self._resolution_catalog_qa_focus_label = None
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_malformed_saved_customs(self) -> None:
        self._apply_resolution_settings_schema_qa_custom_profile(
            _AREA1_QA_PROFILE_MALFORMED_CUSTOM_LIST,
            _AREA1_QA_MALFORMED_CUSTOM_LIST,
        )
        self._resolution_catalog_qa_profile = (
            _AREA2_QA_PROFILE_MALFORMED_SAVED_CUSTOMS
        )
        self._resolution_catalog_qa_preset_config = _AREA2_QA_MALFORMED_CUSTOMS_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_match_hd_copy(self) -> None:
        self._set_resolution_catalog_qa_custom_list([_AREA2_QA_HD_COPY_CUSTOM])
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_MATCH_HD_COPY
        self._resolution_catalog_qa_preset_config = _AREA2_QA_MATCH_HD_COPY_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_requested_size = (1920, 1080)
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_match_review(self) -> None:
        self._set_resolution_catalog_qa_custom_list([_AREA2_QA_REVIEW_CUSTOM])
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_MATCH_REVIEW
        self._resolution_catalog_qa_preset_config = _AREA2_QA_MATCH_REVIEW_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_requested_size = _AREA2_QA_UNSAVED_CUSTOM_SIZE
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_match_near_size(self) -> None:
        self._set_resolution_catalog_qa_custom_list(
            [_AREA2_QA_HD_COPY_CUSTOM, _AREA2_QA_REVIEW_CUSTOM]
        )
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_MATCH_NEAR_SIZE
        self._resolution_catalog_qa_preset_config = _AREA2_QA_MATCH_NEAR_SIZE_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_requested_size = _AREA2_QA_NEAR_HD1080P_SIZE
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _show_resolution_catalog_qa_match_duplicates(self) -> None:
        self._apply_resolution_settings_schema_qa_custom_profile(
            _AREA2_QA_PROFILE_MATCH_DUPLICATE_SAVED,
            _AREA2_QA_DUPLICATE_REVIEW_CUSTOMS,
        )
        self._resolution_catalog_qa_profile = (
            _AREA2_QA_PROFILE_MATCH_DUPLICATE_SAVED
        )
        self._resolution_catalog_qa_preset_config = _AREA2_QA_MATCH_DUPLICATE_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_requested_size = _AREA2_QA_UNSAVED_CUSTOM_SIZE
        self._refresh_resolution_catalog_qa_window()

    def _prepare_resolution_catalog_qa_selection(self) -> None:
        self._set_resolution_catalog_qa_custom_list([_AREA2_QA_REVIEW_CUSTOM])
        self._resolution_catalog_qa_preset_config = _AREA2_QA_SELECTION_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_attempted_requested_size = None
        self._resolution_catalog_qa_action_accepted = True

    def _show_resolution_catalog_qa_selection_initial(self) -> None:
        self._prepare_resolution_catalog_qa_selection()
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SELECTION_INITIAL
        self._resolution_catalog_qa_requested_size = VIEWPORT_SENTINEL_DIMENSIONS
        self._resolution_catalog_qa_render_scale = 1.0
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _select_resolution_catalog_qa_viewport(self) -> None:
        self._prepare_resolution_catalog_qa_selection()
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SELECTION_VIEWPORT
        self._resolution_catalog_qa_requested_size = VIEWPORT_SENTINEL_DIMENSIONS
        self._resolution_catalog_qa_render_scale = 1.0
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _select_resolution_catalog_qa_hd1080p(self) -> None:
        self._prepare_resolution_catalog_qa_selection()
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SELECTION_HD1080P
        self._resolution_catalog_qa_requested_size = _AREA2_QA_HD1080P_SIZE
        self._resolution_catalog_qa_render_scale = 1.0
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _select_resolution_catalog_qa_scale_50(self) -> None:
        self._prepare_resolution_catalog_qa_selection()
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SELECTION_SCALE_50
        self._resolution_catalog_qa_requested_size = _AREA2_QA_HD1080P_SIZE
        self._resolution_catalog_qa_render_scale = 0.5
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _select_resolution_catalog_qa_review(self) -> None:
        self._prepare_resolution_catalog_qa_selection()
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SELECTION_REVIEW
        self._resolution_catalog_qa_requested_size = _AREA2_QA_UNSAVED_CUSTOM_SIZE
        self._resolution_catalog_qa_render_scale = 1.0
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _select_resolution_catalog_qa_custom(self) -> None:
        self._prepare_resolution_catalog_qa_selection()
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SELECTION_CUSTOM
        self._resolution_catalog_qa_requested_size = _AREA2_QA_NEAR_HD1080P_SIZE
        self._resolution_catalog_qa_render_scale = 1.0
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _reject_resolution_catalog_qa_action(self) -> None:
        self._resolution_catalog_qa_profile = _AREA2_QA_PROFILE_SELECTION_REJECTED
        self._resolution_catalog_qa_preset_config = _AREA2_QA_SELECTION_CONFIG
        self._resolution_catalog_qa_focus_label = None
        self._resolution_catalog_qa_attempted_requested_size = (
            _AREA2_QA_REJECTED_ACTION_SIZE
        )
        self._resolution_catalog_qa_action_accepted = False
        _refresh_area1_settings_schema_qa_windows()
        self._refresh_resolution_catalog_qa_window()

    def _resolution_catalog_qa_normalized_custom_entries(self) -> list[Any]:
        return resolve_viewport_resolution_settings(
            self._resolution_settings_schema_qa_store(),
            self._viewport_id,
        ).custom_list

    def _refresh_resolution_catalog_qa_window(self) -> None:
        labels = self._resolution_catalog_qa_labels
        if not labels:
            return
        if self._resolution_catalog_qa_profile in {
            _AREA2_QA_PROFILE_SENTINEL_VIEW,
            _AREA2_QA_PROFILE_SENTINEL_VIEWPORT_SELECTED,
            _AREA2_QA_PROFILE_SENTINEL_CUSTOM_SELECTED,
            _AREA2_QA_PROFILE_SENTINEL_CUSTOM_WITHOUT_SIZE,
        }:
            lines = format_resolution_sentinel_qa_lines(
                profile_label=self._resolution_catalog_qa_profile,
                requested_size=self._resolution_catalog_qa_requested_size,
                unsaved_size=self._resolution_catalog_qa_unsaved_size,
                attempted_sentinel_label=(
                    self._resolution_catalog_qa_attempted_sentinel_label
                ),
            )
            for label, text in zip(labels, lines):
                try:
                    label.text = text
                except Exception:
                    pass
            for label in labels[len(lines):]:
                try:
                    label.text = ""
                except Exception:
                    pass
            return
        if self._resolution_catalog_qa_profile in {
            _AREA2_QA_PROFILE_SELECTION_INITIAL,
            _AREA2_QA_PROFILE_SELECTION_VIEWPORT,
            _AREA2_QA_PROFILE_SELECTION_HD1080P,
            _AREA2_QA_PROFILE_SELECTION_SCALE_50,
            _AREA2_QA_PROFILE_SELECTION_REVIEW,
            _AREA2_QA_PROFILE_SELECTION_CUSTOM,
            _AREA2_QA_PROFILE_SELECTION_REJECTED,
        }:
            lines = format_resolution_catalog_selection_qa_lines(
                profile_label=self._resolution_catalog_qa_profile,
                accepted_requested_size=self._resolution_catalog_qa_requested_size,
                custom_entries=self._resolution_catalog_qa_normalized_custom_entries(),
                render_scale=self._resolution_catalog_qa_render_scale,
                attempted_requested_size=(
                    self._resolution_catalog_qa_attempted_requested_size
                ),
                action_accepted=self._resolution_catalog_qa_action_accepted,
            )
            for label, text in zip(labels, lines):
                try:
                    label.text = text
                except Exception:
                    pass
            for label in labels[len(lines):]:
                try:
                    label.text = ""
                except Exception:
                    pass
            return
        if self._resolution_catalog_qa_profile in {
            _AREA2_QA_PROFILE_MATCH_HD_COPY,
            _AREA2_QA_PROFILE_MATCH_REVIEW,
            _AREA2_QA_PROFILE_MATCH_NEAR_SIZE,
            _AREA2_QA_PROFILE_MATCH_DUPLICATE_SAVED,
        }:
            lines = format_resolution_catalog_match_qa_lines(
                profile_label=self._resolution_catalog_qa_profile,
                requested_size=self._resolution_catalog_qa_requested_size,
                custom_entries=self._resolution_catalog_qa_normalized_custom_entries(),
            )
            for label, text in zip(labels, lines):
                try:
                    label.text = text
                except Exception:
                    pass
            for label in labels[len(lines):]:
                try:
                    label.text = ""
                except Exception:
                    pass
            return
        if self._resolution_catalog_qa_profile in {
            _AREA2_QA_PROFILE_SAVED_CUSTOM_CATALOG,
            _AREA2_QA_PROFILE_TWO_SAVED_CUSTOMS,
            _AREA2_QA_PROFILE_MALFORMED_SAVED_CUSTOMS,
        }:
            lines = format_saved_custom_resolution_catalog_qa_lines(
                profile_label=self._resolution_catalog_qa_profile,
                custom_entries=self._resolution_catalog_qa_normalized_custom_entries(),
            )
            for label, text in zip(labels, lines):
                try:
                    label.text = text
                except Exception:
                    pass
            for label in labels[len(lines):]:
                try:
                    label.text = ""
                except Exception:
                    pass
            return
        rows = None
        row_heading = "Recognized built-in rows"
        include_badges = False
        saved_custom_entries = None
        if self._resolution_catalog_qa_profile in {
            _AREA2_QA_PROFILE_DEFAULT_PRESET_ABSENT,
            _AREA2_QA_PROFILE_FULL_PRESET_SETTING,
            _AREA2_QA_PROFILE_MALFORMED_PRESET_LIST,
        }:
            rows = resolve_visible_resolution_presets(
                self._resolution_settings_schema_qa_store()
            )
            row_heading = "Visible preset rows"
        if self._resolution_catalog_qa_profile in {
            _AREA2_QA_PROFILE_BADGE_DETAILS,
            _AREA2_QA_PROFILE_WIDE_BADGES,
            _AREA2_QA_PROFILE_REVIEW_CUSTOM_BADGE,
            _AREA2_QA_PROFILE_NEAR_21_9_CUSTOM_BADGE,
        }:
            include_badges = True
            saved_custom_entries = self._resolution_settings_schema_qa_store().get(
                SETTING_CUSTOM_RESOLUTION_LIST,
                [],
            )
        lines = format_builtin_resolution_catalog_qa_lines(
            profile_label=self._resolution_catalog_qa_profile,
            preset_config_label=self._resolution_catalog_qa_preset_config,
            focus_label=self._resolution_catalog_qa_focus_label,
            rows=rows,
            row_heading=row_heading,
            include_badges=include_badges,
            saved_custom_entries=saved_custom_entries,
        )
        for label, text in zip(labels, lines):
            try:
                label.text = text
            except Exception:
                pass
        for label in labels[len(lines):]:
            try:
                label.text = ""
            except Exception:
                pass

    def _destroy_resolution_catalog_qa_window(self) -> None:
        window = self._resolution_catalog_qa_window
        self._resolution_catalog_qa_window = None
        self._resolution_catalog_qa_labels = []
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            try:
                window.visible = False
            except Exception:
                pass

    def _build_resolution_menu_failure_qa_window(self) -> None:
        if self._resolution_menu_failure_qa_window is not None:
            return

        flags = getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
        window = ui.Window(
            "A7 Menu Failure QA",
            width=430,
            height=112,
            flags=flags,
        )
        self._resolution_menu_failure_qa_window = window
        self._resolution_menu_failure_qa_labels = []
        try:
            window.position_x = 780
            window.position_y = 72
        except Exception:
            pass

        with window.frame:
            with ui.VStack(spacing=4):
                ui.Spacer(height=4)
                for text in (
                    "A7 menu-failure profile active",
                    f"Reason: {_RESOLUTION_MENU_FAILURE_REASON}",
                    "QA only; Settings -> Viewport remains reachable",
                ):
                    with ui.HStack(height=20, spacing=6):
                        ui.Spacer(width=8)
                        label = ui.Label(text)
                        self._resolution_menu_failure_qa_labels.append(label)
                        ui.Spacer()

    def _destroy_resolution_menu_failure_qa_window(self) -> None:
        window = self._resolution_menu_failure_qa_window
        self._resolution_menu_failure_qa_window = None
        self._resolution_menu_failure_qa_labels = []
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            try:
                window.visible = False
            except Exception:
                pass

    def _build_resolution_missing_icon_qa_window(self) -> None:
        if self._resolution_missing_icon_qa_window is not None:
            return

        flags = getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
        window = ui.Window(
            "A7 Missing Icon QA",
            width=520,
            height=132,
            flags=flags,
        )
        self._resolution_missing_icon_qa_window = window
        self._resolution_missing_icon_qa_labels = []
        try:
            window.position_x = 780
            window.position_y = 188
        except Exception:
            pass

        with window.frame:
            with ui.VStack(spacing=4):
                ui.Spacer(height=4)
                for text in (
                    _RESOLUTION_MISSING_ICON_PROFILE_LABEL,
                    "Fallbacks: Settings filter icon/label, link L, save S, delete x",
                    "Badges and warnings remain text labels/tooltips",
                    "QA only; normal launches use configured icon assets",
                ):
                    with ui.HStack(height=20, spacing=6):
                        ui.Spacer(width=8)
                        label = ui.Label(text)
                        self._resolution_missing_icon_qa_labels.append(label)
                        ui.Spacer()

    def _destroy_resolution_missing_icon_qa_window(self) -> None:
        window = self._resolution_missing_icon_qa_window
        self._resolution_missing_icon_qa_window = None
        self._resolution_missing_icon_qa_labels = []
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            try:
                window.visible = False
            except Exception:
                pass

    def _build_resolution_ovui_only_qa_window(self) -> None:
        if self._resolution_ovui_only_qa_window is not None:
            return

        flags = getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
        window = ui.Window(
            "A7 ovui-only Runtime QA",
            width=520,
            height=112,
            flags=flags,
        )
        self._resolution_ovui_only_qa_window = window
        self._resolution_ovui_only_qa_labels = []
        try:
            window.position_x = 780
            window.position_y = 188
        except Exception:
            pass

        with window.frame:
            with ui.VStack(spacing=4):
                ui.Spacer(height=4)
                for text in (
                    _RESOLUTION_OVUI_ONLY_PROFILE_LABEL,
                    "Settings -> Viewport uses ovui widgets only",
                    "Basic row selection remains visibly operable",
                ):
                    with ui.HStack(height=20, spacing=6):
                        ui.Spacer(width=8)
                        label = ui.Label(text)
                        self._resolution_ovui_only_qa_labels.append(label)
                        ui.Spacer()

    def _destroy_resolution_ovui_only_qa_window(self) -> None:
        window = self._resolution_ovui_only_qa_window
        self._resolution_ovui_only_qa_window = None
        self._resolution_ovui_only_qa_labels = []
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            try:
                window.visible = False
            except Exception:
                pass

    def _build_resolution_render_qa_window(self) -> None:
        if self._resolution_render_qa_window is not None:
            return

        flags = getattr(ui, "WINDOW_FLAGS_NO_DOCKING", 0)
        window = ui.Window(
            "A3 Viewport Render QA",
            width=650,
            height=520,
            flags=flags,
        )
        self._resolution_render_qa_window = window
        self._resolution_render_qa_labels = []
        try:
            window.position_x = 24
            window.position_y = 220
        except Exception:
            pass

        with window.frame:
            with ui.VStack(spacing=4):
                ui.Spacer(height=4)
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Frame 1280x720",
                        width=148,
                        clicked_fn=self._apply_resolution_render_qa_frame_1280_720,
                    )
                    ui.Button(
                        "Frame 800x450",
                        width=136,
                        clicked_fn=self._apply_resolution_render_qa_frame_800_450,
                    )
                    ui.Button(
                        "Missing Settings",
                        width=152,
                        clicked_fn=self._apply_resolution_render_qa_missing_settings,
                    )
                    ui.Button(
                        "OpenUSD Session",
                        width=148,
                        clicked_fn=self._apply_resolution_render_qa_openusd_session,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "HD1080P 100%",
                        width=148,
                        clicked_fn=self._apply_resolution_render_qa_fixed_hd1080p_100,
                    )
                    ui.Button(
                        "Render Scale 50%",
                        width=152,
                        clicked_fn=self._apply_resolution_render_qa_fixed_hd1080p_50,
                    )
                    ui.Button(
                        "Frame 800x600",
                        width=136,
                        clicked_fn=self._apply_resolution_render_qa_frame_800_600,
                    )
                    ui.Button(
                        "Resize Fixed Frame",
                        width=152,
                        clicked_fn=self._apply_resolution_render_qa_fixed_resized_frame,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "DPI D=2",
                        width=148,
                        clicked_fn=self._apply_resolution_render_qa_dpi_enabled_d2,
                    )
                    ui.Button(
                        "DPI Unavailable",
                        width=152,
                        clicked_fn=self._apply_resolution_render_qa_dpi_unavailable,
                    )
                    ui.Button(
                        "1501x1001 50%",
                        width=168,
                        clicked_fn=(
                            self._apply_resolution_render_qa_fixed_fractional_50
                        ),
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Icon 25%",
                        width=148,
                        clicked_fn=self._apply_resolution_render_qa_icon_25,
                    )
                    ui.Button(
                        "Tiny 50x40",
                        width=152,
                        clicked_fn=self._apply_resolution_render_qa_tiny_50_40,
                    )
                    ui.Button(
                        "UHD 200%",
                        width=120,
                        clicked_fn=self._apply_resolution_render_qa_uhd_200,
                    )
                    ui.Button(
                        "Invalid 0x-1",
                        width=128,
                        clicked_fn=self._apply_resolution_render_qa_invalid_size,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Frame 1600x900",
                        width=132,
                        clicked_fn=self._apply_resolution_render_qa_frame_1600_900,
                    )
                    ui.Button(
                        "Square Fill Off",
                        width=136,
                        clicked_fn=self._apply_resolution_render_qa_square_fill_off,
                    )
                    ui.Button(
                        "Fill On",
                        width=92,
                        clicked_fn=self._apply_resolution_render_qa_square_fill_on,
                    )
                    ui.Button(
                        "Fill 50%",
                        width=92,
                        clicked_fn=self._apply_resolution_render_qa_square_fill_on_50,
                    )
                    ui.Button(
                        "Viewport",
                        width=88,
                        clicked_fn=self._apply_resolution_render_qa_viewport_after_fill,
                    )
                    ui.Spacer()
                with ui.HStack(height=28, spacing=6):
                    ui.Spacer(width=8)
                    ui.Button(
                        "Interaction QA",
                        width=132,
                        clicked_fn=self._apply_resolution_render_qa_interaction_initial,
                    )
                    ui.Button(
                        "Square Interact",
                        width=140,
                        clicked_fn=self._apply_resolution_render_qa_interaction_square_fill_off,
                    )
                    ui.Button(
                        "Fill Interact",
                        width=120,
                        clicked_fn=self._apply_resolution_render_qa_interaction_fill_on,
                    )
                    ui.Spacer()
                ui.Separator(height=2)
                with ui.HStack():
                    ui.Spacer(width=10)
                    with ui.VStack(spacing=1):
                        for _ in range(23):
                            label = ui.Label("", height=16, word_wrap=True)
                            self._resolution_render_qa_labels.append(label)
                    ui.Spacer(width=10)
                ui.Spacer(height=8)
        self._refresh_resolution_render_qa_window()

    def _clear_resolution_render_qa_dpi_override(self) -> None:
        self._resolution_render_qa_dpi_available = None
        self._resolution_render_qa_dpi_scale = 1.0

    def _set_resolution_render_qa_viewport_state(
        self,
        *,
        uses_dpi: bool = False,
    ) -> None:
        self.set_resolution_state(
            mode="viewport",
            requested_size=VIEWPORT_SENTINEL_DIMENSIONS,
            scale=1.0,
            fill_viewport=False,
            uses_dpi=uses_dpi,
            selected_label=VIEWPORT_RESOLUTION_SENTINEL.label,
            effective_size=None,
        )
        self._resolution_render_qa_status_message = ""

    def _set_resolution_render_qa_fixed_state(
        self,
        requested_size: tuple[int, int],
        *,
        scale: float,
        selected_label: str,
        fill_viewport: bool = False,
        uses_dpi: bool = False,
    ) -> None:
        self.set_resolution_state(
            mode=RESOLUTION_MODE_FIXED,
            requested_size=requested_size,
            scale=scale,
            fill_viewport=fill_viewport,
            uses_dpi=uses_dpi,
            selected_label=selected_label,
            effective_size=None,
        )
        self._resolution_render_qa_status_message = ""

    def _set_resolution_render_qa_fixed_hd1080p_state(self, scale: float) -> None:
        self._set_resolution_render_qa_fixed_state(
            _AREA2_QA_HD1080P_SIZE,
            scale=scale,
            selected_label="HD1080P",
        )

    def _apply_resolution_render_qa_frame_1280_720(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FRAME_1280_720
        self._resolution_render_qa_frame_size = (1280, 720)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_viewport_state()
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_frame_800_450(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FRAME_800_450
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_viewport_state()
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_frame_800_600(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FRAME_800_600
        self._resolution_render_qa_frame_size = (800, 600)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._resolution_render_qa_status_message = (
            "Visible frame resized to 800x600; accepted resolution state unchanged"
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_missing_settings(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_MISSING_SETTINGS
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = True
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_viewport_state()
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_openusd_session(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_OPENUSD_SESSION
        self._resolution_render_qa_frame_size = (1280, 720)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_viewport_state()
        self._resolution_render_qa_status_message = _AREA3_QA_OPENUSD_SESSION_STATUS
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_fixed_hd1080p_100(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FIXED_HD1080P_100
        self._resolution_render_qa_frame_size = (1280, 720)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_hd1080p_state(1.0)
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_fixed_hd1080p_50(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FIXED_HD1080P_50
        if self._resolution_render_qa_frame_size is None:
            self._resolution_render_qa_frame_size = (1280, 720)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_hd1080p_state(0.5)
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_fixed_resized_frame(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FIXED_HD1080P_50_RESIZED
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_hd1080p_state(0.5)
        self._refresh_resolution_render_qa_window()

    def _set_resolution_render_qa_dpi_profile(
        self,
        *,
        available: bool,
        scale: float,
    ) -> None:
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._resolution_render_qa_dpi_available = available
        self._resolution_render_qa_dpi_scale = scale
        self._set_resolution_render_qa_viewport_state(uses_dpi=True)

    def _apply_resolution_render_qa_dpi_enabled_d2(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_DPI_ENABLED_D2
        self._set_resolution_render_qa_dpi_profile(available=True, scale=2.0)
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_dpi_unavailable(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_DPI_UNAVAILABLE
        self._set_resolution_render_qa_dpi_profile(available=False, scale=2.0)
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_fixed_fractional_50(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FIXED_FRACTIONAL_50
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_FRACTIONAL_SIZE,
            scale=0.5,
            selected_label="Custom",
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_icon_25(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_ICON_25
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_ICON_SIZE,
            scale=0.25,
            selected_label="Icon",
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_tiny_50_40(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_TINY_MIN_CLAMP
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_TINY_SIZE,
            scale=1.0,
            selected_label="Custom",
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_uhd_200(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_UHD_200
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_UHD_SIZE,
            scale=2.0,
            selected_label="UHD",
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_invalid_size(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_INVALID_REJECTED
        self._resolution_render_qa_frame_size = (800, 450)
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        try:
            self._set_resolution_render_qa_fixed_state(
                _AREA3_QA_INVALID_SIZE,
                scale=1.0,
                selected_label="Custom",
            )
        except ValueError:
            self._resolution_render_qa_status_message = (
                "Invalid 0x-1 request rejected; previous valid render retained"
            )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_frame_1600_900(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_FRAME_1600_900
        self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_viewport_state()
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_square_fill_off(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_SQUARE_FILL_OFF
        self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_SQUARE_SIZE,
            scale=1.0,
            selected_label="Square",
            fill_viewport=False,
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_square_fill_on(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_SQUARE_FILL_ON
        self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_SQUARE_SIZE,
            scale=1.0,
            selected_label="Square",
            fill_viewport=True,
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_square_fill_on_50(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_SQUARE_FILL_ON_50
        self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_SQUARE_SIZE,
            scale=0.5,
            selected_label="Square",
            fill_viewport=True,
        )
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_viewport_after_fill(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_VIEWPORT_AFTER_FILL
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_viewport_state()
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_interaction_initial(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_INTERACTION_INITIAL
        self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_viewport_state()
        self._resolution_render_qa_status_message = _AREA3_QA_INTERACTION_STATUS
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_interaction_square_fill_off(self) -> None:
        self._resolution_render_qa_profile = (
            _AREA3_QA_PROFILE_INTERACTION_SQUARE_FILL_OFF
        )
        self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_SQUARE_SIZE,
            scale=1.0,
            selected_label="Square",
            fill_viewport=False,
        )
        self._resolution_render_qa_status_message = _AREA3_QA_INTERACTION_STATUS
        self._refresh_resolution_render_qa_window()

    def _apply_resolution_render_qa_interaction_fill_on(self) -> None:
        self._resolution_render_qa_profile = _AREA3_QA_PROFILE_INTERACTION_FILL_ON
        self._resolution_render_qa_frame_size = _AREA3_QA_FILL_FRAME_SIZE
        self._resolution_render_qa_missing_settings = False
        self._clear_resolution_render_qa_dpi_override()
        self._set_resolution_render_qa_fixed_state(
            _AREA3_QA_SQUARE_SIZE,
            scale=1.0,
            selected_label="Square",
            fill_viewport=True,
        )
        self._resolution_render_qa_status_message = _AREA3_QA_INTERACTION_STATUS
        self._refresh_resolution_render_qa_window()

    def _refresh_resolution_render_qa_window(self) -> None:
        labels = self._resolution_render_qa_labels
        if not labels:
            return
        try:
            requested_label = select_resolution_catalog_row_for_state(
                self._resolution_state
            ).current_label
        except Exception:
            requested_label = self._resolution_state.selected_label
        effective = (
            self._last_fixed_mode_effective_resolution
            if self._resolution_state.is_fixed_mode
            else self._last_viewport_mode_effective_resolution
        )
        lines = list(format_viewport_effective_resolution_qa_lines(
            profile_label=self._resolution_render_qa_profile,
            requested_label=requested_label,
            effective=effective,
            missing_settings_profile=self._resolution_render_qa_missing_settings,
            status_message=self._resolution_render_qa_status_message,
        ))
        if self._resolution_render_qa_profile in {
            _AREA3_QA_PROFILE_INTERACTION_INITIAL,
            _AREA3_QA_PROFILE_INTERACTION_SQUARE_FILL_OFF,
            _AREA3_QA_PROFILE_INTERACTION_FILL_ON,
        } and effective is not None:
            visible_frame_size = self._get_raw_viewport_frame_size()
            if visible_frame_size is not None:
                try:
                    rect = compute_aspect_fit_display_rect(
                        visible_frame_size,
                        effective.effective_size,
                    )
                    lines.insert(
                        max(len(lines) - 2, 0),
                        (
                            "A3-T08 Aspect Fit: display "
                            f"{rect.width:.0f}x{rect.height:.0f} at "
                            f"({rect.x:.0f},{rect.y:.0f}); pillarbox "
                            f"L/R={rect.pillarbox_left:.0f}/"
                            f"{rect.pillarbox_right:.0f}; letterbox "
                            f"T/B={rect.letterbox_top:.0f}/"
                            f"{rect.letterbox_bottom:.0f}"
                        ),
                    )
                except Exception:
                    pass
        for label, text in zip(labels, lines):
            try:
                label.text = text
            except Exception:
                pass
        for label in labels[len(lines):]:
            try:
                label.text = ""
            except Exception:
                pass

    def _destroy_resolution_render_qa_window(self) -> None:
        window = self._resolution_render_qa_window
        self._resolution_render_qa_window = None
        self._resolution_render_qa_labels = []
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            try:
                window.visible = False
            except Exception:
                pass

    def _clear_resolution_settings_schema_qa_profile(self) -> None:
        if not self._resolution_settings_schema_qa_uses_persistent_store():
            self._resolution_settings_schema_qa_data.clear()
        self._resolution_settings_schema_qa_profile = _AREA1_QA_PROFILE_REMOVED
        _refresh_area1_settings_schema_qa_windows()

    def _refresh_resolution_settings_schema_qa_window(self) -> None:
        labels = self._resolution_settings_schema_qa_labels
        if not labels:
            return
        profile = self._resolution_settings_schema_qa_profile
        settings = self._resolution_settings_schema_qa_store()
        if profile == _AREA1_QA_PROFILE_DPI_UNAVAILABLE:
            resolved = resolve_viewport_resolution_settings(
                settings,
                viewport_id=self._viewport_id,
                dpi_scale_available=False,
                dpi_scale=1.0,
            )
        else:
            detected_available, detected_scale = self._detect_resolution_dpi_scale()
            resolved = resolve_viewport_resolution_settings(
                settings,
                viewport_id=self._viewport_id,
                dpi_scale_available=detected_available,
                dpi_scale=detected_scale,
            )
        lines = format_resolution_settings_qa_lines(
            resolved,
            profile_label=profile,
        )
        for label, text in zip(labels, lines):
            try:
                label.text = text
            except Exception:
                pass

    def _destroy_resolution_settings_schema_qa_window(self) -> None:
        window = self._resolution_settings_schema_qa_window
        self._resolution_settings_schema_qa_window = None
        self._resolution_settings_schema_qa_labels = []
        self._resolution_settings_schema_qa_name_field = None
        self._resolution_settings_schema_qa_width_field = None
        self._resolution_settings_schema_qa_height_field = None
        try:
            _AREA1_QA_ACTIVE_VIEWPORTS.discard(self)
        except Exception:
            pass
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            try:
                window.visible = False
            except Exception:
                pass

    def _get_active_tool(self) -> Optional[str]:
        if self._tool_registry is not None:
            return getattr(self._tool_registry, "active_tool", None)
        if self._transform_manipulator is not None:
            return getattr(self._transform_manipulator, "tool", None)
        settings = self._resolve_settings()
        if settings is not None:
            try:
                raw = settings.get(ACTIVE_TOOL_SETTING, TOOL_TRANSLATE)
            except (AttributeError, TypeError):
                raw = TOOL_TRANSLATE
            if raw in VALID_TOOLS:
                return raw
        return TOOL_TRANSLATE

    def _build_toolbar_row(self) -> None:
        """Build the viewport toolbar with a leading host before real tools.

        Step 21 intentionally exposes only controls backed by existing
        viewport state. Today that is the transform manipulator's move /
        rotate / scale modes plus the stage-camera selector and post-camera
        generic toolbar contributions. A leading host slot exists before Move
        for the Settings entry point. Area 4 fills that slot with the product
        Settings gear before the Move / Rotate / Scale / Camera controls.
        """
        specs = self._iter_toolbar_tool_specs()
        if not specs:
            self._toolbar_frame = None
            return

        from ovui_widgets.common.style.urls import get_icon_path

        active_tool = self._get_active_tool()
        self._toolbar_frame = ui.Frame(height=self.TOOLBAR_HEIGHT)
        with self._toolbar_frame:
            with ui.ZStack(style_type_name_override="Viewport.Toolbar"):
                ui.Rectangle(style_type_name_override="Viewport.Toolbar")
                with ui.HStack(height=self.TOOLBAR_HEIGHT, spacing=0):
                    ui.Spacer(width=10)
                    self._pre_tools_toolbar_hooks.build_toolbar(
                        ui,
                        button_size=self.TOOLBAR_BUTTON_SIZE,
                    )
                    for tool, label, hotkey, icon_name in specs:
                        icon_path = get_icon_path(icon_name)
                        button_name = f"viewport_toolbar_{tool}"
                        with ui.ZStack(
                            width=self.TOOLBAR_BUTTON_SIZE,
                            height=self.TOOLBAR_BUTTON_SIZE,
                            content_clipping=True,
                        ):
                            background = ui.Rectangle(
                                name="active" if tool == active_tool else "",
                                style_type_name_override="Viewport.Toolbar.Button",
                            )
                            with ui.VStack(spacing=0):
                                ui.Spacer()
                                with ui.HStack(height=self.TOOLBAR_ICON_SIZE, spacing=0):
                                    ui.Spacer()
                                    ui.ImageWithProvider(
                                        _toolbar_icon_provider(icon_path),
                                        width=self.TOOLBAR_ICON_SIZE,
                                        height=self.TOOLBAR_ICON_SIZE,
                                        enabled=False,
                                        opaque_for_mouse_events=False,
                                        style_type_name_override="Viewport.Toolbar.Icon",
                                    )
                                    ui.Spacer()
                                ui.Spacer()
                            button = ui.InvisibleButton(
                                width=self.TOOLBAR_BUTTON_SIZE,
                                height=self.TOOLBAR_BUTTON_SIZE,
                                identifier=button_name,
                                tooltip=f"{label} ({hotkey})",
                            )
                            button.set_clicked_fn(
                                lambda t=tool: self._on_toolbar_tool_clicked(t)
                            )
                        self._toolbar_buttons[tool] = button
                        self._toolbar_button_backgrounds[tool] = background
                        ui.Spacer(width=3)
                    camera_icon_path = get_icon_path("prim_camera")
                    with ui.ZStack(
                        width=self.TOOLBAR_BUTTON_SIZE,
                        height=self.TOOLBAR_BUTTON_SIZE,
                        content_clipping=True,
                    ):
                        background = ui.Rectangle(
                            style_type_name_override="Viewport.Toolbar.Button",
                        )
                        with ui.VStack(spacing=0):
                            ui.Spacer()
                            with ui.HStack(height=self.TOOLBAR_ICON_SIZE, spacing=0):
                                ui.Spacer()
                                ui.ImageWithProvider(
                                    _toolbar_icon_provider(camera_icon_path),
                                    width=self.TOOLBAR_ICON_SIZE,
                                    height=self.TOOLBAR_ICON_SIZE,
                                    enabled=False,
                                    opaque_for_mouse_events=False,
                                    style_type_name_override="Viewport.Toolbar.Icon",
                                )
                                ui.Spacer()
                            ui.Spacer()
                        button = ui.InvisibleButton(
                            width=self.TOOLBAR_BUTTON_SIZE,
                            height=self.TOOLBAR_BUTTON_SIZE,
                            identifier="viewport_toolbar_camera",
                            tooltip="Camera",
                        )
                        button.set_clicked_fn(self._on_camera_menu_button_clicked)
                    self._toolbar_buttons[_TOOLBAR_CAMERA_KEY] = button
                    self._toolbar_button_backgrounds[_TOOLBAR_CAMERA_KEY] = background
                    ui.Spacer(width=3)
                    self._toolbar_hooks.build_toolbar(
                        ui,
                        button_size=self.TOOLBAR_BUTTON_SIZE,
                    )
                    ui.Spacer()

    def _on_toolbar_tool_clicked(self, tool: str) -> None:
        self.set_active_tool(tool)

    def set_active_tool(self, tool: str) -> bool:
        """Set the active transform tool without requiring toolbar widgets."""

        if tool not in VALID_TOOLS:
            return False
        if self._tool_registry is not None:
            self._tool_registry.set_active_tool(tool)
        elif self._transform_manipulator is not None:
            self._transform_manipulator.tool = tool
        else:
            settings = self._resolve_settings()
            if settings is not None:
                try:
                    settings.set(ACTIVE_TOOL_SETTING, tool)
                except AttributeError:
                    pass
        self._refresh_toolbar_state()
        return self._get_active_tool() == tool

    def _on_tool_changed(self, _old_tool: str, _new_tool: str) -> None:
        self._refresh_toolbar_state()

    def _get_transform_control_state(self) -> tuple[bool, str]:
        transform_controls_enabled = True
        transform_disabled_tooltip = ""
        if self._transform_model is not None:
            try:
                transform_controls_enabled = self._transform_model.transform_controls_enabled()
                transform_disabled_tooltip = self._transform_model.transform_controls_tooltip()
            except Exception:
                transform_controls_enabled = True
                transform_disabled_tooltip = ""
        return transform_controls_enabled, transform_disabled_tooltip

    def _refresh_toolbar_state(self) -> None:
        active_tool = self._get_active_tool()
        transform_controls_enabled, transform_disabled_tooltip = (
            self._get_transform_control_state()
        )
        tool_tooltips = {
            tool: f"{label} ({hotkey})"
            for tool, label, hotkey, _icon_name in self._iter_toolbar_tool_specs()
        }
        for tool, background in self._toolbar_button_backgrounds.items():
            is_transform_tool = tool in VALID_TOOLS
            try:
                if is_transform_tool and not transform_controls_enabled:
                    background.name = "disabled"
                else:
                    background.name = "active" if tool == active_tool else ""
            except Exception:
                pass
            if not is_transform_tool:
                continue
            button = self._toolbar_buttons.get(tool)
            if button is None:
                continue
            try:
                button.enabled = bool(transform_controls_enabled)
            except Exception:
                pass
            try:
                button.tooltip = (
                    transform_disabled_tooltip
                    if not transform_controls_enabled and transform_disabled_tooltip
                    else tool_tooltips.get(tool, "")
                )
            except Exception:
                pass

    def _build_tool_state_snapshot(self) -> tuple[ViewportToolState, ...]:
        active_tool = self._get_active_tool()
        controls_enabled, disabled_tooltip = self._get_transform_control_state()
        states: list[ViewportToolState] = []
        for tool, label, hotkey, icon_name in self._iter_toolbar_tool_specs():
            default_tooltip = f"{label} ({hotkey})"
            states.append(
                ViewportToolState(
                    id=tool,
                    label=label,
                    hotkey=hotkey,
                    icon_name=icon_name,
                    active=tool == active_tool,
                    enabled=bool(controls_enabled),
                    tooltip=(
                        disabled_tooltip
                        if not controls_enabled and disabled_tooltip
                        else default_tooltip
                    ),
                )
            )
        return tuple(states)

    def _build_camera_state_snapshot(self) -> tuple[ViewportCameraState, ...]:
        states: list[ViewportCameraState] = []
        for choice in self._list_camera_choices():
            path = str(getattr(choice, "path", "") or "")
            if not path:
                continue
            states.append(
                ViewportCameraState(
                    path=path,
                    label=self._stage_choice_label(choice),
                    active=path == self._active_camera_path,
                )
            )
        return tuple(states)

    def _contribution_enabled(self, registry: Any, contribution: Any) -> bool:
        enabled_fn = getattr(registry, "_enabled", None)
        if not callable(enabled_fn):
            return True
        try:
            return bool(enabled_fn(contribution))
        except Exception:
            return False

    def _toolbar_contribution_text(self, contribution: Any) -> str:
        text_fn = getattr(contribution, "text_fn", None)
        if not callable(text_fn):
            return ""
        try:
            return str(text_fn(self))
        except Exception:
            return ""

    def _toolbar_contribution_tooltip(self, contribution: Any) -> str:
        tooltip_fn = getattr(contribution, "tooltip_fn", None)
        if callable(tooltip_fn):
            try:
                return str(tooltip_fn(self))
            except Exception:
                return ""
        return str(getattr(contribution, "tooltip", "") or "")

    def _build_toolbar_contribution_snapshot(
        self,
    ) -> tuple[ViewportContributionState, ...]:
        states: list[ViewportContributionState] = []
        for contribution in self._toolbar_hooks.iter_contributions():
            states.append(
                ViewportContributionState(
                    id=str(getattr(contribution, "id", "")),
                    label=str(getattr(contribution, "label", "")),
                    kind=str(getattr(contribution, "kind", "")),
                    enabled=self._contribution_enabled(
                        self._toolbar_hooks,
                        contribution,
                    ),
                    widget_name=str(getattr(contribution, "widget_name", "") or ""),
                    tooltip=self._toolbar_contribution_tooltip(contribution),
                    text=self._toolbar_contribution_text(contribution),
                )
            )
        return tuple(states)

    def _build_output_contribution_snapshot(
        self,
    ) -> tuple[ViewportContributionState, ...]:
        states: list[ViewportContributionState] = []
        for contribution in self._viewport_hooks.iter_contributions("output_preset"):
            states.append(
                ViewportContributionState(
                    id=str(getattr(contribution, "id", "")),
                    label=str(getattr(contribution, "label", "")),
                    kind=str(getattr(contribution, "kind", "")),
                    enabled=self._contribution_enabled(
                        self._viewport_hooks,
                        contribution,
                    ),
                    widget_name=str(getattr(contribution, "widget_name", "") or ""),
                )
            )
        return tuple(states)

    def _build_hud_state_snapshot(self) -> ViewportHudState:
        self._refresh_livestream_status()
        fps = self._last_fps
        fps_text = "" if fps is None else f"{fps:.0f}"
        resolution = self._last_resolution
        resolution_text = ""
        if resolution is not None:
            resolution_text = f"{resolution[0]}×{resolution[1]}"
        return ViewportHudState(
            scene=self._scene_name or "",
            fps=fps,
            fps_text=fps_text,
            resolution=resolution,
            resolution_text=resolution_text,
            stream_state=self._last_livestream_state,
            stream_clients=self._last_livestream_clients,
            stream_last_error=self._last_livestream_error,
            stream_text=self._last_livestream_text,
            stream_tooltip=self._last_livestream_tooltip,
        )

    def get_viewport_state_snapshot(self) -> ViewportStateSnapshot:
        """Return toolbar/HUD state independent of server chrome widgets."""

        controls_enabled, controls_tooltip = self._get_transform_control_state()
        return ViewportStateSnapshot(
            active_tool=self._get_active_tool(),
            transform_controls_enabled=bool(controls_enabled),
            transform_controls_tooltip=controls_tooltip,
            tools=self._build_tool_state_snapshot(),
            cameras=self._build_camera_state_snapshot(),
            active_camera_path=self._active_camera_path,
            toolbar_contributions=self._build_toolbar_contribution_snapshot(),
            output_contributions=self._build_output_contribution_snapshot(),
            hud=self._build_hud_state_snapshot(),
        )

    @property
    def chrome_options(self) -> ViewportChromeOptions:
        """Current server-side viewport chrome visibility configuration."""

        return self._get_chrome_options()

    @property
    def toolbar_hooks(self) -> ViewportToolbarRegistry:
        return self._toolbar_hooks

    @property
    def viewport_hooks(self) -> ViewportContributionRegistry:
        return self._viewport_hooks

    def probe_viewport(self, x: float, y: float) -> tuple[ViewportProbeResult, ...]:
        """Run generic viewport probe contributions at an image-space point."""

        w, h = self._get_viewport_size()
        if w <= 0 or h <= 0:
            return ()
        clamped_x = max(0.0, min(float(w - 1), float(x)))
        clamped_y = max(0.0, min(float(h - 1), float(y)))
        view, proj = self._camera.get_matrices(w, h)
        return self._viewport_hooks.probe(
            ViewportProbeContext(
                owner=self,
                x=clamped_x,
                y=clamped_y,
                width=w,
                height=h,
                normalized_x=0.0 if w <= 1 else clamped_x / float(w - 1),
                normalized_y=0.0 if h <= 1 else clamped_y / float(h - 1),
                view_matrix=view,
                projection_matrix=proj,
                image_frame=self._last_image_frame,
                scene_view=self._scene_view,
            )
        )

    @property
    def renderer_adapter(self) -> Optional[RendererAdapter]:
        """Renderer adapter currently driving this viewport."""

        return self._renderer

    def get_viewport_id(self) -> str:
        """Return this viewport's stable lifetime identity.

        Later per-viewport consumers read the identity from the viewport
        instance they already own; no global active-viewport singleton is part
        of the contract.
        """

        return self._viewport_id

    @property
    def viewport_id(self) -> str:
        """Stable lifetime identity for this viewport."""

        return self.get_viewport_id()

    def get_resolution_toolbar_host_context(self) -> ViewportResolutionHostContext:
        """Return the owner context for the leading resolution host."""

        return ViewportResolutionHostContext(
            attachment_id=VIEWPORT_RESOLUTION_ATTACHMENT_ID,
            owner=self,
            viewport_id=self._viewport_id,
        )

    @property
    def resolution_toolbar_host_context(self) -> ViewportResolutionHostContext:
        """Owner context handed to resolution toolbar host builders."""

        return self.get_resolution_toolbar_host_context()

    def attach_resolution_toolbar_host(
        self,
        builder: Callable[[ViewportResolutionHostContext], Any] | Any,
        *,
        replace: bool = False,
    ) -> ViewportResolutionHostAttachment:
        """Attach one leading toolbar contribution for this viewport.

        The attachment identity is fixed at ``viewport.resolution``. Duplicate
        calls for a live viewport return the existing handle unless
        ``replace=True`` is requested, which swaps the contribution without
        allowing duplicate visible controls.
        """

        if self._resolution_toolbar_host_closed:
            raise RuntimeError("resolution toolbar host is closed")
        existing = self._resolution_toolbar_host_attachment
        if existing is not None and existing.active and not replace:
            return existing

        context = self.get_resolution_toolbar_host_context()
        contribution = builder(context) if callable(builder) else builder
        if not isinstance(contribution, _RESOLUTION_HOST_CONTRIBUTION_TYPES):
            raise TypeError(
                "resolution toolbar host builder must return a toolbar contribution"
            )
        if contribution.id != VIEWPORT_RESOLUTION_ATTACHMENT_ID:
            raise ValueError(
                "resolution toolbar host contribution id must be viewport.resolution"
            )

        if existing is not None and existing.active:
            existing.remove()

        toolbar_handle = self._pre_tools_toolbar_hooks.add(contribution)
        attachment = ViewportResolutionHostAttachment(
            self,
            attachment_id=context.attachment_id,
            viewport_id=context.viewport_id,
            toolbar_handle=toolbar_handle,
        )
        self._resolution_toolbar_host_attachment = attachment
        return attachment

    def _remove_resolution_toolbar_host_attachment(
        self,
        attachment: ViewportResolutionHostAttachment,
    ) -> bool:
        if self._resolution_toolbar_host_attachment is not attachment:
            attachment._deactivate()
            return False
        self._resolution_toolbar_host_attachment = None
        try:
            return attachment._remove_from_registry()
        finally:
            attachment._deactivate()

    def _dispose_resolution_toolbar_host_attachment(self) -> None:
        self._resolution_toolbar_host_closed = True
        attachment = self._resolution_toolbar_host_attachment
        self._resolution_toolbar_host_attachment = None
        if attachment is None:
            return
        try:
            attachment._remove_from_registry()
        finally:
            attachment._deactivate()

    def get_resolution_settings(
        self,
        *,
        dpi_scale_available: Optional[bool] = None,
        dpi_scale: Optional[float] = None,
    ) -> ViewportResolutionSettings:
        """Resolve SRD section 6 settings for this viewport without writes."""

        if dpi_scale_available is None or dpi_scale is None:
            detected_available, detected_scale = self._detect_resolution_dpi_scale()
            if dpi_scale_available is None:
                dpi_scale_available = detected_available
            if dpi_scale is None:
                dpi_scale = detected_scale
        return resolve_viewport_resolution_settings(
            self._resolve_settings(),
            viewport_id=self._viewport_id,
            dpi_scale_available=bool(dpi_scale_available),
            dpi_scale=float(dpi_scale),
        )

    @property
    def resolution_settings(self) -> ViewportResolutionSettings:
        """Resolved SRD section 6 settings for this viewport."""

        return self.get_resolution_settings()

    def _detect_resolution_dpi_scale(self) -> tuple[bool, float]:
        try:
            dpi_scale = float(ui.Workspace.get_dpi_scale())
        except Exception:
            return False, 1.0
        if dpi_scale <= 0.0:
            return False, 1.0
        return True, dpi_scale

    def get_resolution_state(self) -> ViewportResolutionState:
        """Return the viewport-owned resolution state record.

        Resolution feature code outside the viewport foundation must use this
        immutable state instead of reading private render-loop storage such as
        ``_last_resolution``.
        """

        return self._resolution_state

    @property
    def resolution_state(self) -> ViewportResolutionState:
        """Current viewport resolution state."""

        return self.get_resolution_state()

    def set_resolution_state(
        self,
        state: Optional[ViewportResolutionState] = None,
        **changes: Any,
    ) -> ViewportResolutionState:
        """Replace or update the viewport-owned resolution state.

        Passing ``state`` replaces the whole record after validation. Passing
        keyword changes applies them to the current record. Supplying both
        applies the keyword changes to ``state``. The accepted result is
        stored and returned.
        """

        base = state if state is not None else self._resolution_state
        if not isinstance(base, ViewportResolutionState):
            raise TypeError("state must be a ViewportResolutionState")
        next_state = base.with_changes(**changes) if changes else base
        if self._resolution_state_observers_closed:
            return self._resolution_state
        previous_state = self._resolution_state
        if next_state == previous_state:
            return previous_state
        self._resolution_state = next_state
        self._notify_resolution_state_changed(previous_state, next_state)
        return next_state

    def subscribe_resolution_state(
        self,
        callback: ResolutionStateChangedCallback,
    ) -> ViewportResolutionStateSubscription:
        """Observe accepted resolution-state changes for this viewport.

        The callback receives ``(old_state, new_state)`` after the new state is
        stored. Call ``unsubscribe()`` or ``cancel()`` on the returned handle to
        remove the observer. Destroying the viewport deactivates all outstanding
        handles and prevents late callbacks from stale external events.
        """

        if not callable(callback):
            raise TypeError("callback must be callable")
        handle = ViewportResolutionStateSubscription(
            self,
            self._resolution_state_next_observer_token,
        )
        if self._resolution_state_observers_closed:
            handle._deactivate()
            return handle
        token = self._resolution_state_next_observer_token
        self._resolution_state_next_observer_token += 1
        self._resolution_state_observers[token] = callback
        self._resolution_state_handles.add(handle)
        return handle

    def _unsubscribe_resolution_state(self, token: int) -> bool:
        return self._resolution_state_observers.pop(token, None) is not None

    def _notify_resolution_state_changed(
        self,
        previous_state: ViewportResolutionState,
        next_state: ViewportResolutionState,
    ) -> None:
        if self._resolution_state_observers_closed:
            return
        for token, callback in tuple(self._resolution_state_observers.items()):
            if token not in self._resolution_state_observers:
                continue
            callback(previous_state, next_state)

    def _dispose_resolution_state_observers(self) -> None:
        self._resolution_state_observers_closed = True
        self._resolution_state_observers.clear()
        for handle in tuple(self._resolution_state_handles):
            handle._deactivate()
        self._resolution_state_handles.clear()

    def get_resolution_availability(self) -> ViewportAvailabilitySnapshot:
        """Return foundation availability facts for this viewport.

        This is a source snapshot only: later UI code may disable presentation
        from these facts, but Area 0 does not hide the future Settings path.
        """

        return self._resolution_availability

    @property
    def resolution_availability(self) -> ViewportAvailabilitySnapshot:
        """Current renderer/settings/owner-liveness availability facts."""

        return self.get_resolution_availability()

    def refresh_resolution_availability(self) -> ViewportAvailabilitySnapshot:
        """Recompute availability facts and notify observers on real changes."""

        return self._refresh_resolution_availability()

    def subscribe_resolution_availability(
        self,
        callback: AvailabilityChangedCallback,
    ) -> ViewportAvailabilitySubscription:
        """Observe accepted availability changes for this viewport.

        The callback receives ``(old_snapshot, new_snapshot)`` after the new
        snapshot is stored. Destroying the viewport first publishes
        ``owner_alive=False`` and then deactivates outstanding handles so late
        events cannot call stale observers.
        """

        if not callable(callback):
            raise TypeError("callback must be callable")
        handle = ViewportAvailabilitySubscription(
            self,
            self._resolution_availability_next_observer_token,
        )
        if self._resolution_availability_observers_closed:
            handle._deactivate()
            return handle
        token = self._resolution_availability_next_observer_token
        self._resolution_availability_next_observer_token += 1
        self._resolution_availability_observers[token] = callback
        self._resolution_availability_handles.add(handle)
        return handle

    def _unsubscribe_resolution_availability(self, token: int) -> bool:
        return self._resolution_availability_observers.pop(token, None) is not None

    def _compute_resolution_availability(
        self,
        *,
        owner_alive: Optional[bool] = None,
    ) -> ViewportAvailabilitySnapshot:
        alive = (
            self._resolution_availability_owner_alive
            if owner_alive is None
            else bool(owner_alive)
        )
        return ViewportAvailabilitySnapshot(
            renderer_available=alive and self._renderer is not None,
            settings_available=alive and self._resolve_settings() is not None,
            owner_alive=alive,
        )

    def _refresh_resolution_availability(
        self,
        *,
        owner_alive: Optional[bool] = None,
    ) -> ViewportAvailabilitySnapshot:
        if owner_alive is not None:
            self._resolution_availability_owner_alive = bool(owner_alive)
        previous_snapshot = self._resolution_availability
        next_snapshot = self._compute_resolution_availability()
        self._resolution_availability = next_snapshot
        if (
            not self._resolution_availability_observers_closed
            and next_snapshot != previous_snapshot
        ):
            self._notify_resolution_availability_changed(
                previous_snapshot,
                next_snapshot,
            )
        return next_snapshot

    def _notify_resolution_availability_changed(
        self,
        previous_snapshot: ViewportAvailabilitySnapshot,
        next_snapshot: ViewportAvailabilitySnapshot,
    ) -> None:
        if self._resolution_availability_observers_closed:
            return
        for token, callback in tuple(self._resolution_availability_observers.items()):
            if token not in self._resolution_availability_observers:
                continue
            callback(previous_snapshot, next_snapshot)

    def _dispose_resolution_availability_observers(self) -> None:
        self._resolution_availability_observers_closed = True
        self._resolution_availability_observers.clear()
        for handle in tuple(self._resolution_availability_handles):
            handle._deactivate()
        self._resolution_availability_handles.clear()

    def _release_viewport_identity(self) -> None:
        if getattr(self, "_viewport_id_released", True):
            return
        _release_viewport_id(self, self._viewport_id)
        self._viewport_id_released = True

    @property
    def stage_adapter(self) -> Any:
        """Stage adapter visible to viewport toolbar contributions, if any."""

        return self._get_stage_adapter()

    def _get_stage_adapter(self) -> Any:
        if self._stage_adapter_provider is None:
            return None
        try:
            return self._stage_adapter_provider()
        except Exception:
            return None

    def _list_camera_choices(self) -> tuple[Any, ...]:
        adapter = self._get_stage_adapter()
        if adapter is None:
            return ()
        try:
            return tuple(adapter.list_cameras())
        except Exception:
            return ()

    def _stage_choice_label(self, choice: Any) -> str:
        display_name = str(getattr(choice, "display_name", "") or "").strip()
        if display_name:
            return display_name
        return str(getattr(choice, "path", "") or "")

    def _destroy_camera_menu(self) -> None:
        menu = self._camera_menu
        self._camera_menu_items = []
        if menu is None:
            return
        try:
            menu.destroy()
        except Exception:
            try:
                menu.hide()
            except Exception:
                pass
        self._camera_menu = None

    def _on_camera_menu_button_clicked(self) -> None:
        button = self._toolbar_buttons.get(_TOOLBAR_CAMERA_KEY)
        if button is None:
            return
        x = float(getattr(button, "screen_position_x", 0.0) or 0.0)
        y = float(
            (getattr(button, "screen_position_y", 0.0) or 0.0)
            + (getattr(button, "computed_height", self.TOOLBAR_BUTTON_SIZE) or 0.0)
        )
        self._show_camera_menu_at(x, y)

    def _show_camera_menu_at(self, x: float, y: float) -> Any:
        self._destroy_camera_menu()
        menu = create_flat_menu(_TOOLBAR_CAMERA_MENU_TITLE, ui_module=ui)
        self._camera_menu = menu
        self._camera_menu_items = []
        choices = self._list_camera_choices()
        with menu:
            added_item = False
            if choices:
                for choice in choices:
                    path = str(getattr(choice, "path", "") or "")
                    if not path:
                        continue
                    checked = path == self._active_camera_path
                    item = ui.MenuItem(
                        self._stage_choice_label(choice),
                        checkable=True,
                        checked=checked,
                        triggered_fn=lambda p=path: self._select_camera_path(p),
                    )
                    self._camera_menu_items.append(
                        (path, self._stage_choice_label(choice), True, item)
                    )
                    added_item = True
            if not added_item:
                item = ui.MenuItem(_TOOLBAR_NO_CAMERAS_LABEL, enabled=False)
                self._camera_menu_items.append(
                    ("", _TOOLBAR_NO_CAMERAS_LABEL, False, item)
                )
        menu.show_at(float(x), float(y))
        return menu

    def _set_renderer_camera_path_if_supported(self, path: Optional[str]) -> bool:
        """Return False only when a concrete renderer selector rejects ``path``."""
        setter = getattr(self._renderer, "set_active_camera_path", None)
        if not callable(setter):
            return True
        if getattr(setter, "__func__", None) is RendererAdapter.set_active_camera_path:
            return True
        try:
            return bool(setter(path))
        except Exception:
            return False

    def select_camera_path(self, path: str) -> bool:
        """Bind viewport navigation to the USD camera at ``path``.

        Optional toolbar integrations can use this public seam without
        reaching into the camera menu's private callback.
        """

        return self._select_camera_path(path)

    def suspend_camera_binding_for_render_target(self) -> bool:
        """Use free viewport navigation for a non-camera render target.

        Sensor/point-cloud RenderProducts are viewable targets, but they are
        not editable USD cameras. Leaving the previous camera bound would make
        MMB navigation in a sensor view write back onto that camera, corrupting
        its pose when the user switches back.
        """

        self._commit_active_camera_pose_if_dirty()
        self._render_target_camera_snapshot = self._camera_state_snapshot()
        self._set_renderer_camera_path_if_supported(None)
        self._active_camera_path = None
        self._last_authored_camera_signature = None
        self._reset_camera_navigation_state()
        return True

    def restore_camera_binding_for_render_target(self) -> bool:
        """Restore the free camera state saved before a non-camera target."""

        snapshot = self._render_target_camera_snapshot
        if snapshot is None:
            return False
        self._restore_camera_state_snapshot(snapshot)
        self._render_target_camera_snapshot = None
        self._active_camera_path = None
        self._last_authored_camera_signature = None
        self._reset_camera_navigation_state()
        return True

    def _camera_state_snapshot(self) -> tuple[Any, ...]:
        state = self._camera.state
        return (
            tuple(float(v) for v in state.target),
            float(state.distance),
            float(state.azimuth),
            float(state.elevation),
            tuple(float(v) for v in self._camera.up_axis),
            float(self._camera.fov_degrees),
        )

    def _restore_camera_state_snapshot(self, snapshot: tuple[Any, ...]) -> None:
        target, distance, azimuth, elevation, up_axis, fov = snapshot
        state = self._camera.state
        state.target = [float(v) for v in target]
        state.distance = float(distance)
        state.azimuth = float(azimuth)
        state.elevation = float(elevation)
        self._camera.up_axis = [float(v) for v in up_axis]
        self._camera.fov_degrees = float(fov)
        self._sync_camera_manipulator_up_axis()

    def _select_camera_path(self, path: str) -> bool:
        if not isinstance(path, str) or not path:
            return False
        adapter = self._get_stage_adapter()
        if adapter is None:
            return False
        try:
            pose = adapter.read_camera_pose(path)
        except Exception:
            return False
        previous_path = self._active_camera_path
        # Bind the renderer to the selected camera before recording the
        # widget state. Supporting renderers can reject invalid prim paths;
        # when that happens the menu must not claim a camera that the
        # renderer did not actually bind. Minimal/mock renderers inherit
        # the base no-op selector and remain permissive for pure widget
        # tests.
        if not self._set_renderer_camera_path_if_supported(path):
            return False
        if previous_path and previous_path != path:
            self._commit_active_camera_pose_if_dirty()
        if not self.apply_camera_pose(pose):
            self._set_renderer_camera_path_if_supported(previous_path)
            return False
        self._active_camera_path = path
        self._last_authored_camera_signature = self._camera_author_signature(path)
        self._render_target_camera_snapshot = None
        self._reset_camera_navigation_state()
        return True

    def _build_hud_label(
        self,
        text: str,
        style: str,
        width: Optional[int] = None,
        alignment: Any = ui.Alignment.LEFT_CENTER,
    ) -> Any:
        kwargs = {
            "alignment": alignment,
            "style_type_name_override": style,
        }
        if width is not None:
            kwargs["width"] = width
        return ui.Label(text, **kwargs)

    def _build_hud_pair(
        self,
        label: str,
        label_width: int = 42,
        value_width: Optional[int] = None,
        right_align_value: bool = False,
    ) -> Any:
        self._build_hud_label(label, "Viewport.HUD.Label", width=label_width)
        ui.Spacer(width=6)
        alignment = ui.Alignment.RIGHT_CENTER if right_align_value else ui.Alignment.LEFT_CENTER
        return self._build_hud_label(
            "",
            "Viewport.HUD.Value",
            width=value_width,
            alignment=alignment,
        )

    def _build_hud(self) -> None:
        chrome = self._get_chrome_options()
        with ui.ZStack(style_type_name_override="Viewport.HUD"):
            # Top-left: scene, FPS, and render resolution.
            if chrome.show_text_hud:
                with ui.VStack(spacing=0):
                    ui.Spacer(height=self._get_hud_top_padding())
                    with ui.HStack(height=38):
                        ui.Spacer(width=14)
                        with ui.VStack(width=430, spacing=0):
                            self._scene_row = ui.HStack(height=16, spacing=0)
                            with self._scene_row:
                                self._scene_value_label = self._build_hud_pair("SCENE")
                            self._fps_res_row = ui.HStack(height=16, spacing=0)
                            with self._fps_res_row:
                                self._fps_value_label = self._build_hud_pair(
                                    "FPS",
                                    label_width=28,
                                    value_width=30,
                                )
                                ui.Spacer(width=8)
                                self._fps_res_separator_label = self._build_hud_label(
                                    "·",
                                    "Viewport.HUD.Separator",
                                    width=8,
                                )
                                ui.Spacer(width=8)
                                self._resolution_label = self._build_hud_label(
                                    "RES",
                                    "Viewport.HUD.Label",
                                    width=28,
                                )
                                ui.Spacer(width=6)
                                self._resolution_value_label = self._build_hud_label(
                                    "",
                                    "Viewport.HUD.Value",
                                    width=120,
                                )
                        ui.Spacer()
                    ui.Spacer()

            # Top-right: livestream status overlay (Step 1.7). The row
            # is hidden when the renderer has no livestream tap; when
            # present, ``_refresh_livestream_status`` rewrites the label
            # text every frame from ``LivestreamTap.status()`` and a
            # tooltip surfaces the static config (protocol, ports, IP).
            if chrome.show_livestream_overlay:
                with ui.VStack(spacing=0):
                    ui.Spacer(height=self._get_hud_top_padding())
                    with ui.HStack(height=22):
                        ui.Spacer()
                        self._livestream_row = ui.HStack(width=320, height=18, spacing=0)
                        with self._livestream_row:
                            ui.Spacer()
                            self._build_hud_label(
                                "STREAM", "Viewport.HUD.Label", width=56,
                            )
                            ui.Spacer(width=6)
                            self._livestream_value_label = self._build_hud_label(
                                "",
                                "Viewport.HUD.Value",
                                width=240,
                            )
                        ui.Spacer(width=14)
                    ui.Spacer()

        # Backward-compatible alias used by older tests and callers: the FPS
        # value label is now only the value part of the label/value row.
        self._fps_label = self._fps_value_label
        self._refresh_hud()

    def _get_hud_top_padding(self) -> int:
        toolbar_height = (
            self.TOOLBAR_HEIGHT if self._get_chrome_options().show_toolbar else 0
        )
        return toolbar_height + 4

    @staticmethod
    def _set_widget_visible(widget: Any, visible: bool) -> None:
        if widget is not None:
            widget.visible = visible

    def _hud_resolution_size(self) -> Optional[tuple[int, int]]:
        """Return the committed effective size that drives the HUD RES field."""

        state_size = self._resolution_state.effective_size
        if state_size is not None:
            try:
                return ensure_safe_renderer_request_size(state_size)
            except Exception:
                pass
        if self._last_resolution is not None:
            try:
                return ensure_safe_renderer_request_size(self._last_resolution)
            except Exception:
                pass
        return None

    def _refresh_hud(self) -> None:
        if self._resolution_sync_is_disposed():
            return
        scene = self._scene_name or ""
        if self._scene_value_label is not None:
            self._scene_value_label.text = scene
        self._set_widget_visible(self._scene_row, bool(scene))

        fps_text = "" if self._last_fps is None else f"{self._last_fps:.0f}"
        res_text = ""
        resolution_size = self._hud_resolution_size()
        if resolution_size is not None:
            res_text = f"{resolution_size[0]}×{resolution_size[1]}"
        if self._fps_value_label is not None:
            self._fps_value_label.text = fps_text
        if self._resolution_value_label is not None:
            self._resolution_value_label.text = res_text
        self._set_widget_visible(self._fps_res_row, bool(fps_text or res_text))
        self._set_widget_visible(self._resolution_label, bool(res_text))
        self._set_widget_visible(self._resolution_value_label, bool(res_text))
        self._set_widget_visible(self._fps_res_separator_label, bool(fps_text and res_text))

        self._refresh_livestream_status()

    def _record_fps_sample(self, render_dt: float) -> None:
        if render_dt <= 0.0:
            return
        dt = float(render_dt)
        self._fps_sample_intervals.append(dt)
        self._fps_sample_seconds += dt
        while (
            len(self._fps_sample_intervals) > 1
            and self._fps_sample_seconds > self.FPS_AVERAGE_WINDOW_SECONDS
        ):
            self._fps_sample_seconds -= self._fps_sample_intervals.popleft()
        if self._fps_sample_seconds > 0.0:
            self._last_fps = len(self._fps_sample_intervals) / self._fps_sample_seconds

    def _reset_fps_samples(self) -> None:
        if not hasattr(self, "_fps_sample_intervals"):
            self._fps_sample_intervals = deque()
        self._fps_sample_intervals.clear()
        self._fps_sample_seconds = 0.0
        self._last_fps = None

    def _refresh_livestream_status(self) -> None:
        """Read the current livestream-tap snapshot and update the
        Step-1.7 status overlay (label text + tooltip).

        Hidden when the renderer has no ``livestream`` tap (i.e.
        ``OVGEAR_LIVESTREAM`` is unset or the SDK is missing). Called
        from ``_refresh_hud`` so the overlay updates once per render. The
        status cache is updated even when the server overlay is hidden so a
        browser-side HUD can read backend-authored stream state.
        """
        tap = getattr(self._renderer, "livestream", None) if self._renderer else None
        if tap is None:
            self._last_livestream_state = None
            self._last_livestream_clients = None
            self._last_livestream_error = ""
            self._last_livestream_text = ""
            self._last_livestream_tooltip = ""
            self._set_widget_visible(self._livestream_row, False)
            return

        try:
            state, n_clients, last_error = tap.status()
        except Exception:
            self._last_livestream_state = None
            self._last_livestream_clients = None
            self._last_livestream_error = ""
            self._last_livestream_text = ""
            self._last_livestream_tooltip = ""
            self._set_widget_visible(self._livestream_row, False)
            return

        signal_port = int(getattr(tap, "signal_port", 0))
        media_port = int(getattr(tap, "media_port", 0))
        protocol = str(getattr(tap, "protocol", "?"))
        public_ip = getattr(tap, "public_ip", None)

        text = _ls_overlay.format_indicator(
            state, n_clients, last_error, signal_port, media_port,
        )
        tooltip = _ls_overlay.format_tooltip(
            state, n_clients, last_error, signal_port, media_port,
            protocol, public_ip,
        )

        self._last_livestream_state = str(state)
        self._last_livestream_clients = int(n_clients)
        self._last_livestream_error = "" if last_error is None else str(last_error)
        self._last_livestream_text = text
        self._last_livestream_tooltip = tooltip

        if not self._get_chrome_options().show_livestream_overlay:
            self._set_widget_visible(self._livestream_row, False)
            return

        if self._livestream_value_label is not None:
            self._livestream_value_label.text = text
            # ``set_tooltip`` is the omni.ui idiom; fall back to
            # ``tooltip`` attribute on builds where the setter is absent.
            try:
                self._livestream_value_label.set_tooltip(tooltip)
            except AttributeError:
                try:
                    self._livestream_value_label.tooltip = tooltip
                except Exception:
                    pass
        self._set_widget_visible(self._livestream_row, True)

    def _get_viewport_size(self) -> tuple:
        """Return the current effective render size for camera/scene overlays.

        The camera gestures and transform gizmo must use the same effective
        dimensions as rendering. Falling back to the raw widget frame is only
        for pre-render startup, before Area 3 has committed an effective size.
        """
        state_size = self._resolution_state.effective_size
        if state_size is not None:
            try:
                return ensure_safe_renderer_request_size(state_size)
            except Exception:
                pass
        if self._last_resolution is not None:
            try:
                return ensure_safe_renderer_request_size(self._last_resolution)
            except Exception:
                pass
        return self._get_raw_viewport_frame_size()

    def _get_raw_viewport_frame_size(self) -> tuple[int, int]:
        """Return the visible image widget frame size before aspect-fit mapping."""

        w = 0
        h = 0
        if self._image is not None:
            w = int(self._image.computed_width or 0)
            h = int(self._image.computed_height or 0)
        if w <= 0:
            w = self._width
        if h <= 0:
            h = self._height
        return (w, h)

    def _interaction_frame_and_render_size(
        self,
    ) -> tuple[tuple[int, int], tuple[int, int]] | None:
        frame_size = self._get_raw_viewport_frame_size()
        try:
            frame_size = ensure_safe_renderer_request_size(frame_size)
        except Exception:
            return None
        render_size = self._resolution_state.effective_size or self._last_resolution
        if render_size is None:
            render_size = frame_size
        try:
            render_size = ensure_safe_renderer_request_size(render_size)
        except Exception:
            return None
        return frame_size, render_size

    def _map_widget_pick_to_render_ndc(
        self,
        x: float,
        y: float,
    ) -> tuple[float, float] | None:
        # Direct unit tests historically called this private method with
        # arbitrary renderer-space values. Runtime PickGesture callbacks use
        # normalized widget coordinates, so only remap the runtime NDC range.
        if x < -1.0 or x > 1.0 or y < -1.0 or y > 1.0:
            return (x, y)
        sizes = self._interaction_frame_and_render_size()
        if sizes is None:
            return (x, y)
        frame_size, render_size = sizes
        mapping = map_widget_ndc_to_render_ndc(x, y, frame_size, render_size)
        if mapping is None:
            return None
        return mapping.render_ndc

    def _map_widget_pick_rect_to_render_ndc_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> tuple[float, float, float, float] | None:
        if any(value < -1.0 or value > 1.0 for value in (x0, y0, x1, y1)):
            return (x0, y0, x1, y1)
        sizes = self._interaction_frame_and_render_size()
        if sizes is None:
            return (x0, y0, x1, y1)
        frame_size, render_size = sizes
        return map_widget_ndc_rect_to_render_ndc_rect(
            x0,
            y0,
            x1,
            y1,
            frame_size,
            render_size,
        )

    def _make_pick_callback(self, mode: str) -> Any:
        """Return a point-pick callback bound to a selection ``mode``.

        ``mode`` is one of ``"replace"`` / ``"add"`` / ``"remove"`` — see
        :meth:`_merge_selection` for the semantics. The returned closure
        is what ``PickGesture`` invokes with the NDC ``(x, y)`` of the
        click.
        """
        def _cb(x: float, y: float) -> None:
            self._on_pick(x, y, mode)
        return _cb

    def _make_pick_rect_callback(self, mode: str) -> Any:
        """Return a marquee callback bound to a selection ``mode``."""
        def _cb(x0: float, y0: float, x1: float, y1: float) -> None:
            self._on_pick_rect(x0, y0, x1, y1, mode)
        return _cb

    def _on_pick(self, x: float, y: float, mode: str = "replace") -> None:
        if self._dismiss_settings_toolbar_menu():
            return
        if self._receiving_from_bus:
            return
        renderer = self._renderer
        if renderer is None:
            return
        cancel_pick = getattr(renderer, "cancel_pick", None)
        if callable(cancel_pick):
            cancel_pick("viewport_click")
        pick = getattr(renderer, "pick", None)
        if not callable(pick):
            return
        mapped = self._map_widget_pick_to_render_ndc(x, y)
        if mapped is None:
            return
        render_x, render_y = mapped
        pick(
            render_x, render_y,
            lambda path, pos: self._on_pick_result(path, mode),
            "viewport_click",
        )

    def _on_pick_result(self, path: Any, mode: str = "replace") -> None:
        hits = self._validate_selection_paths([path] if path else [])
        merged = self._merge_selection(hits, mode)
        self._pushing_to_bus = True
        try:
            if self._bus:
                self._bus.publish(merged, source="viewport")
        finally:
            self._pushing_to_bus = False
        self._apply_self_published_selection(merged)

    def _on_pick_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        mode: str = "replace",
    ) -> None:
        if self._dismiss_settings_toolbar_menu():
            return
        if self._receiving_from_bus:
            return
        renderer = self._renderer
        if renderer is None:
            return
        pick_rect = getattr(renderer, "pick_rect", None)
        if not callable(pick_rect):
            return
        mapped = self._map_widget_pick_rect_to_render_ndc_rect(x0, y0, x1, y1)
        if mapped is None:
            return
        render_x0, render_y0, render_x1, render_y1 = mapped
        pick_rect(
            render_x0, render_y0, render_x1, render_y1,
            lambda paths: self._on_pick_rect_result(paths, mode),
        )

    def _on_pick_rect_result(self, paths: Any, mode: str = "replace") -> None:
        hits = self._validate_selection_paths(list(paths or []))
        merged = self._merge_selection(hits, mode)
        self._pushing_to_bus = True
        try:
            if self._bus:
                self._bus.publish(merged, source="viewport")
        finally:
            self._pushing_to_bus = False
        self._apply_self_published_selection(merged)

    def _validate_selection_paths(self, paths: list) -> list[str]:
        selected = [str(path) for path in (paths or []) if path]
        adapter = self._get_stage_adapter()
        if adapter is None:
            return list(dict.fromkeys(selected))
        validated: list[str] = []
        for path in selected:
            try:
                item = adapter.get_item_at_path(path)
            except Exception:
                item = None
            if item is not None:
                validated.append(path)
        return list(dict.fromkeys(validated))

    def _apply_self_published_selection(self, paths: list) -> None:
        """Mirror a viewport-initiated publish onto the viewport's own UI.

        :meth:`_on_bus_selection_changed` short-circuits when
        ``_pushing_to_bus`` is ``True`` to avoid a republish loop. That
        guard also skipped the benign-but-necessary calls that update
        the renderer highlight and gizmo — so a
        click on a prim selected it on the bus but left the viewport's
        own overlays stale. This helper runs those updates after the
        guard window closes. ``_on_bus_selection_changed`` keeps doing
        them for non-viewport sources (Stage Browser, keyboard shortcut,
        undo, etc.).
        """
        self._set_renderer_selection_highlight(paths)
        self._request_selection_highlight_retry(paths)
        if self._manipulator_registry is not None:
            try:
                self._manipulator_registry.on_selection_changed(paths)
            except Exception:
                pass
        if self._transform_model is not None:
            try:
                self._transform_model.set_selection(paths)
            except Exception:
                pass
        if self._transform_manipulator is not None:
            try:
                self._transform_manipulator.invalidate()
            except Exception:
                pass
            # Selection moved the pivot — reset the scale baseline so the
            # next ``_maybe_invalidate_gizmo_for_scale`` re-evaluates
            # against the new pivot rather than the previous prim's.
            self._last_gizmo_scale = 0.0
        self._refresh_toolbar_state()

    def sync_selection_from_bus(self) -> list[str]:
        """Synchronize viewport visuals from the attached SelectionBus.

        Backend-hosted viewports can publish selection through a protocol
        service rather than through the viewport's native pick callbacks. The
        SelectionBus remains authoritative; this public sync method mirrors its
        current snapshot into the renderer highlight, manipulator registry, and
        transform model without creating any synthetic selection or transform
        state.
        """

        if self._bus is None:
            self._apply_self_published_selection([])
            self._refresh_hud()
            return []
        try:
            snapshot = self._bus.get_snapshot()
            paths = list(snapshot.paths()) if snapshot is not None else []
        except Exception:
            paths = []
        self._apply_self_published_selection(paths)
        self._refresh_hud()
        return paths

    def _merge_selection(self, hits: list, mode: str) -> list:
        """Combine ``hits`` with the current selection according to ``mode``.

        * ``"replace"`` — returns ``hits`` verbatim (plain click behavior).
        * ``"add"`` — union of current selection + ``hits``, current-order
          first so a shift-click appended item lands at the end of the
          list.
        * ``"remove"`` — current selection minus ``hits``; order of the
          surviving paths is preserved. A ctrl-click on empty space
          (``hits == []``) leaves the selection unchanged.

        Duplicates in ``hits`` or between ``hits`` and current selection
        are collapsed via ``dict.fromkeys`` (preserves order, dedupes).
        """
        if self._bus is None:
            return list(hits) if mode != "remove" else []
        try:
            snap = self._bus.get_snapshot()
            current = list(snap.paths()) if snap else []
        except Exception:
            current = []
        if mode == "replace":
            return list(dict.fromkeys(hits))
        if mode == "add":
            return list(dict.fromkeys(current + list(hits)))
        if mode == "remove":
            hit_set = set(hits)
            return [p for p in current if p not in hit_set]
        # Unknown mode — fall back to replace rather than raise so a
        # stale setting can't bring the viewport down.
        return list(dict.fromkeys(hits))

    def _on_bus_selection_changed(self, event: SelectionChangedEvent) -> None:
        if self._pushing_to_bus:
            return
        self._receiving_from_bus = True
        try:
            paths = event.snapshot.paths()
            self._set_renderer_selection_highlight(paths)
            self._request_selection_highlight_retry(paths)
            if self._manipulator_registry is not None:
                self._manipulator_registry.on_selection_changed(paths)
            # Feed the transform gizmo. ``set_selection`` filters to the
            # transformable subset when the adapter is wired (post
            # ``attach_stage``); otherwise it keeps the raw list so the
            # gizmo still appears. Invalidate so the next draw emits
            # geometry at the new pivot.
            if self._transform_model is not None:
                self._transform_model.set_selection(paths)
            if self._transform_manipulator is not None:
                self._transform_manipulator.invalidate()
                self._last_gizmo_scale = 0.0
            self._refresh_toolbar_state()
        finally:
            self._receiving_from_bus = False
        self._refresh_hud()

    def _request_selection_highlight_retry(self, paths: list) -> None:
        """Retry the current renderer outline once after the next rendered frame."""

        self._selection_highlight_retry_paths = [str(path) for path in (paths or [])]

    def _retry_selection_highlight_after_render(self) -> None:
        retry_paths = self._selection_highlight_retry_paths
        if retry_paths is None:
            return
        self._selection_highlight_retry_paths = None
        current_paths = list(retry_paths)
        if self._bus is not None:
            try:
                snap = self._bus.get_snapshot()
                current_paths = snap.paths() if snap else []
            except Exception:
                current_paths = list(retry_paths)
        self._set_renderer_selection_highlight(current_paths, force=True)

    def _set_renderer_selection_highlight(
        self,
        paths: list,
        *,
        force: bool = False,
    ) -> None:
        """Apply selection highlights to renderable mesh targets.

        Stage/Property selection remains the user's exact selected paths.
        The renderer outline pass, however, only visibly outlines renderable
        geometry, so Xform/Scope/group selections are expanded to their
        descendant mesh prims before calling the renderer.
        """
        try:
            highlight_paths = self._resolve_selection_highlight_paths(paths)
            renderer = self._renderer
            if force:
                refresh_highlight = getattr(
                    renderer,
                    "refresh_selection_highlight",
                    None,
                )
                if callable(refresh_highlight):
                    refresh_highlight(highlight_paths)
                    return
                renderer.set_selection_highlight([])  # type: ignore[union-attr]
            renderer.set_selection_highlight(highlight_paths)  # type: ignore[union-attr]
        except Exception:
            pass

    def _resolve_selection_highlight_paths(self, paths: list) -> list[str]:
        selected = [str(path) for path in (paths or []) if path]
        adapter = self._get_stage_adapter()
        if adapter is None:
            return list(dict.fromkeys(selected))

        resolved: list[str] = []
        for path in selected:
            try:
                item = adapter.get_item_at_path(path)
            except Exception:
                item = None
            if item is None:
                resolved.append(path)
                continue
            resolved.extend(self._collect_mesh_highlight_paths(adapter, item))
        return list(dict.fromkeys(resolved))

    def _collect_mesh_highlight_paths(self, adapter: Any, item: Any) -> list[str]:
        paths: list[str] = []
        stack = [item]
        while stack:
            current = stack.pop()
            try:
                if adapter.get_type_category(current) == "Mesh":
                    paths.append(str(adapter.get_item_path(current)))
            except Exception:
                pass
            try:
                children = list(adapter.get_children(current) or [])
            except Exception:
                children = []
            stack.extend(reversed(children))
        return paths

    def _get_outline_selection(self) -> list:
        """Return selected paths for renderer/gizmo change invalidation.

        Reads from the ``SelectionBus`` rather than the transform model so
        non-transformable prims are still considered when deciding whether a
        stage change affects the current selection.
        """
        if self._bus is None:
            return []
        try:
            snap = self._bus.get_snapshot()
        except Exception:
            return []
        if snap is None:
            return []
        try:
            return list(snap.paths())
        except Exception:
            return []

    def _get_gizmo_world_scale(self) -> float:
        """Return the per-frame gizmo world-scale for constant screen size.

        The fixed :data:`~ovui_widgets.viewport.transform_manipulator.GIZMO_SIZE_SCALE`
        placeholder is too small for USD scenes authored in centimetres or
        larger units — a 0.05-unit gizmo is sub-pixel at normal camera
        distances. This computes a world scale that keeps the gizmo a
        consistent fraction of the viewport height:

            world_scale = distance_from_eye_to_pivot
                         * tan(fov/2) * 2
                         * SCREEN_FRACTION / viewport_height_px

        With ``fov = 45°`` and ``SCREEN_FRACTION = 80 px``, that collapses
        to roughly ``0.092 * distance`` on a 720-px-tall viewport, which
        sits comfortably between "visible at every distance" and
        "dominates the frame".
        """
        import math
        try:
            pivot = self._transform_model.get_pivot_world() if self._transform_model else (0.0, 0.0, 0.0)
            eye = self._camera._get_eye()
            dx = float(eye[0]) - float(pivot[0])
            dy = float(eye[1]) - float(pivot[1])
            dz = float(eye[2]) - float(pivot[2])
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        except Exception:
            dist = float(self._camera.state.distance)
        # Keep the gizmo roughly 80 pixels tall on a 720-tall viewport.
        # tan(22.5°) ≈ 0.4142. The final ratio is independent of viewport
        # height for a perspective camera — the FOV fully determines the
        # screen-space / world-space ratio at the pivot.
        SCREEN_PIXEL_TARGET = 80.0
        _, vh = self._get_viewport_size()
        if vh <= 0:
            vh = 720
        scale = dist * math.tan(math.radians(45.0) * 0.5) * 2.0 * (SCREEN_PIXEL_TARGET / float(vh))
        # Floor so the gizmo never shrinks to zero at very small camera
        # distances (e.g., min-zoom clamp at 0.01).
        return max(scale, 1e-4)

    def _compute_world_bbox(self, path: str):
        """Return ``((min_xyz, max_xyz))`` AABB for ``path`` or ``None``.

        Retained as a small compatibility helper for existing tests and
        callers that need viewport-owned stage bounds. Native ovrtx selection
        outlines no longer use this path for production drawing.

        Step 17 delegates to
        :meth:`StageAdapter.compute_prim_world_aabb_with_extent_fallback`
        so the widget no longer imports ``pxr``. The adapter implementation
        retains the original two-tier algorithm: ``Boundable.ComputeExtent``
        for prims with extent-driving attributes (radius / size / points),
        ``UsdGeom.BBoxCache`` for non-Boundable selections.

        Adapter exceptions are caught and reported as ``None``, preserving
        the pre-Step-17 no-throw contract (the old inline pxr code wrapped
        the entire body in ``try/except`` for the same reason). A failing
        adapter implementation must not break the manipulator.
        """
        if self._stage_adapter_provider is None:
            return None
        adapter = self._stage_adapter_provider()
        if adapter is None:
            return None
        try:
            return adapter.compute_prim_world_aabb_with_extent_fallback(path)
        except Exception:
            return None

    def attach_stage(
        self,
        transform_adapter: Any,
        stage_adapter: Any,
        undo_manager: Any,
        snap_system: Any = None,
    ) -> None:
        """Wire per-stage adapters into the transform gizmo (Step C.2).

        Called by :class:`~ovui_widgets.app.application.Application._load_stage` after
        the USD stage has been opened and the stage/transform adapters have
        been constructed. The adapters live on the
        :class:`PrimTransformModel` for the lifetime of the stage; loading
        a different stage replaces them.
        """
        if getattr(self, "_destroyed", False):
            # Terminal: a late stage load must not rewire model state.
            return
        if self._transform_model is None:
            return
        # Resolve a held drag against the outgoing wiring first.
        try:
            self.cancel_active_transform_drag(reason="stage_transition")
        except Exception:
            pass
        self._commit_active_camera_pose_if_dirty()
        self._active_camera_path = None
        self._last_authored_camera_signature = None
        self._reset_camera_navigation_state()
        # Drop any previously bound camera selection on the renderer so
        # a fresh stage starts on the default session camera instead of
        # whatever the previous stage's user-selected camera was.
        reset = getattr(self._renderer, "set_active_camera_path", None)
        if callable(reset):
            try:
                reset(None)
            except Exception:
                pass
        self._transform_model.attach_adapters(
            transform_adapter=transform_adapter,
            stage_adapter=stage_adapter,
            undo=undo_manager,
            snap_system=snap_system,
            renderer=self._renderer,
        )
        self._refresh_toolbar_state()

    @staticmethod
    def _normalize_stage_up_axis(up_axis: Any) -> str:
        return "Z" if isinstance(up_axis, str) and up_axis.upper() == "Z" else "Y"

    def _read_stage_up_axis_from_adapter(self, adapter: Any) -> str:
        read_stage_up_axis = getattr(adapter, "read_stage_up_axis", None)
        if not callable(read_stage_up_axis):
            return "Y"
        try:
            return self._normalize_stage_up_axis(read_stage_up_axis())
        except Exception:
            return "Y"

    def _sync_camera_manipulator_up_axis(self) -> None:
        """Keep manipulator metadata aligned with the camera controller."""
        model = getattr(self, "_camera_model", None)
        setter = getattr(model, "set_floats", None)
        if not callable(setter):
            return
        try:
            setter("up_axis", [float(value) for value in self._camera.up_axis])
        except Exception:
            pass

    def apply_stage_up_axis(self, up_axis: Any) -> bool:
        """Apply stage-level up-axis metadata without changing camera target.

        Bound camera poses use :meth:`apply_camera_pose`; this method covers
        stages that have no bound pose and therefore use bbox fallback framing.
        """
        try:
            self._camera.set_up_axis(self._normalize_stage_up_axis(up_axis))
        except Exception:
            return False
        self._sync_camera_manipulator_up_axis()
        return True

    def frame_paths(self, paths: list) -> bool:
        """Frame the camera to enclose the given prim paths.

        Returns ``True`` when real bounds were computed and applied;
        ``False`` when no real bounds were available (empty paths,
        no adapter, no provider, adapter returned ``None``, or adapter
        raised). On the ``False`` path with non-empty ``paths``, the
        camera falls back to a safe default focus
        (``center=(0, 0, 0)``, ``distance=5.0``) so the viewport remains
        usable. Empty ``paths`` returns ``False`` without touching the
        camera at all.

        Adapter exceptions are caught and treated as "no bounds available"
        (matching the pre-Step-17 inline pxr code's blanket ``except``
        guard). This preserves the no-throw contract — a failing adapter
        implementation never breaks the framing loop.

        Special case ``"/"`` is handled inside the adapter
        (:meth:`StageAdapter.compute_world_aabb` iterates the pseudo-root's
        children when given the pseudo-root path); the widget no longer
        needs to know about it.
        """
        if not paths:
            return False
        bounds = None
        if self._stage_adapter_provider is not None:
            adapter = self._stage_adapter_provider()
            if adapter is not None:
                self.apply_stage_up_axis(self._read_stage_up_axis_from_adapter(adapter))
                try:
                    bounds = adapter.compute_world_aabb(paths)
                except Exception:
                    bounds = None
        if bounds is None:
            # Fallback: keep the viewport usable with a safe default
            # focus. Mirrors the pre-Step-17 inline behavior where
            # missing/invalid bounds fell through to the default
            # ``center=(0,0,0), distance=5.0`` focus call.
            self._camera.focus([0.0, 0.0, 0.0], 5.0)
            return False
        (min_x, min_y, min_z), (max_x, max_y, max_z) = bounds
        center = [
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            (min_z + max_z) * 0.5,
        ]
        size = (max_x - min_x, max_y - min_y, max_z - min_z)
        distance = max(float(max(size[0], size[1], size[2])) * 2.0, 0.5)
        self._camera.focus(center, distance)
        return True

    def apply_camera_pose(self, pose: Optional[BoundCameraPose]) -> bool:
        """Apply ``pose`` to the viewport camera.

        Step 16 closes the previous raw-``Usd.Stage`` seam: callers
        (typically :class:`Application`) parse the bound-camera metadata
        through the stage adapter and pass the resulting
        :class:`BoundCameraPose` value object here. The widget no
        longer touches ``Usd.Stage`` for camera metadata.

        Returns ``True`` when a pose was successfully applied; ``False``
        when ``pose`` is ``None`` or when the underlying camera setter
        raised. Callers fall back to :meth:`frame_paths` when this is
        ``False`` so the bbox framing remains the safe default.
        """
        if pose is None:
            return False
        try:
            self._camera.set_pose(
                eye=pose.eye,
                target=pose.target,
                up_axis=pose.up_axis,
                fov_degrees=pose.fov_degrees,
            )
        except Exception:
            return False
        self._sync_camera_manipulator_up_axis()
        return True

    def _camera_author_signature(self, path: str) -> tuple[Any, ...]:
        state = self._camera.state
        return (
            path,
            tuple(round(float(v), 9) for v in state.target),
            round(float(state.distance), 9),
            round(float(state.azimuth), 9),
            round(float(state.elevation), 9),
            tuple(round(float(v), 9) for v in self._camera.up_axis),
            round(float(self._camera.fov_degrees), 9),
        )

    def _camera_navigation_signature(self) -> tuple[Any, ...]:
        return self._camera_author_signature(self._active_camera_path or "")

    def _reset_camera_navigation_state(self) -> None:
        self._camera_navigation_state.reset(self._camera_navigation_signature())

    def _tick_camera_navigation_state(self) -> None:
        self._camera_navigation_state.observe(self._camera_navigation_signature())

    def is_camera_navigation_active(self) -> bool:
        return self._camera_navigation_state.is_active

    def has_dirty_camera_navigation(self) -> bool:
        return self._camera_navigation_state.is_dirty

    def _write_active_camera_pose_from_matrices(
        self,
        path: str,
        view_matrix: Any,
        proj_matrix: Any,
        width: int,
        height: int,
        *,
        undoable: bool = True,
    ) -> bool:
        adapter = self._get_stage_adapter()
        writer = getattr(adapter, "write_camera_pose_from_matrices", None)
        if not callable(writer):
            return False
        try:
            self._committing_active_camera_pose = True
            target = tuple(float(v) for v in self._camera.state.target)
            kwargs: dict[str, Any] = {}
            if self._callable_accepts_keyword(writer, "source"):
                kwargs["source"] = VIEWPORT_CAMERA_POSE_SOURCE
            if self._callable_accepts_keyword(writer, "undoable"):
                kwargs["undoable"] = undoable
            return bool(
                writer(path, view_matrix, proj_matrix, width, height, target, **kwargs)
            )
        except Exception:
            return False
        finally:
            self._committing_active_camera_pose = False

    @staticmethod
    def _callable_accepts_keyword(callable_obj: Any, keyword: str) -> bool:
        try:
            parameters = inspect.signature(callable_obj).parameters
        except (TypeError, ValueError):
            return True
        if keyword in parameters:
            return True
        return any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

    def _commit_active_camera_pose_if_dirty(self, *, undoable: bool = True) -> bool:
        if self._committing_active_camera_pose:
            return False
        path = self._active_camera_path
        if not path or not self._camera_navigation_state.is_dirty:
            return False
        resolution = self._last_resolution
        if resolution is None:
            self._camera_navigation_state.clear_dirty()
            return False
        width, height = resolution
        if width <= 0 or height <= 0:
            self._camera_navigation_state.clear_dirty()
            return False
        view, proj = self._camera.get_matrices(width, height)
        signature = self._camera_author_signature(path)
        accepted = self._write_active_camera_pose_from_matrices(
            path,
            view,
            proj,
            width,
            height,
            undoable=undoable,
        )
        if accepted:
            self._last_authored_camera_signature = signature
        self._camera_navigation_state.clear_dirty()
        return accepted

    @staticmethod
    def _stage_change_path_affects_prim(change_path: Any, prim_path: str) -> bool:
        path = str(change_path or "")
        prim = str(prim_path or "")
        if not path or not prim:
            return False
        if path == prim or path.startswith(prim + "/") or path.startswith(prim + "."):
            return True
        # USD attribute notices use property paths such as
        # ``/World.xformOp:translate``. The active camera's world pose changes
        # when an ancestor xform attribute changes, so compare against the
        # owning prim path too.
        owner = path.split(".", 1)[0]
        return owner == "/" or prim == owner or prim.startswith(owner + "/")

    def _is_self_authored_active_camera_pose_event(self, event: Any) -> bool:
        path = self._active_camera_path
        if not path or not is_viewport_camera_pose_change_event(event):
            return False
        changed = tuple(getattr(event, "changed_paths", ()) or ())
        resynced = tuple(getattr(event, "resynced_paths", ()) or ())
        return any(
            self._stage_change_path_affects_prim(changed_path, path)
            for changed_path in changed + resynced
        )

    def _sync_active_camera_from_stage_change(self, event: Any) -> bool:
        path = self._active_camera_path
        if not path:
            return False
        changed = tuple(getattr(event, "changed_paths", ()) or ())
        resynced = tuple(getattr(event, "resynced_paths", ()) or ())
        if not changed and not resynced:
            return False
        if not any(
            self._stage_change_path_affects_prim(changed_path, path)
            for changed_path in changed + resynced
        ):
            return False
        if self._is_self_authored_active_camera_pose_event(event):
            return False
        adapter = self._get_stage_adapter()
        reader = getattr(adapter, "read_camera_pose", None)
        if not callable(reader):
            return False
        should_reset_navigation = not self._camera_navigation_state.is_active
        if should_reset_navigation:
            self._commit_active_camera_pose_if_dirty()
        try:
            pose = reader(path)
        except Exception:
            return False
        if not self.apply_camera_pose(pose):
            return False
        self._last_authored_camera_signature = self._camera_author_signature(path)
        # External Properties edits arrive while navigation is settled and
        # should become the new baseline. A self-authored camera notice can
        # arrive after the render tick already marked navigation active; do
        # not let that notice erase the active/dirty state Step 4 will use.
        if should_reset_navigation:
            self._reset_camera_navigation_state()
        return True

    def _author_active_camera_pose(
        self,
        view_matrix: Any,
        proj_matrix: Any,
        width: int,
        height: int,
    ) -> bool:
        """Persist active USD camera navigation back to the stage.

        Selecting a USD camera puts the viewport in camera-edit mode: pan,
        zoom, orbit, look, and flight changes must move that camera prim so
        Properties and later camera switches see the edited pose. Minimal
        adapters return ``False`` and keep the free-camera behavior.
        """
        path = self._active_camera_path
        if not path:
            return False
        signature = self._camera_author_signature(path)
        if signature == self._last_authored_camera_signature:
            self._camera_navigation_state.clear_dirty()
            return False
        if self._camera_navigation_state.is_active:
            return False
        accepted = self._write_active_camera_pose_from_matrices(
            path,
            view_matrix,
            proj_matrix,
            width,
            height,
        )
        if accepted:
            self._last_authored_camera_signature = signature
            self._camera_navigation_state.clear_dirty()
        return accepted

    # Camera-physics dt clamps. ``TumbleInertia.tick`` already clamps
    # internally (see ``camera_inertia.py:DT_CLAMP_MIN/MAX``); flight mode
    # has no built-in clamp and would otherwise launch the camera across
    # the scene if the loop ever produces a multi-second tick (debugger
    # pause, GC stall, first-frame clock bug). Mirror tumble's bounds.
    _UPDATE_DT_MIN = 0.001
    _UPDATE_DT_MAX = 0.1

    def update(self, tick_dt: float) -> None:
        """Per-tick wall-clock physics — flight + tumble inertia.

        Runs every outer-loop tick regardless of whether the render gate
        fires this frame. ``tick_dt`` is the time since the previous tick.
        Non-positive values (``None``, ``0.0``, negative) short-circuit
        the whole method: ``FlightModeKeyboard.integrate()`` documents
        non-positive dt as a no-op (camera_flight_keyboard.py:248-252)
        and ``TumbleInertia.tick()`` does the same — there is nothing
        useful for either subsystem to do at a zero or negative interval.

        Positive values are clamped to ``[_UPDATE_DT_MIN, _UPDATE_DT_MAX]``
        before reaching flight integration so a long stall cannot teleport
        the camera. Tumble inertia clamps the same range internally; we
        pass it the original (positive) value so its own bounds remain
        authoritative.
        """
        if self._resolution_sync_is_disposed():
            return
        if tick_dt is None or tick_dt <= 0.0:
            return
        # Flight integration is speed × seconds; clamp before forwarding so
        # a multi-second stall can't propel the camera through the scene.
        if self._flight_keyboard.is_flying:
            dt = max(self._UPDATE_DT_MIN, min(self._UPDATE_DT_MAX, float(tick_dt)))
            self._flight_keyboard.integrate(dt)
        if self._tumble_inertia.is_active:
            self._tumble_inertia.tick(tick_dt)
        self._maybe_request_viewport_resize_effective_recompute()

    def _viewport_mode_resize_needs_effective_recompute(self) -> bool:
        """True when Viewport mode has a new visible frame size to commit."""

        if not self._resolution_state.is_viewport_mode:
            return False
        visible_frame_size = self._visible_viewport_frame_size_for_render()
        if visible_frame_size is None:
            return False
        return visible_frame_size != self._last_viewport_mode_visible_frame_size

    def _fill_viewport_resize_needs_effective_recompute(self) -> bool:
        """True when fixed Fill Viewport has a new visible frame size."""

        if not (
            self._resolution_state.is_fixed_mode
            and self._resolution_state.fill_viewport
        ):
            return False
        visible_frame_size = self._visible_viewport_frame_size_for_render()
        if visible_frame_size is None:
            return False
        return visible_frame_size != self._last_fill_viewport_visible_frame_size

    def _resize_needs_effective_recompute(self) -> bool:
        return (
            self._viewport_mode_resize_needs_effective_recompute()
            or self._fill_viewport_resize_needs_effective_recompute()
        )

    def _maybe_request_viewport_resize_effective_recompute(self) -> bool:
        """Request one Area-3 recompute for resize-sensitive modes."""

        if self._resolution_sync_is_disposed():
            return False
        if not self._resize_needs_effective_recompute():
            return False
        self._request_viewport_resize_render_refresh()
        return True

    def _request_viewport_resize_render_refresh(self) -> None:
        """Coalesce resize-driven renders without writing resolution settings."""

        if self._resolution_sync_is_disposed():
            return
        if self._viewport_resize_render_refresh_pending:
            return
        self._viewport_resize_render_refresh_pending = True

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _render_latest_resize_frame() -> None:
            try:
                await ui.next_frame()
                if self._resolution_sync_is_disposed():
                    return
                if self._resize_needs_effective_recompute():
                    self._render_rate_limited()
            except Exception as exc:
                self._last_render_resolution_apply_error = exc
            finally:
                self._viewport_resize_render_refresh_pending = False

        loop.create_task(_render_latest_resize_frame())

    def _visible_viewport_frame_size_for_render(self) -> tuple[int, int] | None:
        if (
            (
                _env_flag_enabled(AREA3_RENDER_QA_ENV)
                or _env_flag_enabled(AREA3_INTERACTION_QA_ENV)
            )
            and self._resolution_render_qa_frame_size is not None
        ):
            return self._resolution_render_qa_frame_size
        if self._image is None:
            return None
        width = int(self._image.computed_width or 0)
        height = int(self._image.computed_height or 0)
        if width <= 0 or height <= 0:
            return None
        return (width, height)

    def _compute_viewport_mode_effective_resolution(
        self,
        visible_frame_size: tuple[int, int],
    ) -> ViewportModeEffectiveResolution:
        dpi_scale = 1.0
        dpi_available = True
        if self._resolution_state.uses_dpi:
            if (
                (
                    _env_flag_enabled(AREA3_RENDER_QA_ENV)
                    or _env_flag_enabled(AREA3_INTERACTION_QA_ENV)
                )
                and self._resolution_render_qa_dpi_available is not None
            ):
                dpi_available = self._resolution_render_qa_dpi_available
                dpi_scale = self._resolution_render_qa_dpi_scale
            else:
                dpi_available, detected_scale = self._detect_resolution_dpi_scale()
                dpi_scale = detected_scale
        return compute_viewport_mode_effective_resolution_for_state(
            visible_frame_size,
            self._resolution_state,
            dpi_scale=dpi_scale,
            dpi_available=dpi_available,
        )

    def _compute_fixed_mode_effective_resolution(
        self,
        visible_frame_size: tuple[int, int],
    ) -> FixedModeEffectiveResolution:
        dpi_scale = 1.0
        dpi_available = True
        if self._resolution_state.uses_dpi:
            if (
                (
                    _env_flag_enabled(AREA3_RENDER_QA_ENV)
                    or _env_flag_enabled(AREA3_INTERACTION_QA_ENV)
                )
                and self._resolution_render_qa_dpi_available is not None
            ):
                dpi_available = self._resolution_render_qa_dpi_available
                dpi_scale = self._resolution_render_qa_dpi_scale
            else:
                dpi_available, detected_scale = self._detect_resolution_dpi_scale()
                dpi_scale = detected_scale
        return compute_fixed_mode_effective_resolution_for_state(
            self._resolution_state,
            visible_frame_size=visible_frame_size,
            dpi_scale=dpi_scale,
            dpi_available=dpi_available,
        )

    def _commit_resolution_effective_size(
        self,
        effective_size: tuple[int, int],
    ) -> tuple[int, int]:
        safe_effective_size = ensure_safe_renderer_request_size(effective_size)
        if self._resolution_state.effective_size != safe_effective_size:
            self.set_resolution_state(effective_size=safe_effective_size)
        committed_size = self._resolution_state.effective_size
        if committed_size is None:
            return safe_effective_size
        return ensure_safe_renderer_request_size(committed_size)

    def render(self, render_dt: float) -> bool:
        """Per-render path — RTX render, image bridge upload, HUD refresh.

        Returns ``True`` iff a frame was actually rendered. The Application
        only commits the FrameClock on ``True``, so a hidden, zero-size, or
        first-pass-with-no-renderer frame leaves the cadence clock untouched
        and the next tick re-attempts rendering immediately rather than
        waiting out the throttle period.

        ``render_dt`` is the time since the last *committed* render. The FPS
        HUD records it into a one-second rolling average. The first render sees
        ``render_dt == 0.0``; the FPS HUD update is suppressed in that case
        so the user doesn't see a one-frame "inf FPS" or boot-clock-derived
        garbage value.
        """
        if self._resolution_sync_is_disposed():
            self._resolution_render_refresh_pending = False
            self._viewport_resize_render_refresh_pending = False
            return False
        if self._resolution_render_in_progress:
            return False
        resize_render_refresh_was_pending = bool(
            self._viewport_resize_render_refresh_pending
        )
        self._resolution_render_in_progress = True
        try:
            if self._image is None:
                return False
            if not self._image.visible:
                return False
            visible_frame_size = self._visible_viewport_frame_size_for_render()
            if visible_frame_size is None:
                return False
            if self._renderer is None:
                return False
            if self._resolution_state.is_viewport_mode:
                effective = self._compute_viewport_mode_effective_resolution(
                    visible_frame_size
                )
                self._last_viewport_mode_effective_resolution = effective
                self._last_viewport_mode_visible_frame_size = visible_frame_size
                self._last_fixed_mode_effective_resolution = None
                self._last_fill_viewport_visible_frame_size = None
                w, h = self._commit_resolution_effective_size(
                    effective.effective_size
                )
                self._viewport_resize_render_refresh_pending = False
            elif self._resolution_state.is_fixed_mode:
                effective = self._compute_fixed_mode_effective_resolution(
                    visible_frame_size
                )
                self._last_fixed_mode_effective_resolution = effective
                self._last_viewport_mode_effective_resolution = None
                self._last_viewport_mode_visible_frame_size = None
                self._last_fill_viewport_visible_frame_size = (
                    visible_frame_size if self._resolution_state.fill_viewport else None
                )
                w, h = self._commit_resolution_effective_size(
                    effective.effective_size
                )
                self._viewport_resize_render_refresh_pending = False
            else:
                frame_width, frame_height = visible_frame_size
                w = max(self.MIN_RENDER_WIDTH, min(self.MAX_RENDER_WIDTH, frame_width))
                h = max(
                    self.MIN_RENDER_HEIGHT,
                    min(self.MAX_RENDER_HEIGHT, frame_height),
                )
                self._last_viewport_mode_effective_resolution = None
                self._last_viewport_mode_visible_frame_size = None
                self._last_fixed_mode_effective_resolution = None
                self._last_fill_viewport_visible_frame_size = None
                self._viewport_resize_render_refresh_pending = False
            w, h = ensure_safe_renderer_request_size((w, h))
            self._last_resolution = (w, h)
            self._refresh_hud()
            self._refresh_resolution_render_qa_window()
            view, proj = self._camera.get_matrices(w, h)
            self._tick_camera_navigation_state()
            self._author_active_camera_pose(view, proj, w, h)
            frame = self._renderer.render_frame(  # type: ignore[union-attr]
                w,
                h,
                view,
                proj,
            )
            self._last_image_frame = frame
            self._bridge.update(frame)
            self._retry_selection_highlight_after_render()
            # Update the FPS HUD after the render succeeds. The rolling one-second
            # window keeps short stalls from dominating the visible value.
            self._record_fps_sample(render_dt)
            self._refresh_hud()
            # Sync the scene-view overlay's camera so gizmo geometry drawn in
            # world coordinates (translate handles, pick markers, etc.) aligns
            # with the rendered prims. ``sc.SceneView.view`` / ``projection``
            # expect a flat 16-float matrix with translation in the *last row*
            # (positions 12/13/14), but :func:`CameraController._look_at`
            # stores it in the last *column* (indices 3/7/11). Transpose
            # before flattening so the column-convention matrix matches the
            # row-convention binding.
            if self._scene_view is not None:
                try:
                    # Under the renderer's depth-one LdrColor overlap the
                    # image on screen is one frame older than the camera
                    # just submitted. The adapter exposes the PRESENTED
                    # frame's complete camera state; overlays must use it so
                    # gizmo/outline geometry projects onto the visible
                    # pixels, not the in-flight frame's. When absent (the
                    # synchronous path), the just-submitted matrices are the
                    # presented matrices, so fall back to them.
                    presented = getattr(
                        self._renderer, "presented_camera_snapshot", None
                    )
                    if presented is not None:
                        overlay_view = presented.view
                        overlay_source_proj = presented.projection
                        overlay_render_size = presented.size
                    else:
                        overlay_view = view
                        overlay_source_proj = proj
                        overlay_render_size = (w, h)
                    overlay_frame_size = self._get_raw_viewport_frame_size()
                    overlay_proj = apply_aspect_fit_projection_transform(
                        overlay_source_proj,
                        overlay_frame_size,
                        overlay_render_size,
                    )
                    view_flat = (
                        overlay_view.T.flatten().tolist()
                        if hasattr(overlay_view, "T")
                        else list(overlay_view)
                    )
                    proj_flat = (
                        overlay_proj.T.flatten().tolist()
                        if hasattr(overlay_proj, "T")
                        else list(overlay_proj)
                    )
                    self._scene_view.view = view_flat
                    self._scene_view.projection = proj_flat
                except Exception:
                    pass
            self._viewport_hooks.update_frame(
                ViewportFrameContext(
                    owner=self,
                    width=w,
                    height=h,
                    render_dt=render_dt,
                    view_matrix=view,
                    projection_matrix=proj,
                    image_frame=frame,
                    image_bridge=self._bridge,
                    scene_view=self._scene_view,
                )
            )
            # Drive the gizmo's position & scale via direct ``sc.Transform``
            # attribute updates — same "build-once-update-per-frame" pattern
            # Kit uses in ``omni.kit.manipulator.transform.TransformManipulator.
            # _update_from_model``. Every frame the manipulator reads the
            # current pivot + camera-distance scale off our callables and
            # writes them into its persistent Transform nodes, so selection
            # changes show up on the very next draw without any
            # ``invalidate()`` race. Cheap: two matrix writes when anything
            # actually changed, no-op otherwise.
            if self._transform_manipulator is not None:
                try:
                    self._transform_manipulator.refresh_transform()
                except Exception:
                    pass
            # Kept for the "camera moved enough → invalidate" fallback path
            # that still forces a full rebuild when the gizmo size needs a
            # major step. With ``refresh_transform`` in place this is
            # mostly a no-op; retained as defence in depth.
            self._maybe_invalidate_gizmo_for_scale()
            if resize_render_refresh_was_pending:
                self._request_settings_menu_reshow()
            return True
        finally:
            self._resolution_render_in_progress = False

    def _on_frame(self, dt: float) -> None:
        """Backward-compatible single-call entry — splits into update + render.

        Production: :class:`Application` calls :meth:`update` and
        :meth:`render` separately under control of its own
        :class:`FrameClock`. This shim is retained for legacy QA scripts
        and pre-FrameClock unit tests that still drive the viewport with a
        single ``dt``. It applies the simple "skip render if dt below the
        configured cap period" gate, so it honors the same Kit-compatible
        ``rateLimitFrequency`` setting as the production cadence path.
        """
        target_dt = 1.0 / self._configured_max_fps()
        self.update(dt)
        if self._image is None or not self._image.visible:
            return
        if dt < target_dt:
            return
        self.render(dt)

    def _is_gizmo_drag_active(self) -> bool:
        """True iff a translate / rotate / scale drag is currently in flight.

        Each gesture exposes an ``is_active`` flag it sets between
        ``on_began`` and ``on_ended``. If any of them is active we must
        not invalidate the manipulator — doing so swaps the shape the
        gesture is bound to and the drag dies silently.
        """
        mani = self._transform_manipulator
        if mani is None:
            return False
        for group in (
            getattr(mani, "_translate_drags", None) or (),
            getattr(mani, "_rotate_drags", None) or (),
            getattr(mani, "_scale_drags", None) or (),
        ):
            for g in group:
                if getattr(g, "is_active", False):
                    return True
        uniform = getattr(mani, "_uniform_scale_drag", None)
        if uniform is not None and getattr(uniform, "is_active", False):
            return True
        return False

    def _maybe_invalidate_gizmo_for_scale(self) -> None:
        """Invalidate the gizmo iff camera-driven size changed non-trivially.

        Compares the current ``_get_gizmo_world_scale`` against the
        value at the last rebuild; only invalidates when the relative
        change is ≥ 10 % or the baseline is zero (first build). Skipped
        while a drag is active — see :meth:`_is_gizmo_drag_active`.
        """
        mani = self._transform_manipulator
        if mani is None or not mani.has_selection():
            self._last_gizmo_scale = 0.0
            return
        if self._is_gizmo_drag_active():
            return
        try:
            current = float(self._get_gizmo_world_scale())
        except Exception:
            return
        if current <= 0.0:
            return
        last = self._last_gizmo_scale
        if last <= 0.0 or abs(current - last) / max(last, 1e-6) >= 0.10:
            try:
                mani.invalidate()
            except Exception:
                return
            self._last_gizmo_scale = current

    def update_prim_count(self, count: int) -> None:
        """Store the current stage prim count.

        Step 18 removes the viewport's old prim-count HUD line in favour of
        scene/selection data. The value is still stored because the
        application continues to notify the viewport after stage resyncs.
        """
        self._prim_count = int(count)

    def set_scene_name(self, name: Optional[str]) -> None:
        """Set the viewport HUD scene name from the active stage title."""
        self._scene_name = name or None
        self._refresh_hud()

    def notify_stage_changed(self, event: Any) -> None:
        """Forward a stage ``ChangeEvent`` to the active renderer if it can handle it.

        Called by ``Application._on_stage_changed`` whenever the USD stage adapter
        flushes a batch of changes (Property Inspector edits, undo/redo, external
        stage mutations). The renderer decides what to re-read; the viewport
        routes the event and also invalidates scene-view overlays whose geometry
        depends on selected-prim state (the transform gizmo pivot) so a
        Property-panel translate / scale / radius edit shows up in the viewport
        without requiring a re-click. Active USD camera changes are also re-read
        through the stage adapter so Properties edits to the selected camera
        immediately update the viewport's controller pose.
        """
        if not self._is_self_authored_active_camera_pose_event(event):
            self._sync_active_camera_from_stage_change(event)
        if self._renderer is not None:
            handler = getattr(self._renderer, "notify_stage_changed", None)
            if handler is not None:
                try:
                    handler(event)
                except Exception:
                    pass
        # Invalidate outline + gizmo whenever any selected prim (or its
        # subtree) is part of the change. We compare path prefixes so a
        # parent-level xform edit pushes a refresh through to children that
        # inherit it. An empty selection short-circuits — there's nothing
        # to refresh.
        selected = self._get_outline_selection()
        if not selected:
            return
        changed = tuple(getattr(event, "changed_paths", ()) or ())
        resynced = tuple(getattr(event, "resynced_paths", ()) or ())
        if not changed and not resynced:
            return
        affected = False
        for path in list(changed) + list(resynced):
            for sel in selected:
                # Matches the prim path itself, a descendant prim path
                # (``/Foo`` → ``/Foo/Bar``), an ancestor path (parent xform
                # edits propagate down), and property paths
                # (``/Foo.xformOp:translate`` is how USD reports attribute
                # changes — those never match ``startswith(sel + '/')``).
                if (
                    path == sel
                    or path.startswith(sel + "/")
                    or path.startswith(sel + ".")
                    or sel.startswith(path + "/")
                ):
                    affected = True
                    break
            if affected:
                break
        if not affected:
            return
        if self._transform_manipulator is not None:
            try:
                self._transform_manipulator.invalidate()
            except Exception:
                pass

    def _resolve_settings(self) -> Any:
        """Return the live :class:`Settings` instance, or ``None``.

        Step 11.3: two-stage explicit lookup. First check the
        services object the widget was constructed with for an
        attached ``settings`` attribute (legacy test fakes that still
        set ``services=SimpleNamespace(settings=...)`` rely on this),
        then fall back to the
        :class:`ovui_widgets.common.settings.Settings` singleton wired by
        :meth:`Application.__init__` in Step 10. Returns ``None`` if
        neither path supplies a live Settings (headless / mock paths).
        """
        services_settings = getattr(self._services, "settings", None)
        if services_settings is not None:
            return services_settings
        from ovui_widgets.common.settings import Settings
        return Settings._instance

    @staticmethod
    def _enable_renderer_frame_overlap(renderer: Optional[RendererAdapter]) -> None:
        """Opt a freshly attached renderer into frame-loop overlap, if able."""
        setter = getattr(renderer, "set_ldr_overlap_enabled", None)
        if callable(setter):
            try:
                setter(True)
            except Exception:
                # the synchronous path remains fully functional
                pass

    def _attach_zero_copy_state(
        self,
        renderer: Optional[RendererAdapter],
        *,
        adopt_existing: bool = False,
    ) -> None:
        """Attach this viewport's zero-copy state to ``renderer`` when possible."""
        if renderer is None:
            return
        if adopt_existing:
            existing = getattr(renderer, "_zero_copy_state", None)
            if existing is not None:
                self._zero_copy_state = existing
                return

        setter = getattr(renderer, "set_zero_copy_state", None)
        if callable(setter):
            setter(self._zero_copy_state)
            return

        try:
            renderer._zero_copy_state = self._zero_copy_state
        except AttributeError:
            pass

    @property
    def lifecycle_state(self) -> str:
        """"usable"/"unavailable"/"destroyed", derived from the token
        and actual ownership, never from requested work."""
        if getattr(self, "_destroyed", False):
            return "destroyed"
        generation = getattr(self, "_live_generation", None)
        if generation is not None and generation.operational(self):
            return "usable"
        return "unavailable"

    @property
    def unresolved_predecessor(self) -> Optional[Any]:
        """The single viewport-owned renderer with unresolved shutdown."""
        return getattr(self, "_unresolved_predecessor", None)

    def _retry_unresolved_predecessor(self, cleanup: _LifecycleCleanup) -> None:
        """Retry the owned predecessor's shutdown at a lifecycle point."""
        predecessor = getattr(self, "_unresolved_predecessor", None)
        if predecessor is not None and cleanup.run(
            "unresolved predecessor shutdown retry",
            getattr(predecessor, "shutdown", None),
        ):
            self._unresolved_predecessor = None

    def _reapply_selection_highlight(
        self, renderer: Any, cleanup: _LifecycleCleanup
    ) -> None:
        if self._bus is None or renderer is None:
            return

        def _reapply() -> None:
            snap = self._bus.get_snapshot()
            renderer.set_selection_highlight(
                self._resolve_selection_highlight_paths(
                    snap.paths() if snap else []))

        cleanup.run("selection highlight reapply", _reapply)

    def _refuse_renderer(
        self, renderer: Any, cleanup: _LifecycleCleanup, label: str
    ) -> None:
        """Courtesy-shutdown a refused/rejected incoming; adopt it into
        the debt slot only when the slot is free and shutdown fails."""
        if renderer is None:
            return
        if (not cleanup.run(label, getattr(renderer, "shutdown", None))
                and getattr(self, "_unresolved_predecessor", None) is None):
            self._unresolved_predecessor = renderer

    def _detach_interaction_resources(self, cleanup: _LifecycleCleanup) -> None:
        """Detach interaction resources; revoking the token makes every
        retained callback inert even when a destructor fails."""
        generation = getattr(self, "_live_generation", None)
        if generation is not None:
            generation.alive = False
        cleanup.run(
            "scene view destroy",
            getattr(getattr(self, "_scene_view", None), "destroy", None))
        cleanup.run(
            "tool registry destroy",
            getattr(getattr(self, "_tool_registry", None), "destroy", None))
        self._scene_view = None
        self._camera_manipulator = None
        self._transform_manipulator = None
        self._pick_manager = None
        self._tool_registry = None

    def _detach_model_renderer(self, cleanup: _LifecycleCleanup) -> None:
        """Detach the model's renderer; a dead reference never survives."""
        model = getattr(self, "_transform_model", None)
        if model is None:
            return
        if not cleanup.run(
            "model renderer detach", lambda: model.set_renderer(None)
        ):
            try:
                model._renderer = None
            except BaseException:
                pass

    def set_renderer(self, renderer: Optional[RendererAdapter]) -> bool:
        """Swap or clear the active renderer. ``True`` iff the request
        is now the published surface renderer (or a clear completed) —
        ``False`` leaves unresolved incoming ownership with the caller."""
        cleanup = _LifecycleCleanup()
        try:
            if getattr(self, "_destroyed", False):
                # Terminal: never adopt, retain nothing.
                if renderer is not None:
                    cleanup.run(
                        "courtesy shutdown of renderer offered after destroy",
                        getattr(renderer, "shutdown", None),
                    )
                return False
            old = self._renderer
            if old is renderer:
                self._reapply_selection_highlight(renderer, cleanup)
                cleanup.run(
                    "resolution availability refresh",
                    self._refresh_resolution_availability,
                )
                return True
            # Resolve the drag, then invalidate the outgoing generation
            # BEFORE native shutdown can re-enter old callbacks.
            cleanup.run(
                "drag cancellation during renderer replacement",
                lambda: self.cancel_active_transform_drag(
                    reason="renderer_transition"))
            self._detach_interaction_resources(cleanup)
            # A renderer known to have been shut down is never republished.
            was_unresolved = (
                renderer is not None and renderer
                is getattr(self, "_unresolved_predecessor", None))
            self._retry_unresolved_predecessor(cleanup)
            if (old is not None
                    and getattr(self, "_unresolved_predecessor", None) is None):
                if not cleanup.run("outgoing renderer shutdown",
                                   getattr(old, "shutdown", None)):
                    self._unresolved_predecessor = old
            published = renderer
            if was_unresolved:
                published = None  # shut down (or still unresolved): refuse
            if getattr(self, "_unresolved_predecessor", None) is not None:
                # Possibly-live predecessor: refuse the incoming.
                self._refuse_renderer(published, cleanup,
                                      "courtesy shutdown of refused renderer")
                published = None
            if published is not None:
                cleanup.run("zero-copy state attach",
                            lambda: self._attach_zero_copy_state(published))
                cleanup.run(
                    "frame-overlap opt-in",
                    lambda: self._enable_renderer_frame_overlap(published))
            # Publication: model first, surface second.
            model = getattr(self, "_transform_model", None)
            if model is not None:
                if not cleanup.run("model renderer publication",
                                   lambda: model.set_renderer(published)):
                    rejected = published
                    published = None
                    self._detach_model_renderer(cleanup)
                    self._refuse_renderer(rejected, cleanup,
                                          "courtesy shutdown of rejected renderer")
            self._renderer = published
            cleanup.run("fps sample reset", self._reset_fps_samples)
            if hasattr(self, "_scene_value_label"):
                cleanup.run("hud refresh", self._refresh_hud)
            self._active_render_product_path = None
            # Request the deferred rebuild for the published generation.
            if getattr(self, "_image", None) is not None:
                window = getattr(self, "_window", None)
                rebuild = getattr(getattr(window, "frame", None), "rebuild", None)
                if window is not None and not cleanup.run(
                    "ui rebuild request", rebuild
                ):
                    if published is not None:
                        if not cleanup.run(
                            "successor shutdown after rebuild failure",
                            getattr(published, "shutdown", None),
                        ) and getattr(self, "_unresolved_predecessor", None) is None:
                            self._unresolved_predecessor = published
                        published = None
                        self._renderer = None
                        self._detach_model_renderer(cleanup)
            self._reapply_selection_highlight(published, cleanup)
            cleanup.run(
                "resolution availability refresh",
                self._refresh_resolution_availability,
            )
            return self._renderer is renderer
        finally:
            cleanup.report("ViewportWidget.set_renderer")

    def _destroy_surface_resources(self) -> None:
        """Tear down to a terminal state. Every step runs through the
        accumulator (absorbs ``BaseException``); ``destroyed`` is set only
        after all safety work.  An unresolved renderer predecessor re-raises
        its first exact shutdown throwable so the parent retains this surface
        as the retry owner.  Other interrupt-class conditions also re-raise.
        Idempotent."""
        cleanup = _LifecycleCleanup()
        try:
            # Resolve any drag before resources go away.
            cleanup.run(
                "drag cancellation during teardown",
                lambda: self.cancel_active_transform_drag(reason="teardown"))
            # No dead renderer reference may survive teardown.
            self._detach_model_renderer(cleanup)
            renderer = getattr(self, "_renderer", None)
            self._renderer = None
            if renderer is not None:
                if not cleanup.run(
                        "renderer shutdown during teardown",
                        getattr(renderer, "shutdown", None)):
                    if getattr(self, "_unresolved_predecessor", None) is None:
                        self._unresolved_predecessor = renderer
            else:
                # A repeated destroy is the later, explicit retry point.  Do
                # not retry a just-failed renderer again in the same attempt.
                self._retry_unresolved_predecessor(cleanup)
            cleanup.run(
                "camera pose commit",
                lambda: self._commit_active_camera_pose_if_dirty(
                    undoable=False))

            def _cancel_bus_sub() -> None:
                if self._bus_sub:
                    self._bus_sub.cancel()
                    self._bus_sub = None

            cleanup.run("selection bus unsubscribe", _cancel_bus_sub)
            # Destroy AND neutralize interaction resources.
            self._detach_interaction_resources(cleanup)
            cleanup.run(
                "resolution availability release",
                lambda: self._refresh_resolution_availability(
                    owner_alive=False))
            for label, step in (
                ("resolution availability observers", self._dispose_resolution_availability_observers),
                ("resolution state observers", self._dispose_resolution_state_observers),
                ("viewport identity release", self._release_viewport_identity),
                ("camera menu destroy", self._destroy_camera_menu),
                ("resolution settings schema qa window", self._destroy_resolution_settings_schema_qa_window),
                ("resolution settings notification qa window", self._destroy_resolution_settings_notification_qa_window),
                ("resolution catalog qa window", self._destroy_resolution_catalog_qa_window),
                ("resolution menu failure qa window", self._destroy_resolution_menu_failure_qa_window),
                ("resolution missing icon qa window", self._destroy_resolution_missing_icon_qa_window),
                ("resolution ovui-only qa window", self._destroy_resolution_ovui_only_qa_window),
                ("resolution render qa window", self._destroy_resolution_render_qa_window),
                ("resolution sync pending work", self._cancel_resolution_sync_pending_work),
                ("resolution settings subscription", self._destroy_resolution_settings_subscription),
                ("resolution toolbar host attachment", self._dispose_resolution_toolbar_host_attachment),
                ("pre-tools toolbar hooks", self._pre_tools_toolbar_hooks.clear),
                ("toolbar hooks", self._toolbar_hooks.clear),
                ("viewport hooks", self._viewport_hooks.clear),
            ):
                cleanup.run(label, step)
        finally:
            # Terminal only after all safety work has been attempted.
            self._destroyed = True
            cleanup.report("ViewportWidget.teardown")
        # A possibly-live renderer must remain owned by this surface and the
        # parent must observe refusal; otherwise Application could discard the
        # surface (and its sole retry capability) after an apparent success.
        if getattr(self, "_unresolved_predecessor", None) is not None:
            for label, exc in cleanup.failures:
                if "shutdown" in label:
                    raise exc
            raise RuntimeError("renderer shutdown remains unresolved")
        # Re-raise other interrupt-class conditions once terminal safety holds.
        for _label, exc in cleanup.failures:
            if not isinstance(exc, Exception):
                raise exc

    def destroy(self) -> None:
        """Tear down an embeddable viewport surface."""

        self._destroy_surface_resources()


class ViewportWidget(ViewportSurface, ManagedWindow):
    """Desktop viewport panel wrapping :class:`ViewportSurface` in a window."""

    def __init__(
        self,
        services: Any = None,
        renderer: Optional[RendererAdapter] = None,
        bus: Any = None,
        on_drop_fn: Optional[Callable[[Any], None]] = None,
        stage_adapter_provider: Optional[Callable[[], Any]] = None,
        chrome_options: Optional[ViewportChromeOptions | dict[str, Any]] = None,
        window_kwargs: Optional[dict[str, Any]] = None,
        viewport_id: Optional[str] = None,
    ) -> None:
        ViewportSurface.__init__(
            self,
            services=services,
            renderer=renderer,
            bus=bus,
            on_drop_fn=on_drop_fn,
            stage_adapter_provider=stage_adapter_provider,
            chrome_options=chrome_options,
            viewport_id=viewport_id,
        )
        ManagedWindow.__init__(
            self,
            _viewport_window_title(self._viewport_id),
            width=800,
            height=600,
            **(window_kwargs or {}),
        )
        # Content-Browser Step 40 — per-window drop handler. Wires the
        # viewport's :class:`ui.Window` to a shim that delegates back to
        # :meth:`Application._on_drop` with ``target="viewport"`` so a
        # ``.usd`` dragged from the content browser opens as the active
        # stage (the content browser behavior). ``hasattr`` guards
        # ovui test builds that expose :class:`ui.Window` without
        # :meth:`set_drop_fn`.
        if self._window is not None and hasattr(self._window, "set_drop_fn"):
            self._window.set_drop_fn(self._on_drop)

    def destroy(self) -> None:
        """Tear down the viewport and its desktop window.

        ``ManagedWindow.destroy()`` runs in a ``finally`` so the underlying
        UI window is always released.  A renderer shutdown refusal still
        propagates after that UI cleanup, allowing the parent application to
        retain this object and retry its unresolved predecessor.
        """

        try:
            self._destroy_surface_resources()
        finally:
            ManagedWindow.destroy(self)


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovui_widgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_TOOLBAR_ICON_PROVIDERS)
