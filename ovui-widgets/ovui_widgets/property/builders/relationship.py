# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Relationship builder for :class:`WidgetBuilderTable`.

Step 3.7 of the property inspector implementation (property attribute builder behavior, the property inspector behavior).
USD ``Usd.Relationship`` objects carry a list of target prim paths; the
row renders that list as a comma-separated read-only string inside a
:class:`omni.ui.StringField`. A modal stage-browser target picker
(``RelationshipTargetPicker``) is scheduled for a later phase — Step 3.7
is strictly display-only.

Type-name coverage: ``relationship`` → :class:`RelationshipAttributeRow`.
The ``"relationship"`` type_name is a synthesised sentinel the USD
adapter stashes in ``UsdAttributeProp.usd_type_str`` when enumerating
``prim.GetRelationships()``; there is no ``Usd.Relationship.GetTypeName()``
counterpart to the attribute case, so the sentinel is the single hook
this builder needs to register against.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.attribute_row import RelationshipAttributeRow
from ovui_widgets.property.builders.builder_table import WidgetBuilderTable


def build_relationship(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> RelationshipAttributeRow:
    """Build a ``RelationshipAttributeRow`` (label + read-only StringField)."""
    return RelationshipAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


WidgetBuilderTable.register("relationship", build_relationship)
