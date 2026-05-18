# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Content-browser icon registration tests (the content browser implementation step 5).

Verifies that:

* Every ``asset_*`` URL key announced by ``ovwidgets.common.asset_types`` is
  registered by ``ovwidgets.common.style.urls.register_urls`` and resolves to an
  on-disk PNG that decodes cleanly.
* Every ``content_*`` chrome icon key (browser toolbar / navigation /
  filter silhouettes) is registered and resolves to an on-disk PNG.
* ``getattr(url, <name>)`` returns a shade-store string (what
  ``ui.Image(source_url=...)`` consumes under Kit).
* The ``icon_url_key`` strings baked into the asset-type catalog
  (Step 4) line up with the URL keys registered here (Step 5) — the
  two modules agree on the name list.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from omni.ui import url
from PIL import Image

import ovwidgets.app
import ovwidgets.app.style  # noqa: F401 — ensures register_urls() has run.
from ovwidgets.common.asset_types import _CATALOG, AssetCategory, categories
from ovwidgets.common.style import urls as _urls_module
from ovwidgets.common.style.urls import _STYLE_ICON_PATHS, get_icon_path, register_urls

# ---------------------------------------------------------------------------
# Canonical lists — kept here (not imported) so a typo in the implementation
# does not silently propagate into the test expectations.
# ---------------------------------------------------------------------------

_ASSET_URL_KEYS = (
    "asset_folder",
    "asset_usd",
    "asset_image",
    "asset_material",
    "asset_model",
    "asset_sound",
    "asset_script",
    "asset_volume",
    "asset_text",
    "asset_archive",
    "asset_unknown",
)

_CONTENT_URL_KEYS = (
    "content_search",
    "content_filter",
    "content_bookmark",
    "content_bookmark_filled",
    "content_arrow_left",
    "content_arrow_right",
    "content_arrow_up",
    "content_arrow_down",
    "content_grid_view",
    "content_list_view",
    "content_home",
    "content_plus",
    "content_minus",
)


# ---------------------------------------------------------------------------
# Registration presence
# ---------------------------------------------------------------------------

class TestAssetIconRegistration:
    @pytest.mark.parametrize("key", _ASSET_URL_KEYS)
    def test_key_registered_on_url_store(self, key):
        """``getattr(url, key)`` returns the shade-store string form."""
        val = getattr(url, key)
        assert isinstance(val, str)
        assert val == key

    @pytest.mark.parametrize("key", _ASSET_URL_KEYS)
    def test_key_present_in_path_map(self, key):
        assert key in _STYLE_ICON_PATHS
        assert _STYLE_ICON_PATHS[key] == get_icon_path(key)

    @pytest.mark.parametrize("key", _ASSET_URL_KEYS)
    def test_icon_file_exists(self, key):
        path = get_icon_path(key)
        assert os.path.isfile(path), f"Missing icon file for {key!r}: {path}"

    @pytest.mark.parametrize("key", _ASSET_URL_KEYS)
    def test_icon_file_is_png(self, key):
        path = get_icon_path(key)
        assert path.endswith(".png")
        with Image.open(path) as img:
            img.verify()

    @pytest.mark.parametrize("key", _ASSET_URL_KEYS)
    def test_icon_file_lives_under_style_icons_dir(self, key):
        path = Path(get_icon_path(key)).resolve()
        style_dir = Path(_urls_module._STYLE_ICONS_DIR).resolve()
        assert style_dir in path.parents, (
            f"{key!r} resolves to {path}, expected under {style_dir}"
        )


class TestContentChromeIconRegistration:
    @pytest.mark.parametrize("key", _CONTENT_URL_KEYS)
    def test_key_registered_on_url_store(self, key):
        val = getattr(url, key)
        assert isinstance(val, str)
        assert val == key

    @pytest.mark.parametrize("key", _CONTENT_URL_KEYS)
    def test_key_present_in_path_map(self, key):
        assert key in _STYLE_ICON_PATHS
        assert _STYLE_ICON_PATHS[key] == get_icon_path(key)

    @pytest.mark.parametrize("key", _CONTENT_URL_KEYS)
    def test_icon_file_exists(self, key):
        path = get_icon_path(key)
        assert os.path.isfile(path), f"Missing icon file for {key!r}: {path}"

    @pytest.mark.parametrize("key", _CONTENT_URL_KEYS)
    def test_icon_file_is_png(self, key):
        path = get_icon_path(key)
        assert path.endswith(".png")
        with Image.open(path) as img:
            img.verify()

    @pytest.mark.parametrize("key", _CONTENT_URL_KEYS)
    def test_icon_file_lives_under_style_icons_dir(self, key):
        path = Path(get_icon_path(key)).resolve()
        style_dir = Path(_urls_module._STYLE_ICONS_DIR).resolve()
        assert style_dir in path.parents


# ---------------------------------------------------------------------------
# Catalog cross-check
# ---------------------------------------------------------------------------

class TestCatalogMatchesRegistration:
    """The ``icon_url_key`` on every ``AssetTypeDef`` must be registered."""

    @pytest.mark.parametrize("category", list(AssetCategory))
    def test_catalog_icon_key_is_registered(self, category):
        icon_key = _CATALOG[category].icon_url_key
        assert icon_key in _STYLE_ICON_PATHS, (
            f"{category.name} -> {icon_key!r} is not registered"
        )
        assert os.path.isfile(get_icon_path(icon_key))

    def test_every_asset_category_maps_to_an_asset_prefixed_key(self):
        """Every catalog ``icon_url_key`` starts with the ``asset_`` prefix."""
        for category in categories():
            key = _CATALOG[category].icon_url_key
            assert key.startswith("asset_"), (
                f"{category.name} -> {key!r} breaks the asset_ prefix contract"
            )

    def test_catalog_icon_keys_are_subset_of_registered_asset_keys(self):
        """The 11 catalog-declared keys equal the 11 registered asset_ keys."""
        catalog_keys = {_CATALOG[c].icon_url_key for c in AssetCategory}
        assert catalog_keys == set(_ASSET_URL_KEYS)


# ---------------------------------------------------------------------------
# Idempotency + wholeness checks
# ---------------------------------------------------------------------------

class TestRegistrationShape:
    def test_register_urls_is_idempotent(self):
        """Calling ``register_urls()`` a second time does not change state."""
        before = dict(_STYLE_ICON_PATHS)
        register_urls()
        after = dict(_STYLE_ICON_PATHS)
        assert before == after

    def test_no_duplicate_asset_and_content_keys(self):
        """``asset_*`` and ``content_*`` key sets must not overlap."""
        overlap = set(_ASSET_URL_KEYS) & set(_CONTENT_URL_KEYS)
        assert not overlap, f"Unexpected key-name overlap: {overlap}"

    def test_all_step5_keys_present_in_path_map(self):
        """One-shot assert: every Step 5 key is present."""
        missing = [
            k for k in (_ASSET_URL_KEYS + _CONTENT_URL_KEYS)
            if k not in _STYLE_ICON_PATHS
        ]
        assert not missing, f"Not registered: {missing}"
