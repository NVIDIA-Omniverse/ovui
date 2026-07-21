# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Asset-path builder for :class:`WidgetBuilderTable`.

Step 3.6 of the property inspector implementation (property attribute builder behavior). USD ``asset`` attributes render
as a label + :class:`omni.ui.StringField` + small folder button. The folder
button is a no-op in Step 3.6 — the :mod:`omni.kit.window.file_importer`
hook lands in a later phase (the property inspector behavior).

Type-name coverage: ``asset`` → :class:`AssetPathAttributeRow`. USD only
ships one asset-path scalar type (``SdfAssetPath``) and one array type
(``SdfAssetPathArray``); the array variant is Step 3.8 territory, so only
the scalar name is registered here.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.attribute_row import AssetPathAttributeRow
from ovui_widgets.property.builders.builder_table import WidgetBuilderTable


def build_asset(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> AssetPathAttributeRow:
    """Build an ``AssetPathAttributeRow`` (label + StringField + folder button)."""
    return AssetPathAttributeRow(
        metadata, adapter, match=kwargs.get("match", ""),
    )


WidgetBuilderTable.register("asset", build_asset)
