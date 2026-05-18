# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""IntVec2 / IntVec3 / IntVec4 builder functions for :class:`WidgetBuilderTable`.

Step 3.2 of the property inspector implementation. Parallels ``builders/vec.py`` but for USD
integer vector types (``int2``, ``int3``, ``int4``) — each builder wraps
the corresponding subclass of :class:`_VecIntRow` in
``ovwidgets.property/attribute_row.py`` and registers it for the USD type
strings property attribute builder behavior lists.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.property.attribute_row import (
    Vec2IntAttributeRow,
    Vec3IntAttributeRow,
    Vec4IntAttributeRow,
)
from ovwidgets.property.builders.builder_table import WidgetBuilderTable


def build_ivec2(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Vec2IntAttributeRow:
    """Build a ``Vec2IntAttributeRow`` (label + 2× IntDrag, X/Y)."""
    return Vec2IntAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_ivec3(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Vec3IntAttributeRow:
    """Build a ``Vec3IntAttributeRow`` (label + 3× IntDrag, X/Y/Z)."""
    return Vec3IntAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_ivec4(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Vec4IntAttributeRow:
    """Build a ``Vec4IntAttributeRow`` (label + 4× IntDrag, X/Y/Z/W)."""
    return Vec4IntAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


WidgetBuilderTable.register("int2", build_ivec2)
WidgetBuilderTable.register("int3", build_ivec3)
WidgetBuilderTable.register("int4", build_ivec4)
