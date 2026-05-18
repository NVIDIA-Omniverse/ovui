# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 49 — prim-spec specifier icons + composition badges.

Covers:
  * :func:`layer_icons.specifier_icon` returns the registered PNG path
    per :class:`PrimSpecifier` value; every value has a mapping.
  * :func:`layer_icons.composition_badge` picks reference / payload
    according to the descriptor flags (payload takes priority).
  * :func:`layer_icons.instance_badge` only fires when the descriptor
    is marked instanceable.
  * :func:`layer_icons.provider` caches providers per path.
  * Delegate renders the icon widget for prim-spec rows without raising
    for every specifier + badge combination.
  * Icon registry carries the Step 49 entries so the URL name is stable
    for style callers.
  * Icon files on disk exist and are non-empty.
"""

from __future__ import annotations

import os

import omni.ui as ui
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.style.urls import _STYLE_ICON_PATHS, get_icon_path
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.layers import LayerDelegate, LayerItem, LayerModel, PrimSpecItem, layer_icons
from ovwidgets.layers.layer_model import DefaultLayerSettings

# ─── layer_icons lookup surface ──────────────────────────────────────────────


class TestSpecifierIconLookup:
    def test_every_specifier_has_an_icon(self) -> None:
        for spec in PrimSpecifier:
            assert layer_icons.specifier_icon(spec) is not None, spec

    def test_specifier_icons_are_distinct_per_kind(self) -> None:
        paths = {
            layer_icons.specifier_icon(s) for s in PrimSpecifier
        }
        assert len(paths) == len(list(PrimSpecifier))

    def test_specifier_icon_points_to_on_disk_file(self) -> None:
        for spec in PrimSpecifier:
            path = layer_icons.specifier_icon(spec)
            assert path is not None
            assert os.path.isfile(path), path
            assert os.path.getsize(path) > 0

    def test_specifier_icon_def_matches_registered_url(self) -> None:
        assert (
            layer_icons.specifier_icon(PrimSpecifier.DEF)
            == _STYLE_ICON_PATHS["prim_def"]
        )

    def test_specifier_icon_over_matches_registered_url(self) -> None:
        assert (
            layer_icons.specifier_icon(PrimSpecifier.OVER)
            == _STYLE_ICON_PATHS["prim_over"]
        )

    def test_specifier_icon_class_matches_registered_url(self) -> None:
        assert (
            layer_icons.specifier_icon(PrimSpecifier.CLASS)
            == _STYLE_ICON_PATHS["prim_class"]
        )


# ─── Composition + instance badges ───────────────────────────────────────────


def _descriptor(
    *,
    has_reference: bool = False,
    has_payload: bool = False,
    is_instanceable: bool = False,
) -> PrimSpecDescriptor:
    return PrimSpecDescriptor(
        path="/World",
        type_name="Xform",
        specifier=PrimSpecifier.DEF,
        has_reference=has_reference,
        has_payload=has_payload,
        is_instanceable=is_instanceable,
    )


class TestCompositionBadge:
    def test_neither_arc_returns_none(self) -> None:
        assert layer_icons.composition_badge(_descriptor()) is None

    def test_reference_only_picks_reference(self) -> None:
        path = layer_icons.composition_badge(_descriptor(has_reference=True))
        assert path == _STYLE_ICON_PATHS["badge_reference"]

    def test_payload_only_picks_payload(self) -> None:
        path = layer_icons.composition_badge(_descriptor(has_payload=True))
        assert path == _STYLE_ICON_PATHS["badge_payload"]

    def test_payload_takes_priority_over_reference(self) -> None:
        """Both flags set → payload wins (LAYERS-PLAN Step 49 ordering)."""
        path = layer_icons.composition_badge(
            _descriptor(has_reference=True, has_payload=True)
        )
        assert path == _STYLE_ICON_PATHS["badge_payload"]


class TestInstanceBadge:
    def test_non_instanceable_returns_none(self) -> None:
        assert layer_icons.instance_badge(_descriptor()) is None

    def test_instanceable_returns_badge(self) -> None:
        path = layer_icons.instance_badge(_descriptor(is_instanceable=True))
        assert path == _STYLE_ICON_PATHS["badge_instance"]

    def test_instance_badge_is_independent_of_composition(self) -> None:
        """A payload + instanceable descriptor returns both badges."""
        desc = _descriptor(has_payload=True, is_instanceable=True)
        assert layer_icons.composition_badge(desc) == _STYLE_ICON_PATHS[
            "badge_payload"
        ]
        assert layer_icons.instance_badge(desc) == _STYLE_ICON_PATHS[
            "badge_instance"
        ]


# ─── Provider caching ────────────────────────────────────────────────────────


class TestProviderCache:
    def test_same_path_returns_same_provider(self) -> None:
        path = _STYLE_ICON_PATHS["prim_def"]
        first = layer_icons.provider(path)
        second = layer_icons.provider(path)
        assert first is second

    def test_different_paths_return_different_providers(self) -> None:
        a = layer_icons.provider(_STYLE_ICON_PATHS["prim_def"])
        b = layer_icons.provider(_STYLE_ICON_PATHS["prim_over"])
        assert a is not b


# ─── URL registry ────────────────────────────────────────────────────────────


class TestIconRegistry:
    def test_prim_def_is_registered(self) -> None:
        assert "prim_def" in _STYLE_ICON_PATHS
        assert get_icon_path("prim_def").endswith("prim_def.png")

    def test_prim_over_is_registered(self) -> None:
        assert "prim_over" in _STYLE_ICON_PATHS
        assert get_icon_path("prim_over").endswith("prim_over.png")

    def test_prim_class_remains_registered(self) -> None:
        """Step 49 reuses the pre-existing Stage prim_class entry."""
        assert "prim_class" in _STYLE_ICON_PATHS
        assert get_icon_path("prim_class").endswith("prim_class.png")

    def test_prim_def_svg_ships_alongside_png(self) -> None:
        png_path = _STYLE_ICON_PATHS["prim_def"]
        svg_path = png_path[:-4] + ".svg"
        assert os.path.isfile(svg_path), svg_path
        assert os.path.getsize(svg_path) > 0

    def test_prim_over_svg_ships_alongside_png(self) -> None:
        png_path = _STYLE_ICON_PATHS["prim_over"]
        svg_path = png_path[:-4] + ".svg"
        assert os.path.isfile(svg_path), svg_path
        assert os.path.getsize(svg_path) > 0


# ─── Delegate rendering ──────────────────────────────────────────────────────


def _layer_item_on(adapter: MockLayerStackAdapter) -> LayerItem:
    return LayerItem(adapter, ROOT_LAYER_IDENTIFIER)


def _spec_item(
    layer: LayerItem,
    *,
    path: str = "/World",
    type_name: str = "Xform",
    specifier: PrimSpecifier = PrimSpecifier.DEF,
    has_reference: bool = False,
    has_payload: bool = False,
    is_instanceable: bool = False,
) -> PrimSpecItem:
    desc = PrimSpecDescriptor(
        path=path,
        type_name=type_name,
        specifier=specifier,
        has_reference=has_reference,
        has_payload=has_payload,
        is_instanceable=is_instanceable,
    )
    return PrimSpecItem(layer, desc)


class TestDelegatePrimSpecIconRender:
    def test_renders_for_def(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(layer, specifier=PrimSpecifier.DEF)
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_renders_for_over(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(layer, specifier=PrimSpecifier.OVER)
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_renders_for_class(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(layer, specifier=PrimSpecifier.CLASS)
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_renders_with_reference_badge(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(layer, has_reference=True)
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_renders_with_payload_badge(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(
            layer, specifier=PrimSpecifier.OVER, has_payload=True
        )
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_renders_with_instance_badge(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(layer, is_instanceable=True)
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_renders_with_all_badges(self) -> None:
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(
            layer,
            has_reference=True,
            has_payload=True,
            is_instanceable=True,
        )
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_falls_back_to_text_tag_when_registry_missing(
        self, monkeypatch
    ) -> None:
        """Unregistered icon → text tag fallback, no exception."""
        adapter = MockLayerStackAdapter()
        layer = _layer_item_on(adapter)
        item = _spec_item(layer, specifier=PrimSpecifier.DEF)
        monkeypatch.setattr(
            "ovwidgets.layers.layer_delegate.specifier_icon",
            lambda _spec: None,
        )
        delegate = LayerDelegate()
        with ui.VStack():
            delegate._build_prim_spec_icon(item)

    def test_build_widget_still_works_end_to_end(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER,
            "/World",
            type_name="Xform",
            has_reference=True,
        )
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER,
            "/Overrides",
            specifier=PrimSpecifier.CLASS,
        )
        settings = DefaultLayerSettings(show_layer_contents=True)
        model = LayerModel(adapter, settings=settings)
        try:
            root = model.root_item
            assert root is not None
            specs = [
                c
                for c in model.get_item_children(root)
                if isinstance(c, PrimSpecItem)
            ]
            assert specs
            delegate = LayerDelegate()
            with ui.VStack():
                for s in specs:
                    for col in range(model.get_item_value_model_count(s)):
                        delegate.build_widget(
                            model, s, col, level=1, expanded=False
                        )
        finally:
            model.destroy()
