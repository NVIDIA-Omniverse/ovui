# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the :class:`UiDisplayGroup` tree — Step 5.1.

the property inspector 5.1 done-signal matrix:

* A prop with group ``"A.B.C"`` (path_parts = ``["A", "B", "C"]``)
  produces three levels of nested sub-groups.
* :meth:`get_children` yields sub-groups before props.
* Multiple props at the same group path collapse into one sub-group's
  :attr:`props` list.
* Props at different nesting depths coexist cleanly.
* Empty path_parts (no group / root-level prop) appends to the root's
  :attr:`props`.
* A second prop targeting an already-existing sub-group reuses that
  sub-group instead of creating a parallel sibling.

Plus a handful of anchors the implementation notes reference directly: insertion-order
iteration for sub-groups (so ``_customize_props_layout`` ordering can
flow through later phases unchanged), independence of separate
:class:`UiDisplayGroup` instances (the ``field(default_factory=...)``
pattern guards against the shared-mutable-default trap), and
:attr:`collapsed` defaulting to ``False`` on auto-created sub-groups.

These tests do NOT need an omni.ui context — :class:`UiDisplayGroup`
is a pure dataclass with no UI dependency. That's intentional: Step
5.1 isolates the tree from the widget so the grouping logic stays unit-
testable independent of any renderer.
"""

from __future__ import annotations

from typing import List

import pytest
from ovui_data_adapters.common import AttributeMetadata

from ovui_widgets.property.parts import UiDisplayGroup
from ovui_widgets.property.parts.display_group import UiDisplayGroup as UiDisplayGroupDirect

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(name: str, group: str = "") -> AttributeMetadata:
    """Build a minimally-populated :class:`AttributeMetadata`.

    The tree cares only about identity — the ``type_name`` / range / etc
    fields are irrelevant for grouping — so these test fixtures fill
    only the fields ``AttributeMetadata``'s dataclass requires.
    """
    return AttributeMetadata(
        name=name,
        display_name=name,
        type_name="float",
        value_type=float,
        group=group,
    )


def _split(path: str) -> List[str]:
    """Emulate the dot-split that Step 5.2 will do on ``metadata.group``.

    Kept here so the test cases read the way the production caller
    will: an empty string splits to ``[]`` (root), not ``[""]``.
    """
    return path.split(".") if path else []


# ---------------------------------------------------------------------------
# Construction / basic shape
# ---------------------------------------------------------------------------


class TestBasicShape:
    """UiDisplayGroup exposes the four fields used by PropertyWindow."""

    def test_defaults_are_independent_instances(self) -> None:
        """``field(default_factory=...)`` keeps separate trees separate.

        Without the factory, two freshly-constructed groups would share
        the same ``sub_groups`` dict and the same ``props`` list — a
        classic shared-mutable-default bug. Mutating one should leave
        the other empty.
        """
        a = UiDisplayGroup(name="A")
        b = UiDisplayGroup(name="B")
        a.sub_groups["child"] = UiDisplayGroup(name="child")
        a.props.append(_meta("x"))
        assert b.sub_groups == {}
        assert b.props == []

    def test_collapsed_defaults_false(self) -> None:
        assert UiDisplayGroup(name="A").collapsed is False

    def test_collapsed_settable(self) -> None:
        g = UiDisplayGroup(name="A", collapsed=True)
        assert g.collapsed is True

    def test_export_from_package(self) -> None:
        """``UiDisplayGroup`` is re-exported from ``ovui_widgets.property.parts``."""
        assert UiDisplayGroup is UiDisplayGroupDirect


# ---------------------------------------------------------------------------
# add_prop — core recursive insertion
# ---------------------------------------------------------------------------


class TestAddProp:
    """Recursive insert semantics — the heart of the tree."""

    def test_empty_path_goes_to_root_props(self) -> None:
        """``add_prop(prop, [])`` appends to this node — no sub-group created."""
        root = UiDisplayGroup(name="")
        prop = _meta("radius")
        root.add_prop(prop, [])
        assert root.props == [prop]
        assert root.sub_groups == {}

    def test_single_level_creates_one_sub_group(self) -> None:
        """``["Shape"]`` creates exactly one sub-group named ``"Shape"``."""
        root = UiDisplayGroup(name="")
        prop = _meta("radius")
        root.add_prop(prop, ["Shape"])
        assert list(root.sub_groups.keys()) == ["Shape"]
        shape = root.sub_groups["Shape"]
        assert shape.name == "Shape"
        assert shape.props == [prop]
        assert shape.sub_groups == {}

    def test_three_level_nesting(self) -> None:
        """Group ``"A.B.C"`` creates three nested levels.

        Directly from the done signal in the property inspector step 5.1.
        """
        root = UiDisplayGroup(name="")
        prop = _meta("leaf")
        root.add_prop(prop, _split("A.B.C"))
        assert list(root.sub_groups.keys()) == ["A"]
        a = root.sub_groups["A"]
        assert a.props == []
        assert list(a.sub_groups.keys()) == ["B"]
        b = a.sub_groups["B"]
        assert b.props == []
        assert list(b.sub_groups.keys()) == ["C"]
        c = b.sub_groups["C"]
        assert c.props == [prop]
        assert c.sub_groups == {}

    def test_multiple_props_same_group_share_sub_group(self) -> None:
        """Two props with identical ``group`` land in the same sub-group.

        This is the invariant that makes the grouping UI work at all —
        without it, every prop would spawn a new frame and the tree
        would be a forest of length-one paths.
        """
        root = UiDisplayGroup(name="")
        p1 = _meta("radius")
        p2 = _meta("height")
        root.add_prop(p1, ["Shape"])
        root.add_prop(p2, ["Shape"])
        assert list(root.sub_groups.keys()) == ["Shape"]
        assert root.sub_groups["Shape"].props == [p1, p2]

    def test_duplicate_sub_group_names_reuse_existing(self) -> None:
        """A pre-existing sub-group is reused, not replaced.

        If the second ``add_prop`` replaced ``root.sub_groups["A"]``
        with a fresh node, ``p1`` would vanish. The dict-get + create-
        only-if-missing branch in :meth:`UiDisplayGroup.add_prop` is
        what guards this.
        """
        root = UiDisplayGroup(name="")
        p1 = _meta("x")
        p2 = _meta("y")
        root.add_prop(p1, ["A", "B"])
        root.add_prop(p2, ["A", "B"])
        a = root.sub_groups["A"]
        assert list(a.sub_groups.keys()) == ["B"]
        assert a.sub_groups["B"].props == [p1, p2]

    def test_props_at_different_depths_coexist(self) -> None:
        """A shallow prop in ``"A"`` and a deep prop in ``"A.B"`` both sit correctly.

        The shallow prop lives in ``root.sub_groups["A"].props``; the
        deep prop lives in ``root.sub_groups["A"].sub_groups["B"].props``.
        Neither disturbs the other.
        """
        root = UiDisplayGroup(name="")
        shallow = _meta("shallow")
        deep = _meta("deep")
        root.add_prop(shallow, ["A"])
        root.add_prop(deep, ["A", "B"])
        a = root.sub_groups["A"]
        assert a.props == [shallow]
        assert list(a.sub_groups.keys()) == ["B"]
        assert a.sub_groups["B"].props == [deep]

    def test_sibling_top_level_groups(self) -> None:
        """Two top-level groups live as siblings under the same root.

        Covers the common case of a prim having ``"Transform"`` and
        ``"Shape"`` groups side-by-side.
        """
        root = UiDisplayGroup(name="")
        t = _meta("translate")
        r = _meta("radius")
        root.add_prop(t, ["Transform"])
        root.add_prop(r, ["Shape"])
        assert set(root.sub_groups.keys()) == {"Transform", "Shape"}
        assert root.sub_groups["Transform"].props == [t]
        assert root.sub_groups["Shape"].props == [r]

    def test_sub_group_insertion_order_preserved(self) -> None:
        """Sub-groups appear in first-seen order, not alphabetic.

        Python 3.7+ dict iteration is insertion-order. The test inserts
        ``Zeta`` before ``Alpha`` and asserts the order is preserved —
        this is what allows Step 6.x's ``_customize_props_layout`` to
        drive group ordering via insertion sequence without needing a
        separate ordered-list field.
        """
        root = UiDisplayGroup(name="")
        root.add_prop(_meta("z"), ["Zeta"])
        root.add_prop(_meta("a"), ["Alpha"])
        assert list(root.sub_groups.keys()) == ["Zeta", "Alpha"]

    def test_auto_created_sub_group_not_collapsed(self) -> None:
        """Sub-groups created by :meth:`add_prop` default to expanded.

        Callers that want a group created-already-collapsed must set
        the flag on the returned node after insertion; insert itself
        never flips the flag.
        """
        root = UiDisplayGroup(name="")
        root.add_prop(_meta("x"), ["A", "B"])
        assert root.sub_groups["A"].collapsed is False
        assert root.sub_groups["A"].sub_groups["B"].collapsed is False

    def test_auto_created_sub_group_name_matches_path_part(self) -> None:
        """Each auto-created sub-group's :attr:`name` equals its path part."""
        root = UiDisplayGroup(name="")
        root.add_prop(_meta("leaf"), ["A", "B", "C"])
        assert root.sub_groups["A"].name == "A"
        assert root.sub_groups["A"].sub_groups["B"].name == "B"
        assert root.sub_groups["A"].sub_groups["B"].sub_groups["C"].name == "C"

    def test_empty_string_path_part_treated_literally(self) -> None:
        """``[""]`` is a single empty-named sub-group, not a no-op.

        This matters because :meth:`add_prop` doesn't do any splitting
        itself — it trusts the caller's ``path_parts``. The production
        caller (Step 5.2) will split on ``"."`` and pass the result; an
        edge case where ``metadata.group == "."`` would produce
        ``["", ""]``. Pin the current behaviour so any future sanitiser
        inside ``add_prop`` has to explicitly decide what to do with it.
        """
        root = UiDisplayGroup(name="")
        root.add_prop(_meta("x"), [""])
        assert list(root.sub_groups.keys()) == [""]
        assert root.sub_groups[""].name == ""


