# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Color3f / Color4f builder functions for :class:`WidgetBuilderTable`.

Step 3.4 of the property inspector implementation (property attribute builder behavior). USD colour attributes render
as an R/G/B(/A) vector row plus a small live swatch preview rectangle.
Clicking the swatch is a no-op in 3.4 — the colour picker modal lands
in a later phase.

Type-name coverage:

* ``color3f`` / ``color3d`` → :class:`Color3fAttributeRow`
  (3-channel R/G/B vector + swatch)
* ``color4f`` / ``color4d`` → :class:`Color4fAttributeRow`
  (4-channel R/G/B/A vector + swatch)

Step 3.1 previously registered ``color3f`` against the plain
``Vec3FloatAttributeRow`` (no swatch); Step 3.4 removes ``color3f`` from
``builders/vec.py::_VEC3_TYPE_NAMES`` and re-registers it here.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.attribute_row import (
    Color3fAttributeRow,
    Color4fAttributeRow,
)
from ovui_widgets.property.builders.builder_table import WidgetBuilderTable


def build_color3(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Color3fAttributeRow:
    """Build a ``Color3fAttributeRow`` (label + 3× FloatDrag + swatch)."""
    return Color3fAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_color4(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Color4fAttributeRow:
    """Build a ``Color4fAttributeRow`` (label + 4× FloatDrag + swatch)."""
    return Color4fAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


WidgetBuilderTable.register("color3f", build_color3)
WidgetBuilderTable.register("color3d", build_color3)
WidgetBuilderTable.register("color4f", build_color4)
WidgetBuilderTable.register("color4d", build_color4)
