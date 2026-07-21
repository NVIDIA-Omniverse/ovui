# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovui_widgets.property.builders — widget builder table + built-in builders.

Introduced in Step 1.2 of the property inspector implementation (property attribute builder behavior). The
:class:`WidgetBuilderTable` is populated at package-import time by the
``scalar``, ``vec``, ``ivec``, ``token``, ``color``, ``matrix``, and
``asset`` submodules, which register the four scalar type names
(``float``, ``int``, ``bool``, ``string``), eleven float vector type
names (vec2: ``half2/float2/double2``; vec3: ``float3/double3/normal3f/
point3f/vector3f``; vec4: ``half4/float4/double4``), the three integer
vector type names (``int2/int3/int4``), the ``token`` type (ComboBox
when ``metadata.allowed_values`` is set, StringField fallback
otherwise), four colour type names
(``color3f/color3d/color4f/color4d``) that render as an R/G/B(/A) row
plus a live swatch preview, three matrix type names (``matrix2d/
matrix3d/matrix4d``) that render as an N×N grid of ``ui.FloatDrag``
cells, and the ``asset`` type (StringField + folder button).

Step 3.1 of the property inspector implementation replaced the vec3-only ``vec3`` submodule
with a unified ``vec`` submodule covering all three float vector
dimensions. Step 3.2 added the ``ivec`` submodule for the three integer
vector type names. Step 3.3 added the ``token`` submodule and removed
the pre-3.3 ``"token" → build_string`` shortcut previously registered
by ``scalar``. Step 3.4 added the ``color`` submodule and moved
``color3f`` registration out of ``vec`` so colour attributes render a
swatch preview. Step 3.5 added the ``matrix`` submodule for the three
USD matrix types. Step 3.6 added the ``asset`` submodule for
``SdfAssetPath`` attributes. Step 3.7 added the ``relationship``
submodule for ``Usd.Relationship`` objects (read-only target list).
"""

from ovui_widgets.property.builders import array as _array  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders import asset as _asset  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders import color as _color  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders import ivec as _ivec  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders import matrix as _matrix  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders import (
    relationship as _relationship,  # noqa: F401 — registers built-ins
)
from ovui_widgets.property.builders import scalar as _scalar  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders import token as _token  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders import vec as _vec  # noqa: F401 — registers built-ins
from ovui_widgets.property.builders.builder_table import WidgetBuilderTable

__all__ = ["WidgetBuilderTable"]
