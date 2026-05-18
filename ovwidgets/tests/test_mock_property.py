# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for MockPropertyAdapter — in-memory PropertyAdapter for unit testing."""

import pytest
from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.app.testing import MockPropertyAdapter
from ovwidgets.common.testing.mock_property import MockPropertyAdapter as MockPropertyAdapterDirect


def _make_metadata(name: str, group: str = "Transform", type_name: str = "float") -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.replace("_", " ").title(),
        type_name=type_name,
        value_type=float,
        group=group,
    )


# ── ABC compliance ────────────────────────────────────────────────────────────

class TestPropertyAdapterABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            PropertyAdapter()  # type: ignore[abstract]

    def test_mock_is_subclass(self):
        assert issubclass(MockPropertyAdapter, PropertyAdapter)

    def test_instance_check(self):
        adapter = MockPropertyAdapter()
        assert isinstance(adapter, PropertyAdapter)

    def test_import_from_testing_package(self):
        assert MockPropertyAdapter is MockPropertyAdapterDirect


# ── Constructor ───────────────────────────────────────────────────────────────

class TestMockPropertyAdapterInit:
    def test_default_init(self):
        adapter = MockPropertyAdapter()
        assert adapter.get_paths() == []
        assert adapter.get_attribute_names() == []

    def test_init_with_paths(self):
        adapter = MockPropertyAdapter(paths=["/World/Cube", "/World/Sphere"])
        assert adapter.get_paths() == ["/World/Cube", "/World/Sphere"]

    def test_init_with_attributes(self):
        attrs = {"xformOp:translate": _make_metadata("xformOp:translate")}
        adapter = MockPropertyAdapter(attributes=attrs)
        assert "xformOp:translate" in adapter.get_attribute_names()

    def test_init_paths_copied(self):
        original = ["/World/A"]
        adapter = MockPropertyAdapter(paths=original)
        original.append("/World/B")
        assert adapter.get_paths() == ["/World/A"]

    def test_init_attributes_copied(self):
        meta = _make_metadata("attr")
        attrs = {"attr": meta}
        adapter = MockPropertyAdapter(attributes=attrs)
        attrs["other"] = _make_metadata("other")
        assert "other" not in adapter.get_attribute_names()

    def test_edits_empty_on_init(self):
        adapter = MockPropertyAdapter()
        assert adapter._edits == []

    def test_subscribers_empty_on_init(self):
        adapter = MockPropertyAdapter()
        assert adapter._subscribers == []


# ── get_paths / is_valid ──────────────────────────────────────────────────────

class TestGetPaths:
    def test_get_paths_empty(self):
        adapter = MockPropertyAdapter()
        assert adapter.get_paths() == []

    def test_get_paths_returns_list(self):
        adapter = MockPropertyAdapter(paths=["/A"])
        result = adapter.get_paths()
        assert isinstance(result, list)

    def test_get_paths_returns_copy(self):
        adapter = MockPropertyAdapter(paths=["/A"])
        result = adapter.get_paths()
        result.append("/B")
        assert adapter.get_paths() == ["/A"]

    def test_is_valid_always_true(self):
        adapter = MockPropertyAdapter()
        assert adapter.is_valid() is True

    def test_is_valid_with_paths(self):
        adapter = MockPropertyAdapter(paths=["/World/Cube"])
        assert adapter.is_valid() is True


# ── Attribute names and metadata ─────────────────────────────────────────────

class TestAttributes:
    def test_get_attribute_names_empty(self):
        adapter = MockPropertyAdapter()
        assert adapter.get_attribute_names() == []

    def test_get_attribute_names_returns_keys(self):
        attrs = {
            "xformOp:translate": _make_metadata("xformOp:translate"),
            "xformOp:scale": _make_metadata("xformOp:scale"),
        }
        adapter = MockPropertyAdapter(attributes=attrs)
        names = adapter.get_attribute_names()
        assert set(names) == {"xformOp:translate", "xformOp:scale"}

    def test_get_attribute_metadata_returns_correct_entry(self):
        meta = _make_metadata("visibility", group="Render")
        adapter = MockPropertyAdapter(attributes={"visibility": meta})
        result = adapter.get_attribute_metadata("visibility")
        assert result is meta

    def test_get_attribute_metadata_missing_raises(self):
        adapter = MockPropertyAdapter()
        with pytest.raises(KeyError):
            adapter.get_attribute_metadata("nonexistent")

    def test_is_ambiguous_always_false(self):
        adapter = MockPropertyAdapter()
        assert adapter.is_ambiguous("any_attr") is False

    def test_get_per_component_ambiguity_unknown_returns_none(self):
        adapter = MockPropertyAdapter()
        assert adapter.get_per_component_ambiguity("any_attr") is None


# ── get_value / set_value ─────────────────────────────────────────────────────

