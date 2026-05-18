# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""``AttributesWidget`` — default "all attributes" property widget.

property widget stack behavior / the property inspector step 6.2. Concrete
:class:`~ovwidgets.property.widget.PropertyWidget` subclass that renders the
group tree + attribute rows :class:`~ovwidgets.property.window.PropertyWindow`
used to build inline in Step 5.2–5.3. Moving the logic here is the
second half of the Phase 6 refactor: Step 6.1 renamed the old
``PropertyWidget`` (the window) to ``PropertyWindow`` and reserved the
name ``PropertyWidget`` for an abstract stackable-section base; Step 6.2
ships the first concrete subclass — the "catch-all that shows every
attribute for the current selection".

Step 6.3 rebases this class onto
:class:`~ovwidgets.property.widget.SimplePropertyWidget`. The catch-all
renders its own group-tree frames at the top level of the property
panel for visual parity with pre-Step-6.3 so it passes ``title=""``
to the base, which makes the inherited :meth:`build_items` skip the
wrapper frame and delegate to :meth:`build_items_content` in the
window's ambient scrollable-content scope. The rest of the widget
(five group / row methods) is unchanged from Step 6.2 — the benefit
of the rebase is that the filter-subscription and rebuild-scheduling
machinery now lives one level up and is available to Step 6.4's
schema widgets without duplication.

The widget reads the adapter, selection, filter text, and per-group
collapse state from its owning :class:`PropertyWindow` via a
back-reference injected at construction. Those fields remain as
instance attrs on :class:`PropertyWindow` because they sit at the window
level (filter bar, adapter hot-swap API, selection bus) — the
attributes widget is one consumer of that shared state, not its owner.
The only writeback to the window is
:attr:`PropertyWindow._active_context_menu`, pinned so omni.ui's
reference-count teardown does not close the menu mid-frame.

Step 6.5 changes the construction / hand-off story. The constructor's
``window`` argument is now optional — :class:`PropertySchemeRegistry`
registers :class:`AttributesWidget` itself as a zero-arg factory
(:func:`ovwidgets.property.widget.scheme_registry._register_defaults`) so
module-import registration can produce windowless instances without
needing a :class:`PropertyWindow` reference at registry-load time.
:class:`PropertyWindow` then binds the window back-reference via the
:meth:`set_window` setter before invoking :meth:`on_new_payload` on
registry-produced instances, so rendering has the adapter / selection /
filter state it needs. Windowless instances remain safely dormant
(:meth:`_compute_display_group` returns an empty root).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.property.parts import UiDisplayGroup
from ovwidgets.property.widget.simple_property_widget import SimplePropertyWidget

if TYPE_CHECKING:
    from ovwidgets.property.payload import PropertyPayload
    from ovwidgets.property.window import PropertyWindow


