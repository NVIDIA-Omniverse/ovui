# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""``SimplePropertyWidget`` — convenience base with frame + filter scaffolding.

property widget stack behavior / the property inspector step 6.3. Concrete convenience subclass
of :class:`~ovui_widgets.property.widget.PropertyWidget` that parks the pattern
every titled "emit a CollapsableFrame full of attribute rows" widget
shares: a :class:`ui.CollapsableFrame` wrapper with a header title, a
filter-subscription hook, a debounced :meth:`request_rebuild` scheduler
via :meth:`ovui_widgets.app.application.Application.call_later`, and
:meth:`add_item` / :meth:`add_item_with_model` helpers that drop a
child widget into the frame's content ``VStack``.

Subclasses typically:

    * call ``super().__init__(title, collapsed)`` with a header title,
    * override :meth:`build_items_content` to emit rows inside the
      scaffolded frame,
    * inherit :meth:`on_new_payload` (returns ``True`` — catch-all) or
      override it to gate on the payload's scheme / prim type,
    * inherit :meth:`destroy` or super-call it from any override so the
      pending-rebuild handle and filter subscription are released.

Subclasses that want the filter / rebuild scaffolding but manage their
own frame layout pass ``title=""`` and override either
:meth:`build_items_content` or :meth:`build_items` directly, skipping
the wrapper. Step 6.2's :class:`~ovui_widgets.property.widget.AttributesWidget`
is the prime example — it renders its own group-tree frames at the top
level of the property panel for visual parity with pre-Step-6.3, so it
passes ``title=""`` and funnels the group build through
:meth:`build_items_content`.

Step 7.5 adds an async-build hook: subclasses that need to spread an
expensive build across multiple frames override
:meth:`build_items_async` to return a generator. The rebuild
dispatcher detects the override (via an MRO-walking method-identity
check in :meth:`_is_async_build`) and drives the generator
frame-by-frame through :meth:`Application.call_later` — one
``next()`` call per frame, one ``yield`` point in the body equals one
frame pause. No widget opts into the async path yet; the hook is
scaffolding for a future material / shader widget with 500+
attributes.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Optional

import omni.ui as ui

from ovui_widgets.property.group_widget import (
    FIT_CONTENT_HEIGHT,
    GROUP_CONTENT_SPACING,
    build_property_group_header,
)
from ovui_widgets.property.widget.property_widget import PropertyWidget


