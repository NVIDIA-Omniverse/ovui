# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""StageIcons — single lookup surface for stage-row icons.

Resolves type categories and composition/state flags to the absolute icon
paths registered by ``ovui_widgets.common.style.urls``. The standalone ``omni.ui``
build routes ``ui.Image(source_url)`` through stb_image, which rejects
SVG, so at render-time callers fetch a cached
:class:`omni.ui.RasterImageProvider` from :func:`provider` and hand it to
:class:`omni.ui.ImageWithProvider`. Providers are process-scoped and
thread-safe to re-use.

See the stage implementation step 13 (prim type icons) and Step 14 (composition badges).
"""

from __future__ import annotations

from typing import List

from ovui_data_adapters.common import BadgeFlags, ItemFlags

from ovui_widgets.common.icon_caches import provider
from ovui_widgets.common.style.urls import _STYLE_ICON_PATHS

_TYPE_ICON_NAME: dict[str, str] = {
    "Mesh":   "prim_mesh",
    "Light":  "prim_light",
    "Camera": "prim_camera",
    "Scope":  "prim_scope",
    "Xform":  "prim_xform",
}


def prim_type_icon(category: str, *, is_class: bool = False) -> str:
    """Return the absolute SVG path for a prim category. Falls back to generic."""
    if is_class:
        return _STYLE_ICON_PATHS.get("prim_class", _STYLE_ICON_PATHS["prim_generic"])
    name = _TYPE_ICON_NAME.get(category, "prim_generic")
    return _STYLE_ICON_PATHS.get(name, _STYLE_ICON_PATHS["prim_generic"])


_BADGE_FLAG_TO_NAME: list[tuple[BadgeFlags, str]] = [
    (BadgeFlags.REFERENCE,   "badge_reference"),
    (BadgeFlags.PAYLOAD,     "badge_payload"),
    (BadgeFlags.INSTANCE,    "badge_instance"),
    (BadgeFlags.INHERITS,    "badge_inherits"),
    (BadgeFlags.SPECIALIZES, "badge_specializes"),
]


def badge_icons(flags: BadgeFlags) -> List[str]:
    """Resolve a ``BadgeFlags`` value to the list of absolute SVG paths to paint.

    Order matches ``_BADGE_FLAG_TO_NAME`` so the dominant glyph ends up last
    in the stack (painted on top) — REFERENCE < PAYLOAD < INSTANCE etc.
    """
    return [
        _STYLE_ICON_PATHS[name]
        for flag, name in _BADGE_FLAG_TO_NAME
        if flags & flag and name in _STYLE_ICON_PATHS
    ]


def active_off_icon() -> str:
    return _STYLE_ICON_PATHS["stage_active_off"]


def eye_on_icon() -> str:
    return _STYLE_ICON_PATHS["stage_eye_on"]


def eye_off_icon() -> str:
    return _STYLE_ICON_PATHS["stage_eye_off"]


def search_icon() -> str:
    return _STYLE_ICON_PATHS["stage_search"]


def close_icon() -> str:
    return _STYLE_ICON_PATHS["stage_close_x"]


__all__ = [
    "prim_type_icon",
    "badge_icons",
    "active_off_icon",
    "eye_on_icon",
    "eye_off_icon",
    "search_icon",
    "close_icon",
    "provider",
    "BadgeFlags",
    "ItemFlags",
]