class TestGetSetValue:
    def test_get_value_unset_returns_none(self):
        adapter = MockPropertyAdapter()
        assert adapter.get_value("missing") is None

    def test_set_then_get_value(self):
        adapter = MockPropertyAdapter()
        adapter.set_value("color", (1.0, 0.5, 0.0))
        assert adapter.get_value("color") == (1.0, 0.5, 0.0)

    def test_set_value_overwrites(self):
        adapter = MockPropertyAdapter()
        adapter.set_value("intensity", 1.0)
        adapter.set_value("intensity", 2.5)
        assert adapter.get_value("intensity") == pytest.approx(2.5)

    def test_set_value_int(self):
        adapter = MockPropertyAdapter()
        adapter.set_value("count", 42)
        assert adapter.get_value("count") == 42

    def test_set_value_string(self):
        adapter = MockPropertyAdapter()
        adapter.set_value("name", "ground")
        assert adapter.get_value("name") == "ground"

    def test_set_value_none(self):
        adapter = MockPropertyAdapter()
        adapter.set_value("field", None)
        assert adapter.get_value("field") is None

    def test_multiple_attrs_independent(self):
        adapter = MockPropertyAdapter()
        adapter.set_value("x", 1.0)
        adapter.set_value("y", 2.0)
        assert adapter.get_value("x") == pytest.approx(1.0)
        assert adapter.get_value("y") == pytest.approx(2.0)


# ── begin_edit / end_edit tracking ───────────────────────────────────────────

class TestEditTracking:
    def test_begin_edit_recorded(self):
        adapter = MockPropertyAdapter()
        adapter.begin_edit("xformOp:translate")
        assert ("begin", "xformOp:translate") in adapter._edits

    def test_end_edit_recorded(self):
        adapter = MockPropertyAdapter()
        adapter.end_edit("xformOp:translate")
        assert ("end", "xformOp:translate") in adapter._edits

    def test_edit_lifecycle_order(self):
        adapter = MockPropertyAdapter()
        adapter.begin_edit("attr")
        adapter.end_edit("attr")
        assert adapter._edits == [("begin", "attr"), ("end", "attr")]

    def test_multiple_edits_accumulate(self):
        adapter = MockPropertyAdapter()
        adapter.begin_edit("a")
        adapter.begin_edit("b")
        adapter.end_edit("a")
        adapter.end_edit("b")
        assert len(adapter._edits) == 4
        assert adapter._edits[0] == ("begin", "a")
        assert adapter._edits[1] == ("begin", "b")
        assert adapter._edits[2] == ("end", "a")
        assert adapter._edits[3] == ("end", "b")

    def test_begin_without_end_tracked(self):
        adapter = MockPropertyAdapter()
        adapter.begin_edit("dangling")
        assert len(adapter._edits) == 1
        assert adapter._edits[0] == ("begin", "dangling")

    def test_edits_list_is_ordered(self):
        adapter = MockPropertyAdapter()
        for i in range(5):
            adapter.begin_edit(f"attr{i}")
        assert [e[1] for e in adapter._edits] == [f"attr{i}" for i in range(5)]


# ── subscribe_changes ────────────────────────────────────────────────────────

class TestSubscribeChanges:
    def test_subscribe_returns_subscription(self):
        from ovwidgets.common.testing.mock_property import _MockPropertySubscription
        adapter = MockPropertyAdapter()
        sub = adapter.subscribe_changes(lambda: None)
        assert isinstance(sub, _MockPropertySubscription)

    def test_fire_change_calls_subscriber(self):
        adapter = MockPropertyAdapter()
        calls = []
        sub = adapter.subscribe_changes(lambda: calls.append(1))  # noqa: F841 — hold ref
        adapter.fire_change()
        assert calls == [1]

    def test_fire_change_multiple_subscribers(self):
        adapter = MockPropertyAdapter()
        calls = []
        sub_a = adapter.subscribe_changes(lambda: calls.append("a"))  # noqa: F841
        sub_b = adapter.subscribe_changes(lambda: calls.append("b"))  # noqa: F841
        adapter.fire_change()
        assert len(calls) == 2
        assert "a" in calls
        assert "b" in calls

    def test_subscription_cancel_removes_subscriber(self):
        adapter = MockPropertyAdapter()
        calls = []
        sub = adapter.subscribe_changes(lambda: calls.append(1))
        sub.cancel()
        adapter.fire_change()
        assert calls == []

    def test_cancel_idempotent(self):
        adapter = MockPropertyAdapter()
        sub = adapter.subscribe_changes(lambda: None)
        sub.cancel()
        sub.cancel()  # Must not raise

    def test_subscribe_no_change_no_call(self):
        adapter = MockPropertyAdapter()
        calls = []
        adapter.subscribe_changes(lambda: calls.append(1))
        assert calls == []


# ── get_per_component_ambiguity — vector/scalar detection (Step 2.1) ─────────