class SimplePropertyWidget(PropertyWidget):
    """Convenience :class:`PropertyWidget` base with frame + filter scaffolding.

    See the module docstring for subclass patterns. This class is
    concrete: the two abstract methods on :class:`PropertyWidget`
    (:meth:`on_new_payload`, :meth:`build_items`) both have safe
    defaults so a minimal subclass only needs to override
    :meth:`build_items_content` to emit its rows.
    """

    def __init__(self, title: str, collapsed: bool = False) -> None:
        """Store frame title + initial collapse state.

        ``title`` is the :class:`ui.CollapsableFrame` header. Pass an
        empty string to skip the frame wrapper entirely — the widget's
        :meth:`build_items_content` then runs in whatever ``with``
        scope the host window opened before calling
        :meth:`build_items`. ``collapsed`` is the initial expanded /
        collapsed state of the frame; ignored when ``title == ""``.
        """
        self._title = title
        self._collapsed = collapsed
        self._frame: Optional[ui.CollapsableFrame] = None
        self._content: Optional[ui.VStack] = None
        # Filter subscription state. :meth:`subscribe_filter` populates
        # these; :meth:`destroy` releases them.
        self._filter_model: Optional[Any] = None
        self._filter_sub_id: Optional[int] = None
        # Coalesced rebuild handle. :meth:`request_rebuild` cancels any
        # still-pending handle before scheduling a new one so rapid
        # successive calls (e.g. from keystroke-driven filter-change
        # events) fold into a single deferred rebuild.
        self._pending_rebuild_handle: Optional[Any] = None
        # Step 7.5 — in-flight :meth:`build_items_async` generator when
        # the subclass overrides the async hook. ``None`` when no async
        # build is active; set by :meth:`_do_rebuild_async` and cleared
        # by :meth:`_advance_async_generator` on ``StopIteration``.
        # :meth:`destroy` and :meth:`request_rebuild` close any in-
        # flight generator so widget teardown and selection churn don't
        # strand a paused generator holding references into the build
        # frame.
        self._async_generator: Optional[Iterator[Any]] = None

    # ------------------------------------------------------------------
    # PropertyWidget contract
    # ------------------------------------------------------------------

    def on_new_payload(self, payload: Any) -> bool:
        """Default: show for every payload.

        Subclasses that gate on the payload's scheme / prim type
        (Step 6.4's :class:`SchemaPropertyWidget` will) override this
        to return ``False`` when the payload doesn't match.
        """
        return True

    def build_items(self) -> None:
        """Template method: open frame + ``VStack``, delegate to subclass hook.

        When ``self._title`` is non-empty, creates ``self._frame`` (a
        :class:`ui.CollapsableFrame` with the stored title + collapse
        state, styled as ``Property.GroupFrame``) and ``self._content``
        (a :class:`ui.VStack` inside the frame) and calls
        :meth:`build_items_content` in the content stack's ``with``
        scope so subclasses can emit rows by simply constructing
        :mod:`omni.ui` widgets.

        When ``self._title`` is empty, no frame is created —
        :meth:`build_items_content` runs in the ambient scope (the
        host window's scrollable-content ``VStack``). This is the
        opt-out path for widgets that own their own frame layout.

        Subclasses may override this method directly (instead of
        :meth:`build_items_content`) for full layout control; the
        :class:`AttributesWidget` rebase in Step 6.3 hooks in via
        :meth:`build_items_content` so both override paths stay valid.
        """
        if not self._title:
            self._frame = None
            self._content = None
            self.build_items_content()
            return
        self._frame = ui.CollapsableFrame(
            title=self._title,
            collapsed=self._collapsed,
            height=FIT_CONTENT_HEIGHT,
            style_type_name_override="Property.GroupFrame",
            build_header_fn=build_property_group_header,
        )
        with self._frame:
            self._content = ui.VStack(
                spacing=GROUP_CONTENT_SPACING,
                height=FIT_CONTENT_HEIGHT,
            )
            with self._content:
                self.build_items_content()

    def build_items_content(self) -> None:
        """Subclass hook — emit rows inside the scaffolded frame's ``VStack``.

        Default is a no-op: the convenience base just provides
        scaffolding, concrete content is the subclass's job. Step 6.4's
        :class:`SchemaPropertyWidget` will override this to iterate
        attributes through :meth:`_filter_props_to_build` and emit rows
        via :meth:`add_item_with_model`.
        """

    def destroy(self) -> None:
        """Cancel pending rebuild, close async generator, unsubscribe filter.

        Idempotent — safe to call multiple times, survives being called
        on a widget that never entered :meth:`build_items`. Subclasses
        that override must super-call so the pending-rebuild handle,
        async-build generator, and filter subscription are released
        (subscription leaks would keep the owning filter model alive
        and re-fire rebuilds after the widget is gone; an un-closed
        async generator would leave its ``finally`` cleanup unrun and
        hold references into the torn-down build frame).
        """
        if self._pending_rebuild_handle is not None:
            self._pending_rebuild_handle.cancel()
            self._pending_rebuild_handle = None
        if self._async_generator is not None:
            self._async_generator.close()
            self._async_generator = None
        if self._filter_model is not None and self._filter_sub_id is not None:
            self._filter_model.remove_value_changed_fn(self._filter_sub_id)
        self._filter_model = None
        self._filter_sub_id = None
        self._frame = None
        self._content = None

    # ------------------------------------------------------------------
    # Row-building helpers — invoked from build_items_content()
    # ------------------------------------------------------------------

    def add_item(self, widget_builder: Callable[[], Any]) -> None:
        """Append a child widget to the frame's content ``VStack``.

        ``widget_builder`` is a no-arg callable that constructs the
        widget. :mod:`omni.ui` widgets register themselves against the
        active ``with`` context at construction time, so this method
        opens the content ``VStack`` as the ``with`` scope, then
        invokes the builder — the builder just needs to emit its
        widgets (and the widget objects register automatically).

        When called without a scaffolded frame
        (``self._content is None`` — happens when ``title=""`` or
        before :meth:`build_items` runs), the builder runs against the
        ambient scope instead. Use :meth:`add_item_with_model` when the
        builder needs the editor's backing model as an argument.
        """
        if self._content is not None:
            with self._content:
                widget_builder()
        else:
            widget_builder()

    def add_item_with_model(
        self,
        model: Any,
        widget_builder: Callable[[Any], Any],
    ) -> None:
        """Append a child widget bound to ``model``.

        Same semantics as :meth:`add_item` but forwards ``model`` to
        ``widget_builder``. Subclasses typically use this to wire an
        existing :class:`~ovui_widgets.property.models.attribute_model.AttributeModelBase`
        onto a freshly constructed editor widget in one call.
        """
        if self._content is not None:
            with self._content:
                widget_builder(model)
        else:
            widget_builder(model)

    # ------------------------------------------------------------------
    # Rebuild scheduling
    # ------------------------------------------------------------------

    def request_rebuild(self) -> None:
        """Schedule a coalesced rebuild on the next application tick.

        Cancels any still-pending handle and closes any in-flight
        async generator (Step 7.5) before scheduling a new one, so
        rapid successive calls (typically from keystroke-driven
        filter-change events) coalesce into a single deferred rebuild
        and a paused generator from the prior request doesn't leak
        into the new build.

        Routes to one of two rebuild paths based on
        :meth:`_is_async_build`:

        * Sync (default): schedule :meth:`_do_rebuild` which triggers
          :meth:`ui.CollapsableFrame.rebuild` — the existing pre-
          Step-7.5 behavior every current widget relies on.
        * Async (subclass overrides :meth:`build_items_async`):
          schedule :meth:`_do_rebuild_async` which kicks off the
          generator driver. Each ``yield`` in the subclass body
          pauses the build for one frame via another
          :meth:`Application.call_later(0.0, ...)` — see
          :meth:`_advance_async_generator`.

        No-op when no :class:`Application` singleton exists — that
        happens in test environments that instantiate the widget
        outside a running application loop. In that case the widget's
        frame (if any) isn't attached to anything live, so there's no
        rebuild to schedule.
        """
        if self._pending_rebuild_handle is not None:
            self._pending_rebuild_handle.cancel()
            self._pending_rebuild_handle = None
        if self._async_generator is not None:
            self._async_generator.close()
            self._async_generator = None
        try:
            from ovui_widgets.common import scheduler as _scheduler
            if self._is_async_build():
                self._pending_rebuild_handle = _scheduler.call_later(
                    0.0, self._do_rebuild_async
                )
            else:
                self._pending_rebuild_handle = _scheduler.call_later(
                    0.0, self._do_rebuild
                )
        except RuntimeError:
            return

    def _is_async_build(self) -> bool:
        """Return ``True`` if this subclass overrides :meth:`build_items_async`.

        Compares the unbound method on ``type(self)`` against
        :meth:`PropertyWidget.build_items_async`. Python's MRO resolves
        the attribute to the base when the subclass hasn't overridden,
        so ``is not`` is precisely the override test — no introspection
        of ``__dict__`` required, and it walks multi-level inheritance
        chains correctly (any ancestor override returns ``True``).
        """
        return (
            type(self).build_items_async
            is not PropertyWidget.build_items_async
        )

    def _do_rebuild(self) -> None:
        """Fire the pending sync rebuild — drops the handle, rebuilds the frame."""
        self._pending_rebuild_handle = None
        if self._frame is not None:
            self._frame.rebuild()

    def _do_rebuild_async(self) -> None:
        """Start an async rebuild — kick off the generator and take the first step.

        Called from :meth:`request_rebuild`'s ``call_later`` when the
        subclass overrides :meth:`build_items_async`. Creates the
        generator, stores it on ``self._async_generator``, and calls
        :meth:`_advance_async_generator` to run the body up to the
        first ``yield`` (or ``StopIteration`` if the body never
        yields). A widget that overrides :meth:`build_items_async` but
        returns ``None`` is treated as a no-op — the sync frame rebuild
        is not invoked as a fallback because the override says "this
        widget owns its own build path."
        """
        self._pending_rebuild_handle = None
        gen = self.build_items_async()
        if gen is None:
            return
        self._async_generator = gen
        self._advance_async_generator()

    def _advance_async_generator(self) -> None:
        """Advance the in-flight async generator by one ``next()`` step.

        Runs the body from the current pause point to the next
        ``yield`` or ``StopIteration``. On ``StopIteration`` the
        generator is cleared and the build is done. Otherwise we
        schedule another :meth:`_advance_async_generator` for the next
        frame via :meth:`Application.call_later(0.0, ...)`, which is
        the same pattern :class:`ScrollPreserver` uses to wait for
        omni.ui's layout pass.

        No-op when :meth:`_async_generator` is already ``None`` (the
        generator was closed by :meth:`destroy` or
        :meth:`request_rebuild` between scheduling and firing).
        Exceptions raised inside the generator propagate up to the
        ``call_later`` driver — they are NOT swallowed here because a
        silent swallow would mask bugs in the subclass's async body.
        Breaking mid-body leaves ``_async_generator`` pointing at the
        now-dead generator; :meth:`destroy`'s ``.close()`` call is a
        safe no-op on a dead generator, so there is no resource leak.
        """
        self._pending_rebuild_handle = None
        gen = self._async_generator
        if gen is None:
            return
        try:
            next(gen)
        except StopIteration:
            self._async_generator = None
            return
        try:
            from ovui_widgets.common import scheduler as _scheduler
            self._pending_rebuild_handle = _scheduler.call_later(
                0.0, self._advance_async_generator
            )
        except RuntimeError:
            self._async_generator = None
            return

    # ------------------------------------------------------------------
    # Filter subscription
    # ------------------------------------------------------------------

    def subscribe_filter(self, filter_model: Any) -> None:
        """Subscribe to ``filter_model`` value changes; fire :meth:`request_rebuild`.

        Storing the model reference + subscription ID lets
        :meth:`destroy` unsubscribe cleanly. Calling this method twice
        drops the prior subscription before registering the new one so
        re-subscribing never leaks stale registrations.
        """
        if self._filter_model is not None and self._filter_sub_id is not None:
            self._filter_model.remove_value_changed_fn(self._filter_sub_id)
        self._filter_model = filter_model
        self._filter_sub_id = filter_model.add_value_changed_fn(
            self._on_filter_changed
        )

    def _on_filter_changed(self, model: Any) -> None:
        """Filter-model callback — bridges into :meth:`request_rebuild`."""
        self.request_rebuild()
