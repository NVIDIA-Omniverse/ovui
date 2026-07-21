# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Asset-type catalog: extension -> category, display name, semantic icon key.

This is the single source of truth for file-type recognition used by
frontend components that need to filter, group, sort, or select a
semantic icon token by file type. It is the ovui equivalent of Kit's
``omni.kit.helper.file_utils/asset_types.py``,
collapsed to a narrower category set.

Compared to Kit's catalog this module:

- Exposes a tiny enum (:class:`AssetCategory`) with 11 members rather
  than Kit's 22 string constants. Specific USD sub-variants
  (``ASSET_TYPE_GEO_USD``, ``ASSET_TYPE_ANIM_USD`` ...) collapse into a
  single :attr:`AssetCategory.USD` for v1; dotted variants like
  ``.geo.usd`` still match because matching is a case-insensitive
  ``endswith``.
- Adds an :attr:`AssetCategory.ARCHIVE` category (Kit treats archives
  as Unknown).
- Adds an :attr:`AssetCategory.TEXT` category (Kit treats ``.txt`` /
  ``.md`` as Unknown).

The module is stdlib-only and has zero forward dependencies: no
``omni.ui``, no ``ovui_widgets``, no backend imports, and no filesystem
access. The :attr:`AssetTypeDef.icon_url_key` strings are semantic icon
tokens; each frontend maps those tokens to its own icon assets.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Iterable, List, Tuple

# -----------------------------------------------------------------------------
# Enum and data class
# -----------------------------------------------------------------------------

class AssetCategory(Enum):
    """Top-level asset category a file belongs to.

    Category membership is determined by file extension (case-insensitive
    ``endswith``) via :func:`get_category`. :attr:`FOLDER` is never
    returned by that function; folders are dispatched by the backend's
    ``IS_FOLDER`` flag, not by extension.
    """

    FOLDER = "folder"
    USD = "usd"          # .usd/.usda/.usdc/.usdz/.live/.omni and dotted variants
    IMAGE = "image"      # bmp/gif/jpg/png/hdr/exr/tiff/psd/...
    MATERIAL = "material"  # .mdl/.mtlx
    MODEL = "model"      # .fbx/.obj
    SOUND = "sound"      # wav/ogg/mp3/...
    SCRIPT = "script"    # .py
    VOLUME = "volume"    # .vdb/.nvdb
    TEXT = "text"        # .txt/.md/.json/.yaml/.toml/...
    ARCHIVE = "archive"  # .zip/.tar/.gz/... (ovui-specific)
    UNKNOWN = "unknown"  # Fallback for any extension not otherwise recognised


@dataclass(frozen=True)
class AssetTypeDef:
    """Definition of one asset category's metadata.

    - ``category``: the enum member this def belongs to (redundant key
      so a single def carries its own identity when passed around).
    - ``display_name``: human-readable string for tooltips / type
      columns / status-bar messages.
    - ``icon_url_key``: semantic token that a frontend maps to the icon
      for this category (e.g. ``"asset_usd"``). The services package
      does not own icon assets or URL registration.
    - ``extensions``: lowercase, leading-dot extensions this category
      owns (e.g. ``(".usd", ".usda", ".usdc")``). Empty for
      :attr:`AssetCategory.FOLDER` (dispatched by backend flag) and
      :attr:`AssetCategory.UNKNOWN` (fallback).
    """

    category: AssetCategory
    display_name: str
    icon_url_key: str
    extensions: Tuple[str, ...]


# -----------------------------------------------------------------------------
# Catalog
# -----------------------------------------------------------------------------