class AttributesWidget(SimplePropertyWidget):
    """Default property widget: renders every attribute of the selection.

    This is the "all attributes" catch-all — it subscribes to no specific
    schema and accepts every :class:`~ovwidgets.property.payload.PropertyPayload`.
    Step 6.5's :class:`PropertySchemeRegistry` will register one of
    these per :class:`PropertyWindow` under scheme ``"default"``; domain-
    specific widgets (Step 6.4) compose on top for richer schemas.

    The widget owns no adapter of its own — it reads the window's
    :attr:`PropertyWindow._adapter`, :attr:`PropertyWindow._selection`,
    :attr:`PropertyWindow._filter_text`, and
    :attr:`PropertyWindow._group_collapse_state` through the back-ref.
    """

    def __init__(self, window: Optional["PropertyWindow"] = None) -> None:
        """Bind to ``window`` for shared adapter / selection / filter state.

        ``window`` is optional so :class:`PropertySchemeRegistry` can
        register :class:`AttributesWidget` itself as a zero-arg
        factory at module-import time. Windowless instances are
        dormant — :meth:`_compute_display_group` returns an empty root
        and :meth:`build_items_content` emits the "No properties"
        placeholder. :class:`PropertyWindow` calls :meth:`set_window`
        on registry-produced instances before invoking
        :meth:`on_new_payload`, which is when the adapter / selection /
        filter-state reads actually need a live back-reference.

        The back-reference is a hard reference (not a ``weakref``)
        because the window owns the widget list and calls
        :meth:`destroy` before dropping the widget — no reference-cycle
        hazard once the widget is unregistered.

        Passes ``title=""`` to :class:`SimplePropertyWidget` so the
        inherited :meth:`build_items` skips the :class:`ui.CollapsableFrame`
        wrapper — the catch-all builds its own per-group frames at the
        top level of the property panel and must stay byte-identical
        to the pre-Step-6.3 visual output.
        """
        super().__init__(title="", collapsed=False)
        self._window: Optional["PropertyWindow"] = window

    def set_window(self, window: Optional["PropertyWindow"]) -> None:
        """Bind / rebind the window back-reference post-construction.

        :class:`PropertySchemeRegistry` returns
        :class:`AttributesWidget` instances created through its
        zero-arg factory, so the window reference has to be threaded
        in after construction.
        :meth:`PropertyWindow._build_registered_widgets` calls this
        with ``self`` on every registry-produced widget immediately
        before :meth:`on_new_payload`. Passing ``None`` unbinds and
        reverts the widget to its dormant state.
        """
        self._window = window

    # ------------------------------------------------------------------
    # PropertyWidget contract
    # ------------------------------------------------------------------

    def on_new_payload(self, payload: "PropertyPayload") -> bool:
        """Always return ``True`` — this is the catch-all widget.

        Future scheme-specific widgets (Step 6.4) will reject payloads
        whose ``get_scheme()`` does not match their registered scheme;
        this one accepts every payload so the property panel shows
        *some* content for every prim type.
        """
        return True

    def build_items_content(self) -> None:
        """Emit the grouped attribute tree into the ambient ovui scope.

        Called by :meth:`SimplePropertyWidget.build_items` — since the
        constructor passed ``title=""`` that inherited method skips the
        :class:`ui.CollapsableFrame` wrapper and invokes this hook
        directly in the host window's scrollable-content ``VStack``.

        Delegates to :meth:`_build_groups`, which walks the
        :class:`UiDisplayGroup` tree built by
        :meth:`_compute_display_group` and emits nested
        :class:`ui.CollapsableFrame` headers via
        :class:`~ovwidgets.property.group_widget.AttributeGroupWidget`.
        """
        self._build_groups()

    def destroy(self) -> None:
        """Drop the active-menu handle and the window back-ref.

        :class:`PropertyWindow` calls this from
        :meth:`PropertyWindow.unregister_widget` and
        :meth:`PropertyWindow.destroy`. Clearing the active context
        menu closes any still-open popup; nulling the back-ref prevents
        stale reads if the widget is re-used after unregister (it
        shouldn't be, but a defensive null makes the failure mode loud).

        Super-calls :meth:`SimplePropertyWidget.destroy` so the
        inherited pending-rebuild handle and filter subscription are
        released — leaking either would keep the filter model alive
        and re-fire rebuilds after the widget is gone.
        """
        if self._window is not None:
            self._window._active_context_menu = None
        self._window = None
        super().destroy()

    # ------------------------------------------------------------------
    # Moved from PropertyWindow in Step 6.2 — group-tree build
    # ------------------------------------------------------------------

    def _compute_display_group(self) -> UiDisplayGroup:
        """Build a :class:`UiDisplayGroup` tree from the filtered attributes.

        Moved verbatim from :class:`PropertyWindow` in Step 6.2. Splits
        each attribute's ``metadata.group`` on ``"."`` and calls
        :meth:`UiDisplayGroup.add_prop` on the root, so
        ``group == "Transform.Translate"`` lands under
        ``root → Transform → Translate → [prop]`` and ``group ==
        "Transform"`` lands under ``root → Transform → [prop]``. Empty
        ``group`` strings place the prop at the root (no wrapper frame).

        Filter text is applied case-insensitively against the
        attribute's ``display_name``; non-matching attributes are
        dropped before insertion so empty sub-groups never get created.

        Returns an empty-name root group when the widget's window has no
        adapter or the filter eats every prop, letting
        :meth:`_build_groups` render the "No properties" label uniformly.
        """
        root = UiDisplayGroup(name="")
        adapter = self._window._adapter if self._window is not None else None
        if adapter is None:
            return root
        filter_text = self._window._filter_text if self._window is not None else ""
        for attr_name in adapter.get_attribute_names():
            meta = adapter.get_attribute_metadata(attr_name)
            if filter_text:
                if filter_text.lower() not in meta.display_name.lower():
                    continue
            path_parts = meta.group.split(".") if meta.group else []
            root.add_prop(meta, path_parts)
        return root

    def _build_groups(self) -> None:
        """Render the :class:`UiDisplayGroup` tree as nested frames.

        Moved from :class:`PropertyWindow` in Step 6.2. Walks the tree
        returned by :meth:`_compute_display_group`: each
        :class:`UiDisplayGroup` child becomes a
        :class:`ui.CollapsableFrame` (via
        :class:`AttributeGroupWidget`), each
        :class:`AttributeMetadata` child is dispatched to
        :meth:`_build_attribute_row`. The recursion lives in
        :meth:`_build_group_children` so each level can thread the
        dot-joined path down for collapse-state keying.
        """
        root = self._compute_display_group()
        if not root.sub_groups and not root.props:
            ui.Label(
                "No properties",
                style_type_name_override="Property.EmptyLabel",
                alignment=ui.Alignment.CENTER,
            )
            return
        self._build_group_children(root, path="", level=0)

    def _build_group_children(
        self, group: UiDisplayGroup, path: str, level: int = 0
    ) -> None:
        """Recursively emit frames + rows for one group's children.

        Moved from :class:`PropertyWindow` in Step 6.2. ``path`` is the
        dot-joined ancestor path of ``group`` — empty string for the
        root, ``"Transform"`` for the Transform group,
        ``"Transform.Translate"`` for its Translate sub-group, etc. It
        is composed with each sub-group's ``name`` to produce the key
        under which the window's ``_group_collapse_state`` stores that
        sub-group's persisted expanded/collapsed state. Keying by full
        path (rather than leaf name) prevents collisions when two
        different top-level groups each own a sub-group named (e.g.)
        ``"Translate"``.

        :meth:`UiDisplayGroup.get_children` yields sub-groups before
        props, so nested frames appear above leaf rows at every level.

        Each sub-group also receives an ``on_context_menu`` callback
        (Step 5.3, group context-menu behavior) that pops the Copy/Paste/Reset-All menu
        for that group's recursive prop set. The callback captures
        ``child`` via a default-argument binding — the loop variable
        would otherwise close over the last iteration's reference by
        the time the user right-clicks.

        Step 8.2 threads ``level`` through the recursion so nested
        frames (``Transform`` → ``Translate``) can paint their title in
        the subordinate ``cl.text_secondary`` shade via
        :class:`AttributeGroupWidget`'s ``::inner`` variant. ``level=0``
        at the root; each recursive call increments to ``level + 1``.
        """
        from ovwidgets.property.group_widget import AttributeGroupWidget

        collapse_state = (
            self._window._group_collapse_state if self._window is not None else {}
        )
        for child in group.get_children():
            if isinstance(child, UiDisplayGroup):
                child_path = f"{path}.{child.name}" if path else child.name
                initial_collapsed = collapse_state.get(child_path, False)
                grp = AttributeGroupWidget(
                    child.name,
                    initially_collapsed=initial_collapsed,
                    on_collapse_change=lambda c, p=child_path: collapse_state.__setitem__(p, c),  # type: ignore[misc]
                    on_context_menu=lambda x, y, g=child: self._show_group_context_menu(g, x, y),
                    level=level,
                )
                with grp.content:  # type: ignore[union-attr]
                    self._build_group_children(child, child_path, level=level + 1)
            else:
                self._build_attribute_row(child)

    def _show_group_context_menu(
        self, group: UiDisplayGroup, x: float, y: float
    ) -> None:
        """Pop the Copy/Paste/Reset-All menu for ``group`` at ``(x, y)``.

        Moved from :class:`PropertyWindow` in Step 6.2. Defers to
        :func:`ovwidgets.property.parts.group_context_menu.show_group_context_menu`
        and retains the returned :class:`ui.Menu` on the window's
        :attr:`_active_context_menu` so omni.ui's reference-count
        teardown does not drop the popup before the user can interact
        with it. A subsequent right-click replaces the reference,
        which closes any still-open menu. The window (not the widget)
        owns the handle because :meth:`PropertyWindow.destroy` needs
        to clear it during teardown.
        """
        if self._window is None:
            return
        adapter = self._window._adapter
        if adapter is None:
            return
        from ovwidgets.property.parts.group_context_menu import show_group_context_menu
        self._window._active_context_menu = show_group_context_menu(
            adapter, group, x, y
        )

    def _build_attribute_row(self, prop: AttributeMetadata) -> None:
        """Dispatch one attribute to :class:`WidgetBuilderTable`.

        Moved from :class:`PropertyWindow` in Step 6.2. The builder
        table owns the per-type-name widget registry (property attribute builder behavior); this
        widget just hands it the adapter + metadata and lets the
        appropriate builder render the row.

        Step 7.1: threads the window's current filter text as the
        ``match`` kwarg so each row's :class:`HighlightLabel` can
        highlight the matching substring of ``display_name``. When the
        filter is empty the kwarg threads through as ``""``, which the
        rows and :class:`HighlightLabel` both treat as "no highlight"
        — the rendered label is byte-identical to pre-7.1 output.
        """
        if self._window is None:
            return
        adapter = self._window._adapter
        if adapter is None:
            return
        from ovwidgets.property.builders import WidgetBuilderTable
        match = self._window._filter_text or ""
        WidgetBuilderTable.build(prop.name, prop, adapter, match=match)
