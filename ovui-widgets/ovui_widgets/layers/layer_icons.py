# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Icon helper for the Layers tree delegate (LAYERS-PLAN Step 49).

Mirrors :mod:`ovui_widgets.stage.widget.stage_icons`: wraps
``ovui_widgets.common.style.urls._STYLE_ICON_PATHS`` with a specifier-/badge-aware
lookup surface and caches one :class:`omni.ui.RasterImageProvider` per
path so the delegate's per-cell rebuild does not re-decode the PNG
every frame.

The standalone ``omni.ui`` build in this repository routes
``ui.Image(url)`` through stb_image, which does not recognise SVG — so
the delegate paints icons with :class:`ui.ImageWithProvider`, backed by
the PNG raster committed alongside each SVG. Both helpers return the
absolute on-disk path so :func:`provider` can hand the same string back
to :class:`omni.ui.RasterImageProvider`.

The three specifier icons + three composition badges align with
LAYERS-WINDOW-ARCHITECTURE §18.1 ("Specifier classification") — the
plan uses ``DEF`` / ``OVER`` / ``CLASS`` as the primary icon axis and
layers the ref / payload / instance badges on top when the backing
descriptor flags are set.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import omni.ui as ui
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

from ovui_widgets.common.style.urls import _STYLE_ICON_PATHS

_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``.

    Providers are process-scoped and thread-safe. Caching avoids
    re-decoding the PNG on every :meth:`LayerDelegate.build_widget`
    pass — a visible prim-spec row rebuilds once per frame during a
    hover / selection transition, so the cache eliminates ``N`` decodes
    per tree refresh.
    """
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


_SPECIFIER_ICON_NAME: Dict[PrimSpecifier, str] = {
    PrimSpecifier.DEF:   "prim_def",
    PrimSpecifier.OVER:  "prim_over",
    PrimSpecifier.CLASS: "prim_class",
}


def specifier_icon(specifier: PrimSpecifier) -> Optional[str]:
    """Return the absolute PNG path for a :class:`PrimSpecifier` value.

    Returns ``None`` when the URL registry does not carry the expected
    entry (e.g. a partially-registered test harness) so callers can
    degrade gracefully to a primitive fallback rather than raising into
    the paint pass.
    """
    name = _SPECIFIER_ICON_NAME.get(specifier)
    if name is None:
        return None
    return _STYLE_ICON_PATHS.get(name)


# Ordered so the dominant badge paints last (on top). Payload is more
# heavyweight than reference (Kit treats payloads as "deferred-load
# references"), so a descriptor carrying both flags reads as a payload
# row — matching LAYERS-PLAN Step 49 "payload takes priority like Kit
# does". Instance is orthogonal and always paints whenever the flag is
# set; the delegate paints the specifier badge and the instance badge
# in distinct corners so they do not overlap.
_BADGE_ORDER: List[str] = ["badge_reference", "badge_payload"]


def composition_badge(descriptor: PrimSpecDescriptor) -> Optional[str]:
    """Return the absolute PNG path for the composition badge of
    ``descriptor``, or ``None`` when neither reference nor payload arcs
    are present.

    Payload wins over reference when both flags are set; LAYERS-PLAN
    Step 49 flags that as the "Kit-consistent" ordering (a payload-
    carrying prim is also a reference-carrying prim in the Sdf sense,
    but the payload is the signal the user cares about).
    """
    if descriptor.has_payload:
        return _STYLE_ICON_PATHS.get("badge_payload")
    if descriptor.has_reference:
        return _STYLE_ICON_PATHS.get("badge_reference")
    return None


def instance_badge(descriptor: PrimSpecDescriptor) -> Optional[str]:
    """Return the absolute PNG path for the instance badge, or ``None``
    when the prim spec is not marked ``instanceable``.

    The instance badge is independent from the composition badge (a
    prim may be instanceable without carrying a reference or payload)
    so the delegate paints them in separate corners of the specifier
    icon.
    """
    if descriptor.is_instanceable:
        return _STYLE_ICON_PATHS.get("badge_instance")
    return None


__all__ = [
    "provider",
    "specifier_icon",
    "composition_badge",
    "instance_badge",
]


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovui_widgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