# ---------------------------------------------------------------------------
# get_children — ordered traversal
# ---------------------------------------------------------------------------


class TestGetChildren:
    """``get_children`` yields sub-groups before props."""

    def test_empty_group_yields_nothing(self) -> None:
        root = UiDisplayGroup(name="")
        assert list(root.get_children()) == []

    def test_only_props_yields_only_props(self) -> None:
        root = UiDisplayGroup(name="")
        p = _meta("x")
        root.add_prop(p, [])
        assert list(root.get_children()) == [p]

    def test_only_sub_groups_yields_only_sub_groups(self) -> None:
        root = UiDisplayGroup(name="")
        root.add_prop(_meta("x"), ["A"])
        children = list(root.get_children())
        assert len(children) == 1
        assert isinstance(children[0], UiDisplayGroup)
        assert children[0].name == "A"

    def test_sub_groups_yielded_before_props(self) -> None:
        """The core ordering invariant from the property inspector step 5.1."""
        root = UiDisplayGroup(name="")
        leaf_prop = _meta("leaf")
        sub_prop = _meta("in_sub")
        root.add_prop(leaf_prop, [])
        root.add_prop(sub_prop, ["A"])
        children = list(root.get_children())
        assert len(children) == 2
        assert isinstance(children[0], UiDisplayGroup)
        assert children[0].name == "A"
        assert children[1] is leaf_prop

    def test_children_ordering_even_when_prop_inserted_first(self) -> None:
        """Insertion order of top-level props doesn't move them ahead of sub-groups.

        ``get_children`` yields ``sub_groups.values()`` before
        ``props`` regardless of which was inserted first — so a user
        scrolling a panel sees nested frames above the un-grouped rows
        even when the un-grouped property was discovered first.
        """
        root = UiDisplayGroup(name="")
        leaf_prop = _meta("leaf")
        sub_prop = _meta("in_sub")
        root.add_prop(leaf_prop, [])
        root.add_prop(sub_prop, ["A"])
        order = [
            c.name if isinstance(c, UiDisplayGroup) else c.name
            for c in root.get_children()
        ]
        assert order == ["A", "leaf"]

    def test_sub_group_order_matches_insertion(self) -> None:
        """Sibling sub-groups come out in first-seen order."""
        root = UiDisplayGroup(name="")
        root.add_prop(_meta("t"), ["Transform"])
        root.add_prop(_meta("r"), ["Shape"])
        order = [
            c.name for c in root.get_children() if isinstance(c, UiDisplayGroup)
        ]
        assert order == ["Transform", "Shape"]

    def test_prop_order_matches_insertion(self) -> None:
        """Root-level props come out in insertion order."""
        root = UiDisplayGroup(name="")
        p1 = _meta("alpha")
        p2 = _meta("beta")
        p3 = _meta("gamma")
        root.add_prop(p1, [])
        root.add_prop(p2, [])
        root.add_prop(p3, [])
        assert list(root.get_children()) == [p1, p2, p3]

    def test_get_children_is_iterator(self) -> None:
        """Return value is an iterator, not a pre-built list.

        Pinned because Step 5.2 iterates directly without ``list(...)``
        — switching to a list return would still work but forces
        unnecessary allocation on the render path. Pin the contract.
        """
        root = UiDisplayGroup(name="")
        root.add_prop(_meta("x"), [])
        result = root.get_children()
        assert iter(result) is result  # iterator protocol: iter(x) is x
        # Can be advanced:
        first = next(result)
        assert first.name == "x"

    def test_nested_get_children_recurses(self) -> None:
        """Each level of the tree has its own independent ordering.

        The inner sub-group's :meth:`get_children` yields its own
        sub-groups-first-then-props — the root's ordering doesn't leak
        through.
        """
        root = UiDisplayGroup(name="")
        shallow = _meta("shallow")
        deep = _meta("deep")
        root.add_prop(shallow, ["A"])
        root.add_prop(deep, ["A", "B"])
        a = root.sub_groups["A"]
        children = list(a.get_children())
        assert len(children) == 2
        assert isinstance(children[0], UiDisplayGroup)
        assert children[0].name == "B"
        assert children[1] is shallow


