# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Array builder for :class:`WidgetBuilderTable`.

Step 3.8 of the property inspector implementation (property attribute builder behavior, the property inspector behavior).
USD array-typed attributes (``float[]``, ``token[]``, ``float3[]``, …)
render as a label + read-only :class:`omni.ui.StringField`. The StringField
value is either a full tuple repr (small arrays, ``metadata.is_big_array =
False``) or ``"[N items]"`` (big arrays, ``metadata.is_big_array = True``).
An interactive array editor (Kit's ``SdfAssetPathDelegate`` TreeView, §9.6)
lands in a later phase — Step 3.8 is display-only.

Type-name coverage: ``array`` → :class:`ArrayAttributeRow`. The
``"array"`` type_name is a synthesised sentinel the USD adapter emits
from :meth:`UsdPropertyAdapter.get_attribute_metadata` whenever an
attribute's USD type string ends in ``"[]"``; the original USD type is
preserved on the underlying ``UsdAttributeProp.usd_type_str`` for future
tooltip/debug use but never reaches ``WidgetBuilderTable.build`` as-is.
One sentinel, one builder — mirrors the ``relationship`` registration.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.attribute_row import ArrayAttributeRow
from ovui_widgets.property.builders.builder_table import WidgetBuilderTable


def build_array(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> ArrayAttributeRow:
    """Build an ``ArrayAttributeRow`` (label + read-only StringField)."""
    return ArrayAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


WidgetBuilderTable.register("array", build_array)