# Ordering determines match precedence in :func:`get_category`: more
# specific categories would come first if we had sub-variants. V1
# categories are mutually exclusive on extension, so order is purely
# for readability.
_CATALOG: Dict[AssetCategory, AssetTypeDef] = {
    AssetCategory.FOLDER: AssetTypeDef(
        category=AssetCategory.FOLDER,
        display_name="Folder",
        icon_url_key="asset_folder",
        extensions=(),
    ),
    AssetCategory.USD: AssetTypeDef(
        category=AssetCategory.USD,
        display_name="USD File",
        icon_url_key="asset_usd",
        extensions=(".usd", ".usda", ".usdc", ".usdz", ".live", ".omni"),
    ),
    AssetCategory.IMAGE: AssetTypeDef(
        category=AssetCategory.IMAGE,
        display_name="Image",
        icon_url_key="asset_image",
        extensions=(
            ".bmp", ".gif", ".jpg", ".jpeg", ".png", ".tga",
            ".tif", ".tiff", ".hdr", ".dds", ".exr", ".psd",
            ".ies", ".tx", ".webp",
        ),
    ),
    AssetCategory.MATERIAL: AssetTypeDef(
        category=AssetCategory.MATERIAL,
        display_name="Material",
        icon_url_key="asset_material",
        extensions=(".mdl", ".mtlx"),
    ),
    AssetCategory.MODEL: AssetTypeDef(
        category=AssetCategory.MODEL,
        display_name="3D Model",
        icon_url_key="asset_model",
        extensions=(".fbx", ".obj"),
    ),
    AssetCategory.SOUND: AssetTypeDef(
        category=AssetCategory.SOUND,
        display_name="Audio",
        icon_url_key="asset_sound",
        extensions=(
            ".wav", ".wave", ".ogg", ".oga", ".flac", ".fla",
            ".mp3", ".m4a", ".spx", ".opus", ".adpcm",
        ),
    ),
    AssetCategory.SCRIPT: AssetTypeDef(
        category=AssetCategory.SCRIPT,
        display_name="Python Script",
        icon_url_key="asset_script",
        extensions=(".py",),
    ),
    AssetCategory.VOLUME: AssetTypeDef(
        category=AssetCategory.VOLUME,
        display_name="Volume",
        icon_url_key="asset_volume",
        extensions=(".vdb", ".nvdb"),
    ),
    AssetCategory.TEXT: AssetTypeDef(
        category=AssetCategory.TEXT,
        display_name="Text",
        icon_url_key="asset_text",
        extensions=(
            ".txt", ".md", ".json", ".yaml", ".yml", ".toml",
            ".ini", ".cfg", ".log",
        ),
    ),
    AssetCategory.ARCHIVE: AssetTypeDef(
        category=AssetCategory.ARCHIVE,
        display_name="Archive",
        icon_url_key="asset_archive",
        extensions=(".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z"),
    ),
    AssetCategory.UNKNOWN: AssetTypeDef(
        category=AssetCategory.UNKNOWN,
        display_name="File",
        icon_url_key="asset_unknown",
        extensions=(),
    ),
}


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def get_category(filename_or_url: str) -> AssetCategory:
    """Return the :class:`AssetCategory` that owns ``filename_or_url``'s extension.

    Matching is case-insensitive and uses ``endswith`` so dotted
    variants (``.geo.usd``) still match the base category (``USD``).
    Folders are *not* detected here; pass the backend's ``IS_FOLDER``
    flag separately.

    Returns :attr:`AssetCategory.UNKNOWN` for any input that does not
    match a registered extension, including empty strings, bare names
    without an extension, and extensions not in the catalog.
    """
    lowered = filename_or_url.lower()
    for category, type_def in _CATALOG.items():
        if category is AssetCategory.FOLDER or category is AssetCategory.UNKNOWN:
            continue
        for ext in type_def.extensions:
            if lowered.endswith(ext):
                return category
    return AssetCategory.UNKNOWN


def get_display_name(filename_or_url: str) -> str:
    """Return the human-readable display name for ``filename_or_url``'s category."""
    return _CATALOG[get_category(filename_or_url)].display_name


def get_icon_url_key(filename_or_url: str) -> str:
    """Return the semantic icon token for ``filename_or_url``.

    The returned string is a key like ``"asset_usd"`` or
    ``"asset_unknown"``. This function never returns an empty string;
    :attr:`AssetCategory.UNKNOWN` always resolves to ``"asset_unknown"``.
    """
    return _CATALOG[get_category(filename_or_url)].icon_url_key


def is_asset_category(filename_or_url: str, category: AssetCategory) -> bool:
    """Return ``True`` iff ``filename_or_url`` belongs to ``category``.

    Equivalent to ``get_category(filename_or_url) is category``.
    Provided as a named helper to make call sites readable, e.g.
    ``if is_asset_category(url, AssetCategory.IMAGE): ...``.
    """
    return get_category(filename_or_url) is category


def register_extensions(category: AssetCategory, extensions: Iterable[str]) -> None:
    """Add extensions to an existing category at runtime.

    ``extensions`` may be any iterable of strings; each must start with
    a leading dot and will be lowercased before insertion. Extensions
    already registered with ``category`` are ignored; extensions owned
    by a *different* category raise :class:`ValueError`; a single
    extension can only belong to one category at a time.

    A consumer that adds a new image format can register it here without
    editing the built-in catalog. :attr:`AssetCategory.FOLDER` and
    :attr:`AssetCategory.UNKNOWN` reject registration (neither is
    extension-matched).
    """
    if category is AssetCategory.FOLDER or category is AssetCategory.UNKNOWN:
        raise ValueError(
            f"Cannot register extensions for {category.name!r} "
            f"- FOLDER is flag-dispatched and UNKNOWN is the fallback."
        )

    normalised = []
    for ext in extensions:
        if not ext.startswith("."):
            raise ValueError(
                f"Extension {ext!r} must start with a leading dot (e.g. '.foo')."
            )
        normalised.append(ext.lower())

    owners = {
        ext: other_cat
        for other_cat, other_def in _CATALOG.items()
        for ext in other_def.extensions
        if other_cat is not category
    }
    for ext in normalised:
        if ext in owners:
            raise ValueError(
                f"Extension {ext!r} is already registered with "
                f"{owners[ext].name!r}; unregister it there first."
            )

    existing = _CATALOG[category]
    existing_set = set(existing.extensions)
    merged = existing.extensions + tuple(
        e for e in normalised if e not in existing_set
    )
    _CATALOG[category] = replace(existing, extensions=merged)


def categories() -> List[AssetCategory]:
    """Return a new list of every :class:`AssetCategory` in catalog order.

    The list is a fresh copy; mutating it does not affect the catalog.
    Use it to drive UI (filter menus, legend dialogs) that needs the
    full set of category members.
    """
    return list(_CATALOG.keys())
