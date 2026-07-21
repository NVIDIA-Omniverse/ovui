# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Row object for a single prim spec under a layer in the Layers tree.

LAYERS-PLAN Step 48 / LAYERS-WINDOW-ARCHITECTURE §18.

A :class:`PrimSpecItem` is a :class:`omni.ui.AbstractItem` that wraps a
:class:`~ovui_widgets.common.adapters.PrimSpecDescriptor` delivered by
:meth:`LayerStackAdapter.get_prim_specs`. The item is attached to the
:class:`~ovui_widgets.layers.layer_item.LayerItem` that hosts the prim spec so
the row's identity (layer identifier + prim-spec path) round-trips
through the tree without needing to re-query the adapter.

Children are populated lazily on first :meth:`children` call: the tree
view asks for children only when the user expands the row, so the
constructor can skip the adapter round trip entirely for collapsed
branches (LAYERS-WINDOW-ARCHITECTURE §18.3 / §33.1). The cache is
invalidated by :meth:`invalidate_children` when the owning
:class:`LayerModel` batches a structural change that may have altered
the spec's ``nameChildren`` list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import omni.ui as ui
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovui_data_adapters.common import LayerStackAdapter

    from ovui_widgets.layers.layer_item import LayerItem


class PrimSpecItem(ui.AbstractItem):
    """One prim-spec row in the Layers tree, scoped to a single layer.

    Construction is cheap: the descriptor is stored verbatim and the
    child list starts as ``None`` (sentinel for "not yet queried").
    :meth:`children` lazily materialises the next level by calling
    :meth:`LayerStackAdapter.get_prim_specs` under the spec's path; the
    result is cached on the item so repeated expansion reads hit the
    cache until :meth:`invalidate_children` fires.
    """

    def __init__(
        self,
        layer_item: "LayerItem",
        descriptor: PrimSpecDescriptor,
        parent: Optional["PrimSpecItem"] = None,
    ) -> None:
        super().__init__()
        self._layer_item: "LayerItem" = layer_item
        self._descriptor: PrimSpecDescriptor = descriptor
        self._parent: Optional["PrimSpecItem"] = parent
        # ``None`` sentinel distinguishes "never queried" from "queried
        # and empty" — the latter is a legitimate terminal state for a
        # leaf prim spec and must not re-hit the adapter on every paint.
        self._children: Optional[List["PrimSpecItem"]] = None

    # ── Identity / navigation ────────────────────────────────────────

    @property
    def layer_item(self) -> "LayerItem":
        """The :class:`LayerItem` that owns this prim spec."""
        return self._layer_item

    @property
    def descriptor(self) -> PrimSpecDescriptor:
        """The backing :class:`PrimSpecDescriptor` delivered by the adapter."""
        return self._descriptor

    @property
    def path(self) -> str:
        """Sdf-style path of the prim spec (e.g. ``"/World/Cube"``)."""
        return self._descriptor.path

    @property
    def name(self) -> str:
        """Trailing path segment — what the tree row shows as the label.

        ``"/"`` is returned verbatim for the absolute-root case so the
        delegate can render the pseudo-root without a special case.
        """
        path = self._descriptor.path
        if path in ("", "/"):
            return path or "/"
        return path.rsplit("/", 1)[-1] or path

    @property
    def type_name(self) -> str:
        """USD type name (e.g. ``"Xform"``, ``"Cube"``); empty string if untyped."""
        return self._descriptor.type_name

    @property
    def specifier(self) -> PrimSpecifier:
        """The :class:`PrimSpecifier` kind (DEF / OVER / CLASS)."""
        return self._descriptor.specifier

    @property
    def has_reference(self) -> bool:
        return self._descriptor.has_reference

    @property
    def has_payload(self) -> bool:
        return self._descriptor.has_payload

    @property
    def is_instanceable(self) -> bool:
        return self._descriptor.is_instanceable

    @property
    def parent(self) -> Optional["PrimSpecItem"]:
        """The enclosing :class:`PrimSpecItem`, or ``None`` when the spec
        sits directly under its :class:`LayerItem`.

        Mirrors LAYERS-WINDOW-ARCHITECTURE §18.4: a root prim spec's
        parent is the :class:`LayerItem`, not another
        :class:`PrimSpecItem`. Callers that walk upward past the root
        spec read :attr:`layer_item` instead.
        """
        return self._parent

    # ── Lazy children ────────────────────────────────────────────────

    def children(
        self, adapter: "LayerStackAdapter"
    ) -> List["PrimSpecItem"]:
        """Return this spec's direct prim-spec children under ``adapter``.

        First call walks :meth:`LayerStackAdapter.get_prim_specs`
        at :attr:`path` and wraps each returned descriptor in a fresh
        :class:`PrimSpecItem`. The result is cached so subsequent calls
        are O(1). When the adapter raises :class:`KeyError` (the spec
        was removed between the tree-view expand and this read — e.g.
        a peer command just dropped the parent) the cache is set to an
        empty list so the row degrades to a childless leaf instead of
        re-raising into the paint pass.
        """
        if self._children is None:
            try:
                descriptors = adapter.get_prim_specs(
                    self._layer_item.identifier, self._descriptor.path
                )
            except KeyError:
                descriptors = []
            self._children = [
                PrimSpecItem(self._layer_item, d, parent=self)
                for d in descriptors
            ]
        return self._children

    def has_cached_children(self) -> bool:
        """``True`` iff :meth:`children` has been called at least once.

        Used by :class:`~ovui_widgets.layers.layer_model.LayerModel` to decide
        whether a ``can_item_have_children`` query may answer from the
        cache without a fresh adapter call.
        """
        return self._children is not None

    def invalidate_children(self) -> None:
        """Drop the cached child list.

        Called by :class:`LayerModel` when a structural event touches
        the owning layer's prim hierarchy — the next expand re-reads
        the descriptors from the adapter.
        """
        self._children = None

    # ── Introspection ────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"PrimSpecItem(layer={self._layer_item.identifier!r}, "
            f"path={self._descriptor.path!r}, "
            f"type={self._descriptor.type_name!r})"
        )
