# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Token / enum builder for :class:`WidgetBuilderTable`.

Step 3.3 of the property inspector implementation (property attribute builder behavior). USD ``token`` attributes come
in two flavours:

* **Enum-like** — the attribute carries ``allowedTokens`` metadata that
  restricts its authored values to a fixed set (e.g. ``visibility`` on
  ``UsdGeomImageable`` is limited to ``"inherited"`` / ``"invisible"``).
  These render as :class:`ui.ComboBox` via :class:`TokenAttributeRow`.
* **Open string** — no ``allowedTokens``; the authored value is any
  token. These render as a plain :class:`ui.StringField` via the
  existing :class:`StringAttributeRow`.

The :func:`build_token` dispatcher inspects ``metadata.allowed_values``
(which the adapter populates from USD's ``allowedTokens`` metadata) and
routes to the appropriate row class. A bare ``[]`` or missing list
counts as "no allowedTokens" and takes the string-field path.

This module replaces the pre-3.3 ``"token" → build_string`` shortcut
that ``scalar.py`` carried during Steps 1.3 through 3.2 — the shortcut
is removed in Step 3.3.
"""

from typing import Any

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovui_widgets.property.attribute_row import StringAttributeRow, TokenAttributeRow
from ovui_widgets.property.builders.builder_table import WidgetBuilderTable


def build_token(
    attr_name: str,
    metadata: AttributeMetadata,
    adapter: PropertyAdapter,
    **kwargs: Any,
) -> Any:
    """Build a token row — ComboBox if ``allowed_values`` is set, else StringField.

    Returns a :class:`TokenAttributeRow` instance when
    ``metadata.allowed_values`` is a non-empty iterable; otherwise a
    :class:`StringAttributeRow`. The return type is ``Any`` because the
    two row classes do not share a base.
    """
    allowed = metadata.allowed_values
    match = kwargs.get("match", "")
    if allowed:
        return TokenAttributeRow(metadata, adapter, match=match)
    return StringAttributeRow(metadata, adapter, match=match)


WidgetBuilderTable.register("token", build_token)
