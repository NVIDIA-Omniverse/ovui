# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""AttributeModelBase — shared value model for attribute rows.

attribute edit transaction behavior and §17.9. Centralises the begin_edit → set_value → end_edit
contract so every row class does not re-implement the ``_editing`` counter,
the ``change_on_edit_end`` buffer gate, or the ``_ignore_notice`` guard
that keeps self-induced backing-store writes from triggering a feedback
read.

Two write modes driven by ``metadata.change_on_edit_end``:

* ``True`` (default; drag case) — ``set_value()`` stores the new value in
  ``_value`` only. The buffered value is flushed to the adapter once when
  ``end_edit()`` brings the counter back to zero. This is the slider-drag
  optimisation: one USD write per drag instead of one per frame.
* ``False`` (write-through; real-time feedback case) — ``set_value()``
  writes immediately to the adapter. ``end_edit()`` only decrements the
  counter and closes the adapter's undo group.

Introduced in Step 1.1 of the property inspector implementation. Row classes still use the
adapter directly; that swap lands in Step 1.4.
"""

from typing import Any, Callable, List, Optional

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter


class _ValueChangeSubscription:
    """Handle returned by ``subscribe_value_changed``.

    Mirrors the ``_UsdPropertySubscription`` pattern in
    ``ovwidgets.stage/usd_property_adapter.py``: callers hold the handle for the
    duration they want the callback live, then call ``cancel()`` to remove
    the subscription. There is no ``__del__`` auto-cancel because that
    pattern fires too eagerly (an anonymous lambda plus an un-captured
    return would unsubscribe before the first event).
    """

    def __init__(self, model: "AttributeModelBase", callback: Callable[[], None]) -> None:
        self._model: Optional["AttributeModelBase"] = model
        self._callback: Optional[Callable[[], None]] = callback

    def cancel(self) -> None:
        if self._model is None or self._callback is None:
            return
        self._model._remove_subscriber(self._callback)
        self._model = None
        self._callback = None


class AttributeModelBase:
    """Shared value model for a single attribute on a PropertyAdapter.

    Owns the editing counter, the optional buffered value, and the
    subscriber list. Construction performs one initial ``adapter.get_value``
    read to seed ``_value``; subsequent reads hit the cached ``_value``
    until ``_on_backing_changed()`` refreshes it.
    """

    def __init__(
        self,
        adapter: PropertyAdapter,
        attr_name: str,
        metadata: AttributeMetadata,
    ) -> None:
        self._adapter = adapter
        self._attr_name = attr_name
        self._metadata = metadata
        self._editing: int = 0
        self._value: Any = adapter.get_value(attr_name)
        self._prev_value: Any = None
        self._ignore_notice: bool = False
        self._subscribers: List[Callable[[], None]] = []

    # ── Value read/write ────────────────────────────────────────────────

    def get_value(self) -> Any:
        return self._value

    def set_value(self, value: Any) -> None:
        value = self._apply_hard_range_clamp(value)
        self._value = value
        if not self._metadata.change_on_edit_end:
            # Write-through: hit the adapter immediately. The _ignore_notice
            # guard stops our own adapter change from triggering a
            # _on_backing_changed re-read that would clobber _value.
            self._ignore_notice = True
            try:
                self._adapter.set_value(self._attr_name, value)
            finally:
                self._ignore_notice = False
        # Buffered mode: _value is held; flush happens in end_edit().
        self._notify_value_changed()

    def _apply_hard_range_clamp(self, value: Any) -> Any:
        """Clamp scalar ``value`` into ``[hard_range_min, hard_range_max]``.

        AttributeModelBase clamps at ``set_value`` — the authoritative write
        path — so an out-of-range programmatic ``model.set_value(5.0)``
        lands on the same rail as a dragged widget. Only scalar ``int`` /
        ``float`` values are clamped; tuple/vector values fall through
        unchanged because ``min()`` / ``max()`` on a tuple does a
        lexicographic compare rather than per-component clamp, and the
        metadata carries a single pair (not per-channel) so we cannot fan
        it out without a type-specific policy that Step 4.1 doesn't own.
        """
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return value
        hi = self._metadata.hard_range_max
        lo = self._metadata.hard_range_min
        if hi is not None and value > hi:
            value = hi
        if lo is not None and value < lo:
            value = lo
        return value

    # ── Edit lifecycle ──────────────────────────────────────────────────

    def begin_edit(self) -> None:
        if self._editing == 0:
            self._prev_value = self._adapter.get_value(self._attr_name)
            self._adapter.begin_edit(self._attr_name)
        self._editing += 1

    def end_edit(self) -> None:
        if self._editing == 0:
            return
        self._editing -= 1
        if self._editing > 0:
            return
        if self._metadata.change_on_edit_end and self._value != self._prev_value:
            self._ignore_notice = True
            try:
                self._adapter.set_value(self._attr_name, self._value)
            finally:
                self._ignore_notice = False
        self._adapter.end_edit(self._attr_name)
        self._prev_value = None

    # ── State queries ───────────────────────────────────────────────────

    @property
    def editing(self) -> bool:
        return self._editing > 0

    @property
    def adapter(self) -> PropertyAdapter:
        """Read-only accessor for the backing adapter.

        Step 4.3 of the property inspector implementation. ``ControlStateIndicator`` predicates
        (e.g. NotDefault checking ``adapter.clear_value`` capability) need
        access to the adapter instance without reaching into ``_adapter``.
        """
        return self._adapter

    @property
    def attr_name(self) -> str:
        """Read-only accessor for the attribute name this model addresses.

        Step 4.3: ``ControlStateIndicator`` passes the name to the NotDefault
        click handler which routes to ``adapter.clear_value(attr_name)``.
        """
        return self._attr_name

    @property
    def metadata(self) -> AttributeMetadata:
        """Read-only accessor for the attribute's metadata.

        Step 4.3: ``ControlStateIndicator`` predicates (Locked, TimeSampled,
        NotDefault) read flag fields off the metadata via the public
        property rather than the underscored ``_metadata`` attribute.
        """
        return self._metadata

    @property
    def is_ambiguous(self) -> bool:
        return self._adapter.is_ambiguous(self._attr_name)

    @property
    def is_readonly(self) -> bool:
        """True when the attribute cannot accept user writes.

        property metadata behavior: a time-sampled attribute shows an animated curve; a
        scalar write would overwrite the entire timeline without a
        time-code. A locked attribute lives in a layer the current edit
        target cannot write to. Either state disables the row's input
        widget in Step 4.2 of the property inspector implementation. Pure metadata read — no
        adapter hit, no caching — so callers can query it on every
        ``_build_ui`` pass without amortisation cost.
        """
        return bool(
            self._metadata.is_time_sampled or self._metadata.is_locked
        )

    # ── Subscription API ────────────────────────────────────────────────

    def subscribe_value_changed(self, fn: Callable[[], None]) -> _ValueChangeSubscription:
        self._subscribers.append(fn)
        return _ValueChangeSubscription(self, fn)

    def _remove_subscriber(self, fn: Callable[[], None]) -> None:
        try:
            self._subscribers.remove(fn)
        except ValueError:
            pass

    # ── Backing-store refresh ───────────────────────────────────────────

    def _on_backing_changed(self) -> None:
        """Re-read the adapter if this change was not self-induced.

        Suppressed while ``_ignore_notice`` is set (our own write is in
        flight) or while ``_editing > 0`` (the user is mid-edit; do not
        overwrite their in-progress value).
        """
        if self._ignore_notice:
            return
        if self._editing > 0:
            return
        self._value = self._adapter.get_value(self._attr_name)
        self._notify_value_changed()

    # ── Helpers ─────────────────────────────────────────────────────────

    def _notify_value_changed(self) -> None:
        for sub in list(self._subscribers):
            sub()
