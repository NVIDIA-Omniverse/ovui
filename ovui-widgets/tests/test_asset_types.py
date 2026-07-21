# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :mod:`ovui_widgets.common.asset_types`.

See the content browser implementation step 4. Covers the :class:`AssetCategory` enum, the
:class:`AssetTypeDef` frozen dataclass, the built-in catalog, and the
public lookup / registration functions.

Extension round-trip tests drive from ``_CATALOG`` directly so no
parallel "expected" table exists to drift. Case-insensitive matching
and dotted variants (``.geo.usd``) are verified.
``register_extensions`` exercises add / case-normalisation /
idempotency / cross-category collision / FOLDER+UNKNOWN rejection.
The ``catalog_snapshot`` fixture restores the full catalog after any
mutation so later tests start from a pristine state.
"""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from ovui_widgets.common import asset_types
from ovui_widgets.common.asset_types import (
    _CATALOG,
    AssetCategory,
    AssetTypeDef,
    categories,
    get_category,
    get_display_name,
    get_icon_url_key,
    is_asset_category,
    register_extensions,
)

# ──────────────────────────────────────────────────────────────────────────────
# Module surface
# ──────────────────────────────────────────────────────────────────────────────

class TestImport:
    def test_public_symbols_importable(self):
        assert AssetCategory is asset_types.AssetCategory
        assert AssetTypeDef is asset_types.AssetTypeDef
        assert get_category is asset_types.get_category
        assert get_display_name is asset_types.get_display_name
        assert get_icon_url_key is asset_types.get_icon_url_key
        assert is_asset_category is asset_types.is_asset_category
        assert register_extensions is asset_types.register_extensions
        assert categories is asset_types.categories

    def test_ovui_widgets_exports_are_services_objects(self):
        from ovui_data_adapters.services.content import asset_types as services_asset_types

        assert AssetCategory is services_asset_types.AssetCategory
        assert AssetTypeDef is services_asset_types.AssetTypeDef
        assert _CATALOG is services_asset_types._CATALOG
        assert get_category is services_asset_types.get_category
        assert get_display_name is services_asset_types.get_display_name
        assert get_icon_url_key is services_asset_types.get_icon_url_key
        assert is_asset_category is services_asset_types.is_asset_category
        assert register_extensions is services_asset_types.register_extensions
        assert categories is services_asset_types.categories

    def test_services_import_has_no_ui_or_ovui_widgets_dependency(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from ovui_data_adapters.services.content.asset_types "
                    "import AssetCategory, get_category; "
                    "forbidden = [name for name in sys.modules "
                    "if name == 'ovui_widgets' or name.startswith('ovui_widgets.') "
                    "or name == 'omni' or name.startswith('omni.')]; "
                    "print(get_category('file.usd').name, AssetCategory.USD.name, forbidden); "
                    "raise SystemExit(1 if forbidden else 0)"
                ),
            ],
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, (
            "services asset classification must import without ovui-widgets "
            "or omni runtime modules:\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
        assert "USD USD []" in proc.stdout

    def test_module_has_no_heavy_deps(self):
        # Importing the catalog must not drag in omni.ui, backends,
        # or any filesystem access. A `from omni.ui import url` would
        # expose `url` on the module; `import omni.ui` would expose
        # `omni`; similarly for the backends package.
        forbidden = {"omni", "ui", "url", "backends", "ovui_widgets"}
        leaked = forbidden.intersection(vars(asset_types).keys())
        assert leaked == set(), f"asset_types leaked heavy deps: {leaked}"


# ──────────────────────────────────────────────────────────────────────────────
# AssetCategory enum
# ──────────────────────────────────────────────────────────────────────────────

_EXPECTED_ENUM_VALUES = [
    (AssetCategory.FOLDER, "folder"),
    (AssetCategory.USD, "usd"),
    (AssetCategory.IMAGE, "image"),
    (AssetCategory.MATERIAL, "material"),
    (AssetCategory.MODEL, "model"),
    (AssetCategory.SOUND, "sound"),
    (AssetCategory.SCRIPT, "script"),
    (AssetCategory.VOLUME, "volume"),
    (AssetCategory.TEXT, "text"),
    (AssetCategory.ARCHIVE, "archive"),
    (AssetCategory.UNKNOWN, "unknown"),
]


class TestAssetCategoryEnum:
    def test_all_11_members_present(self):
        names = {c.name for c in AssetCategory}
        assert names == {
            "FOLDER", "USD", "IMAGE", "MATERIAL", "MODEL",
            "SOUND", "SCRIPT", "VOLUME", "TEXT", "ARCHIVE", "UNKNOWN",
        }

    @pytest.mark.parametrize("member,value", _EXPECTED_ENUM_VALUES)
    def test_enum_member_value(self, member, value):
        assert member.value == value

    def test_members_distinct(self):
        values = [c.value for c in AssetCategory]
        assert len(values) == len(set(values))


# ──────────────────────────────────────────────────────────────────────────────
# AssetTypeDef dataclass
# ──────────────────────────────────────────────────────────────────────────────

class TestAssetTypeDef:
    def _def(self):
        return AssetTypeDef(
            category=AssetCategory.IMAGE,
            display_name="Image",
            icon_url_key="asset_image",
            extensions=(".png", ".jpg"),
        )

    def test_fields_preserved(self):
        d = self._def()
        assert d.category is AssetCategory.IMAGE
        assert d.display_name == "Image"
        assert d.icon_url_key == "asset_image"
        assert d.extensions == (".png", ".jpg")

    @pytest.mark.parametrize(
        "field,value",
        [
            ("category", AssetCategory.SOUND),
            ("display_name", "changed"),
            ("icon_url_key", "changed"),
            ("extensions", ()),
        ],
    )
    def test_is_frozen(self, field, value):
        d = self._def()
        with pytest.raises(FrozenInstanceError):
            setattr(d, field, value)

    def test_equality_by_value(self):
        a = self._def()
        b = AssetTypeDef(
            category=AssetCategory.IMAGE,
            display_name="Image",
            icon_url_key="asset_image",
            extensions=(".png", ".jpg"),
        )
        assert a == b

    def test_hashable(self):
        d = self._def()
        assert hash(d) == hash(self._def())


# ──────────────────────────────────────────────────────────────────────────────
# Catalog structure
# ──────────────────────────────────────────────────────────────────────────────

class TestCatalog:
    def test_every_category_has_a_def(self):
        for cat in AssetCategory:
            assert cat in _CATALOG, f"{cat.name} missing from catalog"

    def test_catalog_has_no_extra_keys(self):
        extra = set(_CATALOG.keys()) - set(AssetCategory)
        assert extra == set()

    @pytest.mark.parametrize("category", list(AssetCategory))
    def test_def_category_matches_key(self, category):
        assert _CATALOG[category].category is category

    def test_every_non_sentinel_extension_has_leading_dot(self):
        for cat, type_def in _CATALOG.items():
            for ext in type_def.extensions:
                assert ext.startswith("."), (
                    f"{cat.name} extension {ext!r} is missing leading dot"
                )

    def test_every_extension_is_lowercase(self):
        for cat, type_def in _CATALOG.items():
            for ext in type_def.extensions:
                assert ext == ext.lower(), (
                    f"{cat.name} extension {ext!r} is not lowercase"
                )

    def test_no_extension_appears_in_two_categories(self):
        seen: dict = {}
        for cat, type_def in _CATALOG.items():
            for ext in type_def.extensions:
                assert ext not in seen, (
                    f"Extension {ext!r} is in both "
                    f"{seen[ext].name} and {cat.name}"
                )
                seen[ext] = cat

    def test_folder_has_no_extensions(self):
        assert _CATALOG[AssetCategory.FOLDER].extensions == ()

    def test_unknown_has_no_extensions(self):
        assert _CATALOG[AssetCategory.UNKNOWN].extensions == ()


# ──────────────────────────────────────────────────────────────────────────────
# get_category
# ──────────────────────────────────────────────────────────────────────────────

def _iter_ext_category_pairs():
    """Yield ``(extension, category)`` for every cataloged extension."""
    for cat, type_def in _CATALOG.items():
        if cat is AssetCategory.FOLDER or cat is AssetCategory.UNKNOWN:
            continue
        for ext in type_def.extensions:
            yield ext, cat


class TestGetCategoryExtensions:
    """Round-trip every cataloged extension through ``get_category``."""

    @pytest.mark.parametrize(
        "ext,expected",
        list(_iter_ext_category_pairs()),
    )
    def test_extension_maps_to_expected_category(self, ext, expected):
        assert get_category(f"file{ext}") == expected

    @pytest.mark.parametrize(
        "ext,expected",
        list(_iter_ext_category_pairs()),
    )
    def test_uppercase_extension_maps_same(self, ext, expected):
        assert get_category(f"FILE{ext.upper()}") == expected


class TestGetCategoryCaseInsensitivity:
    def test_pure_uppercase_usd(self):
        assert get_category("foo.USD") is AssetCategory.USD

    def test_mixed_case_usd(self):
        assert get_category("foo.Usd") is AssetCategory.USD

    def test_mixed_case_png(self):
        assert get_category("Shot_A.Png") is AssetCategory.IMAGE

    def test_all_upper_mdl(self):
        assert get_category("LOOKS/BRICK.MDL") is AssetCategory.MATERIAL


class TestGetCategoryDottedUsd:
    def test_geo_usd(self):
        assert get_category("prop.geo.usd") is AssetCategory.USD

    def test_anim_usd(self):
        assert get_category("char.anim.usd") is AssetCategory.USD

    def test_cache_usdc(self):
        assert get_category("sim.cache.usdc") is AssetCategory.USD

    def test_multi_dot_usd(self):
        assert get_category("shot01.v002.geo.usda") is AssetCategory.USD

    def test_dotted_with_upper(self):
        assert get_category("Prop.Geo.USD") is AssetCategory.USD


class TestGetCategoryUnknownFallback:
    def test_random_extension(self):
        assert get_category("foo.xyz") is AssetCategory.UNKNOWN

    def test_no_extension(self):
        assert get_category("README") is AssetCategory.UNKNOWN

    def test_empty_string(self):
        assert get_category("") is AssetCategory.UNKNOWN

    def test_just_a_dot(self):
        assert get_category(".") is AssetCategory.UNKNOWN

    def test_bare_dot_prefix_is_not_usd(self):
        # ``.usdrc`` is not one of ours — not a USD, not anything.
        assert get_category("foo.usdrc") is AssetCategory.UNKNOWN

    def test_trailing_dot_no_extension(self):
        assert get_category("name.") is AssetCategory.UNKNOWN

    def test_extension_substring_does_not_match(self):
        # ``.pythonsource`` does not end in ``.py`` despite containing
        # the letters; ``endswith`` is dot-boundary-respecting.
        assert get_category("file.pythonsource") is AssetCategory.UNKNOWN


class TestGetCategoryUrlInputs:
    def test_file_url(self):
        assert get_category("file:///tmp/foo.png") is AssetCategory.IMAGE

    def test_mock_url(self):
        assert get_category("mock://Home/Scenes/Kitchen.usda") is AssetCategory.USD

    def test_http_url(self):
        assert (
            get_category("http://example.com/asset.fbx") is AssetCategory.MODEL
        )

    def test_url_with_query_string_not_matched(self):
        # Query strings break the ``endswith`` contract — callers are
        # expected to strip them, so this documents the current
        # behaviour rather than silently matching.
        assert (
            get_category("http://ex.com/a.png?ver=1") is AssetCategory.UNKNOWN
        )

    def test_folder_is_not_auto_detected(self):
        # A folder named ``Home`` has no extension, so falls back to
        # UNKNOWN — folders are dispatched by backend flag, never by
        # ``get_category``.
        assert get_category("Home") is AssetCategory.UNKNOWN


# ──────────────────────────────────────────────────────────────────────────────
# get_display_name
# ──────────────────────────────────────────────────────────────────────────────

class TestGetDisplayName:
    def test_png_is_image(self):
        assert get_display_name("shot.png") == "Image"

    def test_usd_variant(self):
        assert get_display_name("prop.geo.usd") == "USD File"

    def test_py_is_python_script(self):
        assert get_display_name("tools/build.py") == "Python Script"

    def test_obj_is_3d_model(self):
        assert get_display_name("props/lamp.obj") == "3D Model"

    def test_mp3_is_audio(self):
        assert get_display_name("bgm.mp3") == "Audio"

    def test_unknown_returns_file(self):
        assert get_display_name("data.xyz") == "File"

    def test_empty_returns_file(self):
        assert get_display_name("") == "File"


# ──────────────────────────────────────────────────────────────────────────────
# get_icon_url_key
# ──────────────────────────────────────────────────────────────────────────────

class TestGetIconUrlKey:
    def test_png(self):
        assert get_icon_url_key("a.png") == "asset_image"

    def test_usd(self):
        assert get_icon_url_key("s.usd") == "asset_usd"

    def test_fbx(self):
        assert get_icon_url_key("s.fbx") == "asset_model"

    def test_mdl(self):
        assert get_icon_url_key("brick.mdl") == "asset_material"

    def test_mtlx(self):
        assert get_icon_url_key("brick.mtlx") == "asset_material"

    def test_wav(self):
        assert get_icon_url_key("bgm.wav") == "asset_sound"

    def test_py(self):
        assert get_icon_url_key("run.py") == "asset_script"

    def test_vdb(self):
        assert get_icon_url_key("smoke.vdb") == "asset_volume"

    def test_md(self):
        assert get_icon_url_key("README.md") == "asset_text"

    def test_zip(self):
        assert get_icon_url_key("release.zip") == "asset_archive"

    def test_unknown(self):
        assert get_icon_url_key("random.xyz") == "asset_unknown"


# ──────────────────────────────────────────────────────────────────────────────
# is_asset_category
# ──────────────────────────────────────────────────────────────────────────────

class TestIsAssetCategory:
    def test_matching_category_true(self):
        assert is_asset_category("scene.usd", AssetCategory.USD) is True

    def test_non_matching_category_false(self):
        assert is_asset_category("scene.usd", AssetCategory.IMAGE) is False

    def test_case_insensitive(self):
        assert (
            is_asset_category("PHOTO.JPEG", AssetCategory.IMAGE) is True
        )

    def test_unknown_ext_matches_unknown_category(self):
        assert (
            is_asset_category("thing.xyz", AssetCategory.UNKNOWN) is True
        )

    def test_folder_never_matches_via_filename(self):
        # Folders are flag-dispatched; a filename can never satisfy
        # AssetCategory.FOLDER through this function.
        assert (
            is_asset_category("anything.usd", AssetCategory.FOLDER) is False
        )
        assert is_asset_category("Home", AssetCategory.FOLDER) is False


# ──────────────────────────────────────────────────────────────────────────────
# register_extensions — mutating; each test restores the catalog.
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def catalog_snapshot():
    """Save and restore the full catalog around a mutating test."""
    original = dict(_CATALOG)
    yield original
    _CATALOG.clear()
    _CATALOG.update(original)


class TestRegisterExtensions:
    def test_adds_new_extension(self, catalog_snapshot):
        register_extensions(AssetCategory.IMAGE, [".heic"])
        assert ".heic" in _CATALOG[AssetCategory.IMAGE].extensions
        assert get_category("photo.heic") is AssetCategory.IMAGE

    def test_adds_multiple_extensions(self, catalog_snapshot):
        register_extensions(AssetCategory.IMAGE, [".heic", ".avif"])
        exts = _CATALOG[AssetCategory.IMAGE].extensions
        assert ".heic" in exts
        assert ".avif" in exts

    def test_existing_extensions_are_preserved(self, catalog_snapshot):
        original = catalog_snapshot[AssetCategory.IMAGE].extensions
        register_extensions(AssetCategory.IMAGE, [".heic"])
        new = _CATALOG[AssetCategory.IMAGE].extensions
        for ext in original:
            assert ext in new

    def test_uppercase_input_is_normalised(self, catalog_snapshot):
        register_extensions(AssetCategory.IMAGE, [".HEIC"])
        assert ".heic" in _CATALOG[AssetCategory.IMAGE].extensions
        # Uppercase source string also matches the lowercase stored ext.
        assert get_category("photo.HEIC") is AssetCategory.IMAGE

    def test_idempotent_add_does_not_duplicate(self, catalog_snapshot):
        before = _CATALOG[AssetCategory.IMAGE].extensions
        # ``.png`` is already registered; adding again must not grow the
        # tuple nor raise.
        register_extensions(AssetCategory.IMAGE, [".png"])
        after = _CATALOG[AssetCategory.IMAGE].extensions
        assert after == before

    def test_preserves_display_name_and_icon_key(
        self, catalog_snapshot
    ):
        before = _CATALOG[AssetCategory.IMAGE]
        register_extensions(AssetCategory.IMAGE, [".heic"])
        after = _CATALOG[AssetCategory.IMAGE]
        assert after.display_name == before.display_name
        assert after.icon_url_key == before.icon_url_key
        assert after.category is before.category

    def test_accepts_tuple_iterable(self, catalog_snapshot):
        register_extensions(AssetCategory.IMAGE, (".heic",))
        assert ".heic" in _CATALOG[AssetCategory.IMAGE].extensions

    def test_accepts_generator_iterable(self, catalog_snapshot):
        register_extensions(
            AssetCategory.IMAGE, (e for e in [".heic"])
        )
        assert ".heic" in _CATALOG[AssetCategory.IMAGE].extensions

    def test_missing_leading_dot_raises(self, catalog_snapshot):
        with pytest.raises(ValueError, match="leading dot"):
            register_extensions(AssetCategory.IMAGE, ["heic"])

    def test_collision_with_other_category_raises(
        self, catalog_snapshot
    ):
        # ``.py`` already owned by SCRIPT — cannot steal it for IMAGE.
        with pytest.raises(ValueError, match="already registered"):
            register_extensions(AssetCategory.IMAGE, [".py"])

    def test_collision_is_atomic(self, catalog_snapshot):
        # If one extension in the batch collides, nothing should be
        # added — even the non-colliding ones.
        original = _CATALOG[AssetCategory.IMAGE].extensions
        with pytest.raises(ValueError):
            register_extensions(AssetCategory.IMAGE, [".heic", ".py"])
        assert _CATALOG[AssetCategory.IMAGE].extensions == original

    def test_rejects_folder(self):
        with pytest.raises(ValueError, match="FOLDER"):
            register_extensions(AssetCategory.FOLDER, [".anything"])

    def test_rejects_unknown(self):
        with pytest.raises(ValueError, match="UNKNOWN"):
            register_extensions(AssetCategory.UNKNOWN, [".anything"])

    def test_empty_iterable_is_noop(self, catalog_snapshot):
        before = _CATALOG[AssetCategory.IMAGE].extensions
        register_extensions(AssetCategory.IMAGE, [])
        assert _CATALOG[AssetCategory.IMAGE].extensions == before


# ──────────────────────────────────────────────────────────────────────────────
# categories()
# ──────────────────────────────────────────────────────────────────────────────

class TestCategories:
    def test_returns_all_11_categories(self):
        result = categories()
        assert len(result) == 11
        assert set(result) == set(AssetCategory)

    def test_returns_a_list(self):
        assert isinstance(categories(), list)

    def test_returns_fresh_copy(self):
        a = categories()
        b = categories()
        assert a == b
        assert a is not b

    def test_mutating_result_does_not_affect_catalog(self):
        result = categories()
        result.clear()
        # Next call must still return the full list.
        assert len(categories()) == 11

    def test_order_matches_catalog_insertion_order(self):
        # The public documentation says "catalog order" — verify the
        # ordering is deterministic and matches the internal dict.
        assert categories() == list(_CATALOG.keys())
