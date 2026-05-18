# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Vec2 / Vec3 / Vec4 builder functions for :class:`WidgetBuilderTable`.

Step 3.1 of the property inspector implementation. Replaces the earlier ``builders/vec3.py``
with a single module covering all three vector dimensions. Each builder
wraps the corresponding row subclass of :class:`_VecFloatRow` in
``ovwidgets.property/attribute_row.py`` and registers it for the USD type
strings property attribute builder behavior lists.

Step 3.4 moved ``color3f`` / ``color3d`` / ``color4f`` / ``color4d`` out
of this module into :mod:`ovwidgets.property.builders.color`, where a colour
swatch is rendered alongside the vector row.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.property.attribute_row import (
    Vec2FloatAttributeRow,
    Vec3FloatAttributeRow,
    Vec4FloatAttributeRow,
)
from ovwidgets.property.builders.builder_table import WidgetBuilderTable

_VEC2_TYPE_NAMES = (
    "half2",
    "float2",
    "double2",
)

_VEC3_TYPE_NAMES = (
    "float3",
    "double3",
    "normal3f",
    "point3f",
    "vector3f",
)

_VEC4_TYPE_NAMES = (
    "half4",
    "float4",
    "double4",
)


def build_vec2(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Vec2FloatAttributeRow:
    """Build a ``Vec2FloatAttributeRow`` (label + 2× FloatDrag, X/Y)."""
    return Vec2FloatAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_vec3(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Vec3FloatAttributeRow:
    """Build a ``Vec3FloatAttributeRow`` (label + 3× FloatDrag, X/Y/Z)."""
    return Vec3FloatAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_vec4(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Vec4FloatAttributeRow:
    """Build a ``Vec4FloatAttributeRow`` (label + 4× FloatDrag, X/Y/Z/W)."""
    return Vec4FloatAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


for _type_name in _VEC2_TYPE_NAMES:
    WidgetBuilderTable.register(_type_name, build_vec2)
for _type_name in _VEC3_TYPE_NAMES:
    WidgetBuilderTable.register(_type_name, build_vec3)
for _type_name in _VEC4_TYPE_NAMES:
    WidgetBuilderTable.register(_type_name, build_vec4)
del _type_name