# ---------------------------------------------------------------------------
# Integration-ish — building a realistic tree
# ---------------------------------------------------------------------------


class TestRealisticTree:
    """Put the pieces together with a sensible USD-shaped example."""

    def test_transform_tree(self) -> None:
        """A USD Xform's hierarchical groups build the expected shape.

        Simulates the end-state of Step 5.2 for a prim with
        ``xformOp:translate``, ``xformOp:rotateXYZ``, ``xformOp:scale``
        authored under ``"Transform.Translate"``, ``"Transform.Rotate"``
        and ``"Transform.Scale"`` respectively, plus a top-level
        ``displayColor`` at root.
        """
        root = UiDisplayGroup(name="")
        t = _meta("xformOp:translate", "Transform.Translate")
        r = _meta("xformOp:rotateXYZ", "Transform.Rotate")
        s = _meta("xformOp:scale", "Transform.Scale")
        dc = _meta("primvars:displayColor", "")

        for p in (t, r, s):
            root.add_prop(p, _split(p.group))
        root.add_prop(dc, _split(dc.group))

        # One top-level sub-group; one top-level prop
        top_level = list(root.get_children())
        assert len(top_level) == 2
        assert isinstance(top_level[0], UiDisplayGroup)
        assert top_level[0].name == "Transform"
        assert top_level[1] is dc

        # Transform has three siblings
        transform = root.sub_groups["Transform"]
        assert list(transform.sub_groups.keys()) == [
            "Translate",
            "Rotate",
            "Scale",
        ]
        assert transform.props == []

        # Each terminal group holds one prop
        assert transform.sub_groups["Translate"].props == [t]
        assert transform.sub_groups["Rotate"].props == [r]
        assert transform.sub_groups["Scale"].props == [s]

    def test_mixed_depth_tree(self) -> None:
        """Sibling sub-groups with different depths coexist.

        ``"Shaping.Cone"`` (depth 2) next to ``"Shape"`` (depth 1) next
        to an ungrouped prop — nothing flattens, nothing ambiguates.
        """
        root = UiDisplayGroup(name="")
        cone = _meta("coneAngle", "Shaping.Cone")
        radius = _meta("radius", "Shape")
        flat = _meta("visibility", "")
        root.add_prop(cone, _split(cone.group))
        root.add_prop(radius, _split(radius.group))
        root.add_prop(flat, _split(flat.group))

        assert list(root.sub_groups.keys()) == ["Shaping", "Shape"]
        assert root.props == [flat]
        assert root.sub_groups["Shaping"].props == []
        assert list(root.sub_groups["Shaping"].sub_groups.keys()) == ["Cone"]
        assert root.sub_groups["Shaping"].sub_groups["Cone"].props == [cone]
        assert root.sub_groups["Shape"].props == [radius]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
