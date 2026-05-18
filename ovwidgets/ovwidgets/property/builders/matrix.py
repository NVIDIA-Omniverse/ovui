# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Matrix builder functions for :class:`WidgetBuilderTable`.

Step 3.5 of the property inspector implementation (property attribute builder behavior). USD ``matrix2d`` / ``matrix3d``
/ ``matrix4d`` attributes render as an N×N grid of ``ui.FloatDrag`` cells
(4 / 9 / 16 cells respectively). Each cell edits one component of the
matrix; the inherited ``change_on_edit_end=True`` default on
:class:`AttributeModelBase` defers the write until edit ends so typing a
value mid-keystroke does not spam the adapter.

Type-name coverage:

* ``matrix2d`` → :class:`MatrixAttributeRow` with ``n_dim=2`` (2×2, 4 cells)
* ``matrix3d`` → :class:`MatrixAttributeRow` with ``n_dim=3`` (3×3, 9 cells)
* ``matrix4d`` → :class:`MatrixAttributeRow` with ``n_dim=4`` (4×4, 16 cells)

USD only ships double-precision matrix types (no ``matrix2f`` / ``matrix3f``
/ ``matrix4f``), so the three registrations above cover the complete
matrix type surface — unlike vec/colour which carry ``float``/``double``/
``half`` precision variants.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.property.attribute_row import MatrixAttributeRow
from ovwidgets.property.builders.builder_table import WidgetBuilderTable


def build_matrix2d(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> MatrixAttributeRow:
    """Build a 2×2 ``MatrixAttributeRow`` (4 ``ui.FloatDrag`` cells)."""
    return MatrixAttributeRow(
        metadata, adapter, n_dim=2,
        match=kwargs.get("match", ""),
    )


def build_matrix3d(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> MatrixAttributeRow:
    """Build a 3×3 ``MatrixAttributeRow`` (9 ``ui.FloatDrag`` cells)."""
    return MatrixAttributeRow(
        metadata, adapter, n_dim=3,
        match=kwargs.get("match", ""),
    )


def build_matrix4d(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> MatrixAttributeRow:
    """Build a 4×4 ``MatrixAttributeRow`` (16 ``ui.FloatDrag`` cells)."""
    return MatrixAttributeRow(
        metadata, adapter, n_dim=4,
        match=kwargs.get("match", ""),
    )


WidgetBuilderTable.register("matrix2d", build_matrix2d)
WidgetBuilderTable.register("matrix3d", build_matrix3d)
WidgetBuilderTable.register("matrix4d", build_matrix4d)
