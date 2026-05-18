# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovwidgets.viewport: 3D viewport widget package."""

from ovwidgets.viewport.camera_controller import CameraController, CameraState
from ovwidgets.viewport.camera_flight_keyboard import (
    DEFAULT_BASE_SPEED as FLIGHT_DEFAULT_BASE_SPEED,
)
from ovwidgets.viewport.camera_flight_keyboard import (
    FLY_SPEED_SETTING,
    FlightModeKeyboard,
)
from ovwidgets.viewport.camera_gesture import (
    LookGesture,
    PanGesture,
    TumbleGesture,
    ZoomScrollGesture,
)
from ovwidgets.viewport.camera_manipulator import (
    DEFAULT_INERTIA_SECONDS,
    CameraManipulator,
    CameraManipulatorModel,
)
from ovwidgets.viewport.image_bridge import ImageBridge
from ovwidgets.viewport.manipulator_registry import (
    ACTIVE_TOOL_SETTING,
    ManipulatorRegistry,
    ToolRegistry,
)
from ovwidgets.viewport.pick_gesture import PICK_THRESHOLD_PX, PickGesture, PickRectGesture
from ovwidgets.viewport.prim_transform_model import PrimTransformModel, _apply_delta
from ovwidgets.viewport.transform_manipulator import (
    GIZMO_SIZE_SCALE,
    TOOL_ROTATE,
    TOOL_SCALE,
    TOOL_TRANSLATE,
    VALID_TOOLS,
    TransformManipulator,
)
from ovwidgets.viewport.translate_gizmo import (
    CONE_TIP_RADIUS,
    HIGHLIGHT_COLOR_X,
    HIGHLIGHT_COLOR_Y,
    HIGHLIGHT_COLOR_Z,
    SHAFT_LENGTH,
    HighlightGesture,
    PrimTranslateChangedGesture,
    TranslateGizmoHandles,
    build_translate_gizmo,
)
from ovwidgets.viewport.viewport_widget import ViewportWidget

__all__ = [
    "ACTIVE_TOOL_SETTING",
    "CONE_TIP_RADIUS",
    "CameraController",
    "CameraManipulator",
    "CameraManipulatorModel",
    "ManipulatorRegistry",
    "CameraState",
    "DEFAULT_INERTIA_SECONDS",
    "FLIGHT_DEFAULT_BASE_SPEED",
    "FLY_SPEED_SETTING",
    "FlightModeKeyboard",
    "GIZMO_SIZE_SCALE",
    "HIGHLIGHT_COLOR_X",
    "HIGHLIGHT_COLOR_Y",
    "HIGHLIGHT_COLOR_Z",
    "HighlightGesture",
    "ImageBridge",
    "LookGesture",
    "PanGesture",
    "PickGesture",
    "PickRectGesture",
    "PICK_THRESHOLD_PX",
    "PrimTransformModel",
    "PrimTranslateChangedGesture",
    "SHAFT_LENGTH",
    "TOOL_ROTATE",
    "TOOL_SCALE",
    "TOOL_TRANSLATE",
    "ToolRegistry",
    "TransformManipulator",
    "TranslateGizmoHandles",
    "TumbleGesture",
    "VALID_TOOLS",
    "_apply_delta",
    "build_translate_gizmo",
    "ViewportWidget",
    "ZoomScrollGesture",
]
