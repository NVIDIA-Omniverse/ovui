# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Abstract UI data-adapter contracts (no runtime dependencies)."""

from ovui_data_adapters.common._bound_camera_pose import BoundCameraPose
from ovui_data_adapters.common._command import Command
from ovui_data_adapters.common._gpu_frame import (
    _STANDALONE_NOOP_MARKER,
    GpuFrame,
    ZeroCopyState,
    _Mode,
)
from ovui_data_adapters.common._subscription import SubscriptionProtocol
from ovui_data_adapters.common._undo_manager import UndoManagerProtocol
from ovui_data_adapters.common.adapters import (
    _DEFAULT_TYPE_CATEGORY_MAP,
    AABB,
    AdapterItem,
    AttributeMetadata,
    BadgeFlags,
    BoundingBox,
    ChangeEvent,
    ChangeEventType,
    ContextManager,
    GpuFrameHandle,
    ImageProvider,
    ItemFlags,
    LayerEvent,
    LayerEventType,
    LayerHandle,
    LayerSnapshot,
    LayerStackAdapter,
    Matrix4d,
    PrimSpecDescriptor,
    PrimSpecifier,
    PropertyAdapter,
    RendererAdapter,
    ReparentPosition,
    SelectionAdapter,
    StageAdapter,
    StageChoice,
    TransformAdapter,
    VIEWPORT_CAMERA_POSE_SOURCE,
    Vec3f,
    VisibilityState,
    is_camera_property_only_info_change,
    is_viewport_camera_pose_change_event,
)

__all__ = [
    # adapter ABCs
    "LayerStackAdapter",
    "PropertyAdapter",
    "RendererAdapter",
    "SelectionAdapter",
    "StageAdapter",
    "TransformAdapter",
    # enums / flags
    "BadgeFlags",
    "ChangeEventType",
    "ItemFlags",
    "LayerEventType",
    "PrimSpecifier",
    "ReparentPosition",
    "VisibilityState",
    # dataclasses
    "AttributeMetadata",
    "BoundCameraPose",
    "ChangeEvent",
    "LayerEvent",
    "LayerHandle",
    "LayerSnapshot",
    "PrimSpecDescriptor",
    "StageChoice",
    "VIEWPORT_CAMERA_POSE_SOURCE",
    # opaque type aliases
    "AABB",
    "AdapterItem",
    "BoundingBox",
    "ContextManager",
    "GpuFrameHandle",
    "ImageProvider",
    "Matrix4d",
    "Vec3f",
    # protocols and command surface (Steps 2/3)
    "Command",
    "SubscriptionProtocol",
    "UndoManagerProtocol",
    # zero-copy / GPU frame contract (Step 4)
    "GpuFrame",
    "ZeroCopyState",
    "_Mode",
    "_STANDALONE_NOOP_MARKER",
    "is_camera_property_only_info_change",
    "is_viewport_camera_pose_change_event",
    # private lookup table — explicit so dotted access continues to work
    "_DEFAULT_TYPE_CATEGORY_MAP",
]
