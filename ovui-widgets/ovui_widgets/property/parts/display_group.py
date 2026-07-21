# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Hierarchical display-group tree for the Property Inspector.

Introduced by Step 5.1 of the property inspector implementation. :class:`UiDisplayGroup` is the
in-memory representation of the nested collapsable-frame hierarchy that
:class:`ovui_widgets.property.window.PropertyWindow` ultimately renders. Today the
window renders a flat
single-level grouping keyed by :attr:`AttributeMetadata.group`; Step 5.2
will replace that logic with a recursive build over a
:class:`UiDisplayGroup` tree so a property with
``group = "Transform.Translate"`` splits into nested frames
``Transform → Translate → [prop]``.

This step is deliberately UI-free. The class is a pure dataclass with
two behavioural methods — :meth:`add_prop` (recursive insert) and
:meth:`get_children` (ordered traversal) — that the next step will hook
up to ``ui.CollapsableFrame`` construction. Isolating the tree from the
widget lets the grouping logic be unit-tested without an omni.ui
context and keeps the "split a dot-path string into a tree" concern
independent of the "render a tree as collapsable frames" concern.

Import direction note: this module imports
:class:`ovui_widgets.common.adapters.AttributeMetadata` (downward, adapters → ui);
the reverse is never allowed and there is no upward omni.ui dependency
here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Sequence, Union

from ovui_data_adapters.common import AttributeMetadata


@dataclass
class UiDisplayGroup:
    """Recursive tree node for grouped property display.

    One :class:`UiDisplayGroup` represents one collapsable frame. The
    ``root`` is a sentinel group whose :attr:`name` is typically empty —
    its children are the top-level groups (``"Transform"``,
    ``"Shape"``, …) and any ungrouped properties.

    The tree is built by calling :meth:`add_prop` on the root for each
    property, passing the dot-split group path as ``path_parts``. An
    empty ``path_parts`` means the property lives at this level.

    :attr:`sub_groups` is a regular dict; Python 3.7+ guarantees
    insertion-order iteration, which :meth:`get_children` relies on to
    yield groups in the order they were first seen. Callers that want
    alphabetic ordering should sort before iterating — the data
    structure itself stays order-preserving so custom-layout ordering
    (Step 6.x, via ``_customize_props_layout``) can flow through
    unchanged.

    :attr:`collapsed` is authored on a group and mirrors the
    per-metadata ``display_group_collapsed`` hint from upstream Kit; the
    widget reads it as the initial expanded/collapsed state when it
    builds the :class:`omni.ui.CollapsableFrame`. Runtime collapse
    persistence is tracked separately in
    ``PropertyWindow._group_collapse_state`` keyed by full dot-joined
    path (the keying swap lands in Step 5.2).
    """

    name: str
    sub_groups: Dict[str, "UiDisplayGroup"] = field(default_factory=dict)
    props: List[AttributeMetadata] = field(default_factory=list)
    collapsed: bool = False

    def add_prop(
        self,
        prop: AttributeMetadata,
        path_parts: Sequence[str],
    ) -> None:
        """Insert ``prop`` at the location described by ``path_parts``.

        ``path_parts`` is the dot-split group path — ``"A.B.C"`` becomes
        ``["A", "B", "C"]``. The method consumes one segment per level:
        if ``path_parts`` is empty the prop is appended to :attr:`props`
        on this node; otherwise the first segment selects (or creates)
        a sub-group and the method recurses with the remainder.

        Duplicate sub-group names reuse the existing sub-group — this
        is what makes multiple properties with the same ``group``
        string collapse into one shared frame instead of producing a
        parallel tree of siblings. A missing sub-group is created with
        :attr:`collapsed` defaulting to ``False``; callers that want a
        group created-already-collapsed look up the node via
        ``self.sub_groups[name]`` after insert and flip the flag there
        (Step 5.2 wiring).

        The method has no return value — the tree is mutated in place.
        """
        if not path_parts:
            self.props.append(prop)
            return
        head = path_parts[0]
        rest = path_parts[1:]
        sub = self.sub_groups.get(head)
        if sub is None:
            sub = UiDisplayGroup(name=head)
            self.sub_groups[head] = sub
        sub.add_prop(prop, rest)

    def get_children(
        self,
    ) -> Iterator[Union["UiDisplayGroup", AttributeMetadata]]:
        """Yield children in display order: sub-groups first, then props.

        "Sub-groups before props" matches the property inspector behavior and the upstream Kit behaviour for unordered groups — a
        group is a bigger visual unit than a leaf row, so nesting is
        laid out before the value widgets at this level. Within each
        category the order is insertion order (the dict / list
        insertion order at :meth:`add_prop` time).

        Returns an iterator, not a list, so callers building a large
        frame tree don't pay the cost of materialising every node.
        The returned union type is either another :class:`UiDisplayGroup`
        (render another :class:`omni.ui.CollapsableFrame`) or an
        :class:`AttributeMetadata` (dispatch to
        :class:`WidgetBuilderTable`).
        """
        yield from self.sub_groups.values()
        yield from self.props
