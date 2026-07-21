# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Icon and image URL constants (OvGear design system, design-system style rules).

Action icons are resolved relative to ovui_widgets.common/resources/icons/.
Prim-type and status icons are resolved relative to
ovui_widgets.common/style/icons/. Placeholder SVGs ship with the package;
production icons replace them in-place.

Call register_urls() once at startup (already invoked at module import time
via style/__init__.py).

Path resolution uses :mod:`importlib.resources` so consumers work both
from the editable in-tree layout and from a built wheel: the icon files
are package data declared in ``dist/common/pyproject.toml``.
"""

import importlib.resources
from pathlib import Path
from typing import Dict

from omni.ui import url

# ``importlib.resources.files()`` returns a Traversable rooted at the
# package directory. Joining with the relative subpath gives a path-like
# object whose ``__fspath__`` resolves to the on-disk location at
# import time. Wrapping in :class:`pathlib.Path` keeps the
# ``Path``-typed public contract that pre-Step-8 callers (and tests
# under ``tests/test_styles.py``) read these constants under
# (e.g. ``_STYLE_ICONS_DIR.is_dir()``), while still using
# ``importlib.resources`` for the wheel-safe lookup.
_ICONS_DIR: Path = Path(
    str(importlib.resources.files("ovui_widgets.common").joinpath("resources/icons"))
)
_STYLE_ICONS_DIR: Path = Path(
    str(importlib.resources.files("ovui_widgets.common.style").joinpath("icons"))
)

# Populated by register_urls(); maps URL name → absolute file path.
_STYLE_ICON_PATHS: Dict[str, str] = {}


def _icon(name: str) -> str:
    return str(_ICONS_DIR / name)


def _style_icon(name: str) -> str:
    return str(_STYLE_ICONS_DIR / name)


def get_icon_path(url_name: str) -> str:
    """Return the absolute filesystem path for a registered style-icon URL.

    Callers that need the resolved path (not the ``omni.ui.url`` shade
    name returned by ``getattr(url, url_name)``) should use this. The
    shade store returns a ``_ShadeName`` string when an attribute is
    read back, which is useful as input to ``ui.Image(source_url=...)``
    under Kit but not as an on-disk filesystem path — tests asserting
    the icon file exists and consumers (e.g.,
    :func:`_register_defaults` for the control-state handlers) that
    need the raw path go through this accessor.

    Raises ``KeyError`` if ``url_name`` has not been registered. The
    map is populated by :func:`register_urls` at import time.
    """
    return _STYLE_ICON_PATHS[url_name]


# ---------------------------------------------------------------------------
# Action icons (resources/icons/)
# ---------------------------------------------------------------------------
url.icon_check = _icon("check.svg")
url.icon_close = _icon("close.svg")
url.icon_expand = _icon("expand.svg")
url.icon_collapse = _icon("collapse.svg")
url.icon_eye_open = _icon("eye_open.svg")
url.icon_eye_closed = _icon("eye_closed.svg")
url.icon_lock = _icon("lock.svg")
url.icon_warning = _icon("warning.svg")
url.icon_error = _icon("error.svg")
url.icon_info = _icon("info.svg")
url.icon_search = _icon("search.svg")
url.icon_filter = _icon("filter.svg")
url.icon_settings = _icon("settings.svg")
url.icon_add = _icon("add.svg")
url.icon_remove = _icon("remove.svg")

# ---------------------------------------------------------------------------
# Prim-type icons — legacy names with icon_ prefix (resources/icons/)
# ---------------------------------------------------------------------------
url.icon_prim_xform = _icon("prim_xform.svg")
url.icon_prim_mesh = _icon("prim_mesh.svg")
url.icon_prim_light = _icon("prim_light.svg")
url.icon_prim_camera = _icon("prim_camera.svg")
url.icon_prim_scope = _icon("prim_scope.svg")
url.icon_prim_generic = _icon("prim_generic.svg")


def register_urls() -> None:
    """Register prim-type, status, and control-state icon URLs from
    ovui_widgets.app/style/icons/.

    Uses short names without the icon_ prefix (url.prim_mesh,
    url.status_warning, url.control_state_mixed) so consumer code can
    reference icons by semantic name. Also populates _STYLE_ICON_PATHS
    with the resolved absolute paths for tests.

    App/prim/stage chrome/badge icons are registered as ``.png`` (high-DPI
    raster renders committed alongside the source ``.svg``) because the standalone
    ``omni.ui`` build in this repo routes ``ui.Image(source_url)`` through the
    stb_image loader, which does not recognise SVG. Status and control-state
    icons fall back to ``.svg`` — they are referenced by styling only, never
    rasterised today, and tests still check for the SVG paths.
    """
    _app_icons = [
        ("app_logo", "app_logo.png"),
    ]
    _prim_icons = [
        ("prim_mesh",    "prim_mesh.png"),
        ("prim_light",   "prim_light.png"),
        ("prim_camera",  "prim_camera.png"),
        ("prim_scope",   "prim_scope.png"),
        ("prim_xform",   "prim_xform.png"),
        # Specifier icons (Layers Step 49). ``prim_def`` + ``prim_over``
        # differentiate concrete definitions from override opinions in
        # the Layers tree; ``prim_class`` already served the Stage
        # "is-a-class" flag and is reused here for ``Sdf.SpecifierClass``
        # rows so the two windows share a single glyph per specifier.
        ("prim_def",     "prim_def.png"),
        ("prim_over",    "prim_over.png"),
        ("prim_class",   "prim_class.png"),
        ("prim_generic", "prim_generic.png"),
    ]
    _status_icons = [
        ("status_warning", "status_warning.svg"),
        ("status_error",   "status_error.svg"),
        ("status_info",    "status_info.svg"),
    ]
    # Step 4.4 — per-state icons for the Property Inspector's right-side
    # indicator column (property control-state behavior, the property inspector behavior).
    # Names mirror the lowercased handler name used as the omni.ui style
    # state selector (``Property.ControlState::mixed`` etc), keeping the
    # SVG filename / URL name / style-state name triad in lock-step.
    _control_state_icons = [
        ("control_state_mixed",       "mixed.svg"),
        ("control_state_locked",      "locked.svg"),
        ("control_state_timesample",  "timesample.svg"),
        ("control_state_not_default", "not_default.svg"),
    ]
    _stage_chrome_icons = [
        ("stage_search",   "search.png"),
        ("stage_close_x",  "close_x.png"),
        ("stage_eye_on",   "eye_open.png"),
        ("stage_eye_off",  "eye_closed.png"),
        ("stage_active_off", "active_off.png"),
    ]
    _viewport_icons = [
        ("viewport_tool_move",   "viewport_tool_move.png"),
        ("viewport_tool_rotate", "viewport_tool_rotate.png"),
        ("viewport_tool_scale",  "viewport_tool_scale.png"),
        ("menu_checkmark",       "menu_checkmark.png"),
    ]
    _stage_badge_icons = [
        ("badge_reference",   "badge_reference.png"),
        ("badge_payload",     "badge_payload.png"),
        ("badge_instance",    "badge_instance.png"),
        ("badge_inherits",    "badge_inherits.png"),
        ("badge_specializes", "badge_specializes.png"),
    ]
    # Content-browser icons (the content browser implementation step 5, the content browser behavior
    # §10 + §32). Asset file-type icons resolve to coloured 64x64 PNG
    # placeholders one per category in ``ovui_widgets.common.asset_types`` — the
    # ``icon_url_key`` strings on each ``AssetTypeDef`` are the URL names
    # below. Chrome icons back the browser toolbar / navigation / filter
    # widgets wired up in later phases.
    _asset_icons = [
        ("asset_folder",   "asset_folder.png"),
        ("asset_usd",      "asset_usd.png"),
        ("asset_image",    "asset_image.png"),
        ("asset_material", "asset_material.png"),
        ("asset_model",    "asset_model.png"),
        ("asset_sound",    "asset_sound.png"),
        ("asset_script",   "asset_script.png"),
        ("asset_volume",   "asset_volume.png"),
        ("asset_text",     "asset_text.png"),
        ("asset_archive",  "asset_archive.png"),
        ("asset_unknown",  "asset_unknown.png"),
    ]
    _content_chrome_icons = [
        # Bug 14 — reuse the stage's ``search.png`` so the content
        # browser's search field and the stage filter pill read with
        # the same magnifier glyph (same pattern as ``content_close``
        # → ``close_x.png`` below). The original ``content_search.png``
        # asset was a nearly-blank 422-byte placeholder.
        ("content_search",          "search.png"),
        ("content_filter",          "content_filter.png"),
        ("content_bookmark",        "content_bookmark.png"),
        ("content_bookmark_filled", "content_bookmark_filled.png"),
        ("content_arrow_left",      "content_arrow_left.png"),
        ("content_arrow_right",     "content_arrow_right.png"),
        ("content_arrow_up",        "content_arrow_up.png"),
        ("content_arrow_down",      "content_arrow_down.png"),
        ("content_grid_view",       "content_grid_view.png"),
        ("content_list_view",       "content_list_view.png"),
        ("content_home",            "content_home.png"),
        ("content_plus",            "content_plus.png"),
        ("content_minus",           "content_minus.png"),
        ("content_gear",            "content_gear.png"),
        # Reuses the already-shipped ``close_x.png`` (also pointed at
        # by ``stage_close_x``) — the glyph is domain-agnostic, and
        # duplicating the asset under ``content_close.png`` would
        # double the on-disk payload for no visual gain.
        ("content_close",           "close_x.png"),
    ]
    for name, filename in (
        _app_icons
        + _prim_icons
        + _status_icons
        + _control_state_icons
        + _stage_chrome_icons
        + _viewport_icons
        + _stage_badge_icons
        + _asset_icons
        + _content_chrome_icons
    ):
        path = _style_icon(filename)
        setattr(url, name, path)
        _STYLE_ICON_PATHS[name] = path


# Register at import time so that importing ovui_widgets.app.style is sufficient.
register_urls()