class TestPerComponentAmbiguity:
    def test_vec3_only_x_differs_returns_true_false_false(self):
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"],
            attributes={"xformOp:translate": _make_metadata("xformOp:translate", type_name="float3")},
        )
        adapter.set_path_value("/A", "xformOp:translate", (1.0, 0.0, 0.0))
        adapter.set_path_value("/B", "xformOp:translate", (5.0, 0.0, 0.0))
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [True, False, False]

    def test_vec3_only_z_differs_returns_false_false_true(self):
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"],
            attributes={"xformOp:translate": _make_metadata("xformOp:translate", type_name="float3")},
        )
        adapter.set_path_value("/A", "xformOp:translate", (1.0, 0.0, 0.0))
        adapter.set_path_value("/B", "xformOp:translate", (1.0, 0.0, 5.0))
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [False, False, True]

    def test_vec3_all_components_differ_returns_all_true(self):
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"],
            attributes={"xformOp:translate": _make_metadata("xformOp:translate", type_name="float3")},
        )
        adapter.set_path_value("/A", "xformOp:translate", (1.0, 2.0, 3.0))
        adapter.set_path_value("/B", "xformOp:translate", (4.0, 5.0, 6.0))
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [True, True, True]

    def test_vec3_all_components_equal_returns_all_false(self):
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"],
            attributes={"xformOp:translate": _make_metadata("xformOp:translate", type_name="float3")},
        )
        adapter.set_path_value("/A", "xformOp:translate", (1.0, 2.0, 3.0))
        adapter.set_path_value("/B", "xformOp:translate", (1.0, 2.0, 3.0))
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [False, False, False]

    def test_scalar_float_returns_none(self):
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"],
            attributes={"radius": _make_metadata("radius", type_name="float")},
        )
        adapter.set_path_value("/A", "radius", 1.0)
        adapter.set_path_value("/B", "radius", 2.0)
        assert adapter.get_per_component_ambiguity("radius") is None

    def test_scalar_string_returns_none(self):
        adapter = MockPropertyAdapter(
            paths=["/A", "/B"],
            attributes={"visibility": _make_metadata("visibility", type_name="token")},
        )
        adapter.set_path_value("/A", "visibility", "inherited")
        adapter.set_path_value("/B", "visibility", "invisible")
        assert adapter.get_per_component_ambiguity("visibility") is None

    def test_single_path_vector_returns_all_false(self):
        adapter = MockPropertyAdapter(
            paths=["/A"],
            attributes={"xformOp:translate": _make_metadata("xformOp:translate", type_name="float3")},
        )
        adapter.set_path_value("/A", "xformOp:translate", (1.0, 2.0, 3.0))
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [False, False, False]


# ── get_scheme ────────────────────────────────────────────────────────────────

class TestGetScheme:
    def test_scheme_is_mock(self):
        adapter = MockPropertyAdapter()
        assert adapter.get_scheme() == "mock"

    def test_scheme_is_string(self):
        adapter = MockPropertyAdapter()
        assert isinstance(adapter.get_scheme(), str)


# ── get_resolved_asset_path (Step 3.6) ────────────────────────────────────────

class TestResolvedAssetPath:
    """Step 3.6: the mock adapter surfaces a per-attribute resolved-path
    dict via :meth:`MockPropertyAdapter.get_resolved_asset_path`, seeded
    by :meth:`set_resolved_asset_path`. The row uses the resolved path
    as a StringField tooltip (property metadata behavior)."""

    def test_default_returns_none(self):
        """Unseeded attribute returns ``None`` — matches the
        :class:`PropertyAdapter` ABC default."""
        adapter = MockPropertyAdapter()
        assert adapter.get_resolved_asset_path("tex") is None

    def test_set_resolved_path_round_trip(self):
        adapter = MockPropertyAdapter()
        adapter.set_resolved_asset_path("tex", "/abs/root/textures/noise.png")
        assert adapter.get_resolved_asset_path("tex") == "/abs/root/textures/noise.png"

    def test_set_resolved_path_coerces_to_string(self):
        """Non-string inputs roundtrip through ``str()`` so callers passing
        :class:`pathlib.Path` or USD path types get consistent storage."""
        from pathlib import PurePosixPath
        adapter = MockPropertyAdapter()
        adapter.set_resolved_asset_path("tex", PurePosixPath("/abs/x.png"))
        resolved = adapter.get_resolved_asset_path("tex")
        assert isinstance(resolved, str)
        assert resolved == "/abs/x.png"

    def test_set_resolved_path_none_clears_entry(self):
        adapter = MockPropertyAdapter()
        adapter.set_resolved_asset_path("tex", "/abs/a.png")
        adapter.set_resolved_asset_path("tex", None)
        assert adapter.get_resolved_asset_path("tex") is None

    def test_different_attrs_track_independently(self):
        adapter = MockPropertyAdapter()
        adapter.set_resolved_asset_path("tex_a", "/abs/a.png")
        adapter.set_resolved_asset_path("tex_b", "/abs/b.png")
        assert adapter.get_resolved_asset_path("tex_a") == "/abs/a.png"
        assert adapter.get_resolved_asset_path("tex_b") == "/abs/b.png"
        # Clearing one leaves the other alone.
        adapter.set_resolved_asset_path("tex_a", None)
        assert adapter.get_resolved_asset_path("tex_a") is None
        assert adapter.get_resolved_asset_path("tex_b") == "/abs/b.png"
