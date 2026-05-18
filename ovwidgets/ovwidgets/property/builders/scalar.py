# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Scalar-type builder functions for :class:`WidgetBuilderTable`.

Wraps the four existing scalar row classes in
``ovwidgets.property/attribute_row.py`` so :class:`WidgetBuilderTable` can
dispatch to them by ``type_name``. At module-import time, the four
builders are registered for the type names the row classes support.

Step 1.2 of the property inspector implementation. Row logic is unchanged; Step 1.4 will
convert the row classes to own an :class:`AttributeModelBase`.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.property.attribute_row import (
    BoolAttributeRow,
    FloatAttributeRow,
    IntAttributeRow,
    StringAttributeRow,
)
from ovwidgets.property.builders.builder_table import WidgetBuilderTable


def build_float(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> FloatAttributeRow:
    """Build a ``FloatAttributeRow`` (label + FloatDrag)."""
    return FloatAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_int(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> IntAttributeRow:
    """Build an ``IntAttributeRow`` (label + IntDrag)."""
    return IntAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_bool(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> BoolAttributeRow:
    """Build a ``BoolAttributeRow`` (label + CheckBox)."""
    return BoolAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


def build_string(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> StringAttributeRow:
    """Build a ``StringAttributeRow`` (label + StringField)."""
    return StringAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


WidgetBuilderTable.register("float", build_float)
WidgetBuilderTable.register("int", build_int)
WidgetBuilderTable.register("bool", build_bool)
WidgetBuilderTable.register("string", build_string)
# Step 3.8: USD ``double`` attributes surface as Python ``float`` through
# the adapter (``_TYPE_MAP["double"] == "float"``), but the adapter
# propagates the USD ``"double"`` string as ``metadata.type_name`` — so
# the dispatch table needed its own entry. Prior to Step 3.8 this slot
# was empty and the Property Inspector rendered ``(unsupported double)``
# for every ``double`` attribute (e.g. Sphere's ``radius``). ``build_float``
# handles the underlying value correctly; this is a one-line fix.
WidgetBuilderTable.register("double", build_float)
# The USD ``token`` type registers against ``builders/token.py::build_token``
# (Step 3.3) — a dispatcher that picks ``TokenAttributeRow`` (ComboBox)
# when ``metadata.allowed_values`` is set or ``StringAttributeRow``
# (StringField) otherwise.
