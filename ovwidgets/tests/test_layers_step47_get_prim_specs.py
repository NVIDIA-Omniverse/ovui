# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 47 — ``get_prim_specs`` / ``has_prim_spec`` adapter extension.

Covers:
  * ABC: both methods are @abstractmethod.
  * Mock: empty layer returns ``[]``; seeded descriptors grouped by parent;
    nested paths; ``/`` default; ``has_prim_spec`` predicate semantics;
    unknown-layer / unknown-path raises.
  * USD: same semantics against a real ``Usd.Stage`` populated with
    ``UsdGeom.Xform`` / ``Cube`` prims with references + payloads.

Step 48 consumes :meth:`get_prim_specs` from the Layers model; Step 50
uses :meth:`has_prim_spec` to guard a DEL command before dispatch. Both
paths rely on the exact semantics asserted here, so weaker coverage
would let Step 48/50 regressions slip through.
"""

from __future__ import annotations

import pytest
from ovui_data_adapters.common import LayerStackAdapter, PrimSpecDescriptor, PrimSpecifier

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER

try:
    from pxr import Sdf, Usd, UsdGeom

    HAS_USD = True
except ImportError:
    HAS_USD = False


# ─── ABC conformance ─────────────────────────────────────────────────────────


class TestAbcContract:
    def test_get_prim_specs_is_abstract(self) -> None:
        assert "get_prim_specs" in LayerStackAdapter.__abstractmethods__

    def test_has_prim_spec_is_abstract(self) -> None:
        assert "has_prim_spec" in LayerStackAdapter.__abstractmethods__


# ─── Mock adapter ────────────────────────────────────────────────────────────


class TestMockGetPrimSpecs:
    def test_empty_layer_returns_empty_list(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER) == []

    def test_default_parent_path_is_slash(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        default = adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER)
        explicit = adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER, "/")
        assert default == explicit

    def test_returns_root_children_for_slash(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/Shader", type_name="Shader"
        )
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World/Cube", type_name="Cube"
        )
        roots = adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER, "/")
        paths = sorted(d.path for d in roots)
        assert paths == ["/Shader", "/World"]

    def test_returns_named_children_for_nested_parent(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World/Cube", type_name="Cube"
        )
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World/Sphere", type_name="Sphere"
        )
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World/Cube/Child", type_name="Cube"
        )
        children = adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER, "/World")
        paths = sorted(d.path for d in children)
        assert paths == ["/World/Cube", "/World/Sphere"]

    def test_deep_child_only_emitted_once(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/A")
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/A/B")
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/A/B/C")
        grand = adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER, "/A/B")
        assert [d.path for d in grand] == ["/A/B/C"]

    def test_descriptor_round_trip_preserves_all_fields(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER,
            "/World/Ref",
            type_name="Xform",
            specifier=PrimSpecifier.OVER,
            has_reference=True,
            has_payload=False,
            is_instanceable=True,
        )
        (descriptor,) = adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER, "/World")
        assert isinstance(descriptor, PrimSpecDescriptor)
        assert descriptor.path == "/World/Ref"
        assert descriptor.type_name == "Xform"
        assert descriptor.specifier is PrimSpecifier.OVER
        assert descriptor.has_reference is True
        assert descriptor.has_payload is False
        assert descriptor.is_instanceable is True

    def test_unknown_layer_raises_keyerror(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.get_prim_specs("no-such-layer", "/")

    def test_unknown_parent_path_raises_keyerror(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER, "/Missing")

    def test_existing_leaf_with_no_children_returns_empty(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World")
        assert adapter.get_prim_specs(ROOT_LAYER_IDENTIFIER, "/World") == []


class TestMockHasPrimSpec:
    def test_false_when_absent(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.has_prim_spec(ROOT_LAYER_IDENTIFIER, "/World") is False

    def test_true_when_present(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World")
        assert adapter.has_prim_spec(ROOT_LAYER_IDENTIFIER, "/World") is True

    def test_true_for_nested_path(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World/Cube")
        assert (
            adapter.has_prim_spec(ROOT_LAYER_IDENTIFIER, "/World/Cube")
            is True
        )

    def test_unknown_layer_raises_keyerror(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.has_prim_spec("no-such-layer", "/World")


# ─── USD adapter ─────────────────────────────────────────────────────────────

_SKIP_WITHOUT_USD = pytest.mark.skipif(
    not HAS_USD, reason="pxr (OpenUSD) not available"
)


if HAS_USD:  # Fixtures only make sense when pxr is importable.

    from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter

    from ovwidgets.common.undo import UndoManager

    @pytest.fixture
    def populated_adapter(tmp_path):
        """Stage with /World/Cube(def), /World/Sphere(over), /Overrides(class).

        /World/Cube carries an explicit reference; /World/Sphere carries an
        explicit payload. Exercises every field of :class:`PrimSpecDescriptor`
        so the USD adapter's projection is verified end-to-end.
        """
        stage = Usd.Stage.CreateInMemory("root.usda")
        UsdGeom.Xform.Define(stage, "/World")
        cube = UsdGeom.Cube.Define(stage, "/World/Cube")
        sphere_prim = stage.OverridePrim("/World/Sphere")
        stage.OverridePrim("/Overrides").SetSpecifier(Sdf.SpecifierClass)

        # Reference + payload on the root layer (author via Sdf.Layer API
        # rather than Usd.Prim so the edit lands on root unconditionally).
        root_layer = stage.GetRootLayer()
        cube_spec = root_layer.GetPrimAtPath("/World/Cube")
        cube_spec.referenceList.explicitItems.append(
            Sdf.Reference("./asset.usda", "/Asset")
        )
        sphere_spec = root_layer.GetPrimAtPath("/World/Sphere")
        sphere_spec.payloadList.explicitItems.append(
            Sdf.Payload("./asset.usda", "/Asset")
        )
        cube.GetPrim().SetInstanceable(True)
        del cube, sphere_prim

        return UsdLayerStackAdapter(stage, UndoManager())

    @pytest.fixture
    def empty_adapter():
        stage = Usd.Stage.CreateInMemory("root.usda")
        return UsdLayerStackAdapter(stage, UndoManager())


@_SKIP_WITHOUT_USD
class TestUsdGetPrimSpecs:
    def test_empty_layer_returns_empty_list(self, empty_adapter) -> None:
        root_id = empty_adapter.get_root_layer().identifier
        assert empty_adapter.get_prim_specs(root_id) == []

    def test_root_children_projected(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        roots = populated_adapter.get_prim_specs(root_id, "/")
        paths = sorted(d.path for d in roots)
        assert paths == ["/Overrides", "/World"]

    def test_nested_children_projected(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        children = populated_adapter.get_prim_specs(root_id, "/World")
        paths = sorted(d.path for d in children)
        assert paths == ["/World/Cube", "/World/Sphere"]

    def test_specifier_def_mapped(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        (cube,) = [
            d
            for d in populated_adapter.get_prim_specs(root_id, "/World")
            if d.path == "/World/Cube"
        ]
        assert cube.specifier is PrimSpecifier.DEF

    def test_specifier_over_mapped(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        (sphere,) = [
            d
            for d in populated_adapter.get_prim_specs(root_id, "/World")
            if d.path == "/World/Sphere"
        ]
        assert sphere.specifier is PrimSpecifier.OVER

    def test_specifier_class_mapped(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        (overrides,) = [
            d
            for d in populated_adapter.get_prim_specs(root_id, "/")
            if d.path == "/Overrides"
        ]
        assert overrides.specifier is PrimSpecifier.CLASS

    def test_type_name_populated(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        by_path = {
            d.path: d
            for d in populated_adapter.get_prim_specs(root_id, "/World")
        }
        assert by_path["/World/Cube"].type_name == "Cube"

    def test_has_reference_true_when_reference_authored(
        self, populated_adapter
    ) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        by_path = {
            d.path: d
            for d in populated_adapter.get_prim_specs(root_id, "/World")
        }
        assert by_path["/World/Cube"].has_reference is True
        # Sibling without a reference stays False.
        assert by_path["/World/Sphere"].has_reference is False

    def test_has_payload_true_when_payload_authored(
        self, populated_adapter
    ) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        by_path = {
            d.path: d
            for d in populated_adapter.get_prim_specs(root_id, "/World")
        }
        assert by_path["/World/Sphere"].has_payload is True
        assert by_path["/World/Cube"].has_payload is False

    def test_is_instanceable_reflects_flag(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        by_path = {
            d.path: d
            for d in populated_adapter.get_prim_specs(root_id, "/World")
        }
        assert by_path["/World/Cube"].is_instanceable is True
        assert by_path["/World/Sphere"].is_instanceable is False

    def test_unknown_layer_raises_keyerror(self, populated_adapter) -> None:
        with pytest.raises(KeyError):
            populated_adapter.get_prim_specs("no-such-layer")

    def test_unknown_parent_path_raises_keyerror(
        self, populated_adapter
    ) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        with pytest.raises(KeyError):
            populated_adapter.get_prim_specs(root_id, "/Missing")

    def test_existing_leaf_with_no_children_returns_empty(
        self, populated_adapter
    ) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        assert (
            populated_adapter.get_prim_specs(root_id, "/World/Cube") == []
        )


@_SKIP_WITHOUT_USD
class TestUsdHasPrimSpec:
    def test_root_path_true_on_empty_layer(self, empty_adapter) -> None:
        root_id = empty_adapter.get_root_layer().identifier
        assert empty_adapter.has_prim_spec(root_id, "/") is True

    def test_true_for_existing_spec(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        assert populated_adapter.has_prim_spec(root_id, "/World") is True
        assert (
            populated_adapter.has_prim_spec(root_id, "/World/Cube") is True
        )

    def test_false_for_missing_spec(self, populated_adapter) -> None:
        root_id = populated_adapter.get_root_layer().identifier
        assert populated_adapter.has_prim_spec(root_id, "/Missing") is False
        assert (
            populated_adapter.has_prim_spec(root_id, "/World/Nope") is False
        )

    def test_unknown_layer_raises_keyerror(self, populated_adapter) -> None:
        with pytest.raises(KeyError):
            populated_adapter.has_prim_spec("no-such-layer", "/")
