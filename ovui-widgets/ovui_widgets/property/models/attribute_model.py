# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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

Typed values that cannot be stored are refused before any write: a value
that is not a finite number for a transform operation
(``xformOp:*``), and a finite value that does not fit a 16-bit or 32-bit
float attribute (it would become infinity). A refusal shows a message
that names the field and the cause.
"""

import math
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter
from ovui_data_adapters.common.matrix_transform import MatrixPartError, with_matrix_part

from ovui_widgets.common.error_reporter import ErrorReporter

_REPORT_MODULE = "Property Inspector"

# Storage of the float attributes that hold less than a double: the
# ``struct`` format that rounds a Python float to that storage (it raises
# OverflowError when the result would be infinity), the words for the
# message, and the largest finite value.
_FLOAT_STORAGES = {
    "half": ("<e", "16-bit float", 65504.0),
    "float": ("<f", "32-bit float", 3.4028234663852886e38),
}
# USD role types put the precision in the last letter: color3f, point3h, quatf.
_ROLE_TYPE_PREFIXES = ("color", "point", "normal", "vector", "texcoord", "quat")
_ROLE_TYPE_STORAGES = {"f": "float", "h": "half"}


def _float_storage(type_name: str) -> Optional[str]:
    """``"half"`` or ``"float"`` for an attribute of 16-bit or 32-bit floats.

    ``None`` for double attributes and for types that are not floats.
    """
    name = (type_name or "").lower()
    for storage in ("half", "float"):
        if name.startswith(storage):
            return storage
    if name.startswith(_ROLE_TYPE_PREFIXES):
        return _ROLE_TYPE_STORAGES.get(name[-1:])
    return None


def _number_text(value: Any) -> str:
    """The value as a user reads it: ``nan``, ``inf``, ``-inf``, ``1e+308``."""
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return f"{value:.15g}"
    return str(value)


def _refusal_cause(metadata: AttributeMetadata, value: Any) -> Optional[str]:
    """The reason why ``value`` must not be stored, or ``None`` when it can be.

    Only a float is checked: a drag field gives floats, and an integer is
    always finite.
    """
    if not isinstance(value, float):
        return None
    number = value
    if not math.isfinite(number):
        if metadata.name.startswith("xformOp:"):
            return "A transform value must be a finite number."
        return None
    storage = _float_storage(metadata.type_name)
    if storage is None:
        return None
    struct_format, words, largest = _FLOAT_STORAGES[storage]
    try:
        struct.pack(struct_format, number)
    except OverflowError:
        return (
            f"It is outside the range of a {words} "
            f"(largest value {largest:.8g})."
        )
    return None


def _same_number(a: Any, b: Any) -> bool:
    if a == b:
        return True
    return (
        isinstance(a, float) and isinstance(b, float)
        and math.isnan(a) and math.isnan(b)
    )


class _ValueChangeSubscription:
    """Handle returned by ``subscribe_value_changed``.

    Mirrors the ``_UsdPropertySubscription`` pattern in
    ``ovui_widgets.stage/usd_property_adapter.py``: callers hold the handle for the
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
        # Buffered channel edits (index -> value) for end_edit() to flush.
        self._pending_components: Dict[int, Any] = {}
        # Buffered edits of a matrix part: (part, index) -> (value, field name).
        self._pending_matrix_parts: Dict[Tuple[str, int], Tuple[float, str]] = {}
        self._ignore_notice: bool = False
        self._subscribers: List[Callable[[], None]] = []
        # True after a write-through write of the active edit: a refusal
        # must then put back the value from before the edit.
        self._wrote_in_edit: bool = False

    # ── Value read/write ────────────────────────────────────────────────

    def get_value(self) -> Any:
        return self._value

    def set_value(self, value: Any, field: Optional[str] = None) -> bool:
        """Store ``value``; ``field`` names the field in messages.

        Return ``False`` when the value is refused: the old value stays,
        and a message names the field and the cause. Else return ``True``
        (also when the hard range changed the stored value).
        """
        label = field or self._metadata.display_name
        for component in self._new_components(value):
            cause = _refusal_cause(self._metadata, component)
            if cause is not None:
                self._refuse(label, component, cause)
                return False
        value = self._apply_hard_range_clamp(value)
        self._value = value
        self._pending_components.clear()
        self._pending_matrix_parts.clear()
        if not self._metadata.change_on_edit_end:
            # Write-through: hit the adapter immediately. The _ignore_notice
            # guard stops our own adapter change from triggering a
            # _on_backing_changed re-read that would clobber _value.
            self._ignore_notice = True
            try:
                self._wrote_in_edit = self._editing > 0
                self._adapter.set_value(self._attr_name, value)
            finally:
                self._ignore_notice = False
        # Buffered mode: _value is held; flush happens in end_edit().
        self._notify_value_changed()
        return True

    def set_component_value(
        self, index: int, vector: Any, field: Optional[str] = None
    ) -> bool:
        """Set channel ``index`` of a vector attribute.

        ``vector`` is the value that the row shows after the edit. The
        adapter writes only ``vector[index]``: each object keeps its own
        values in the other channels, so a "Mixed" channel stays mixed.
        ``field`` names the channel in messages. Return ``False`` when the
        value is refused (the old value stays, and a message names the
        field and the cause), else ``True``.
        """
        component = vector[index]
        cause = _refusal_cause(self._metadata, component)
        if cause is not None:
            self._refuse(field or self._metadata.display_name, component, cause)
            return False
        self._value = vector
        if not self._metadata.change_on_edit_end:
            self._ignore_notice = True
            try:
                self._wrote_in_edit = self._editing > 0
                self._adapter.set_component_value(
                    self._attr_name, index, component
                )
            finally:
                self._ignore_notice = False
        else:
            # Buffered mode: end_edit() writes only the edited channels.
            self._pending_components[index] = component
        self._notify_value_changed()
        return True

    def set_matrix_part_value(
        self,
        part: str,
        index: int,
        value: float,
        start: Any,
        field: Optional[str] = None,
    ) -> bool:
        """Set channel ``index`` of the Translate, Rotate or Scale part of a
        4x4 transform matrix.

        ``start`` is the matrix that the row showed at the start of the
        edit, or ``None`` when the row shows no matrix. The adapter changes
        only this channel of this part: each object keeps its own matrix in
        the other parts and channels. ``field`` names the field in messages.
        Return ``False`` when the value is refused (the old value stays, and
        a message names the field and the cause), else ``True``. A part that
        a matrix cannot give (Rotate and Scale of a matrix with a value that
        is not a finite number) is refused in the same way, also when only
        one of the selected objects has such a matrix.
        """
        label = field or self._metadata.display_name
        cause = _refusal_cause(self._metadata, value)
        if cause is not None:
            self._refuse(label, value, cause)
            return False
        shown = None
        if start is not None:
            try:
                shown = with_matrix_part(start, part, index, value)
            except MatrixPartError as refused:
                self._refuse(label, value, str(refused))
                return False
        if not self._metadata.change_on_edit_end:
            wrote_before = self._wrote_in_edit
            self._ignore_notice = True
            try:
                self._wrote_in_edit = self._editing > 0
                self._adapter.set_matrix_part_value(
                    self._attr_name, part, index, value
                )
            except MatrixPartError as refused:
                # The adapter refuses before it writes any object.
                self._wrote_in_edit = wrote_before
                self._ignore_notice = False
                self._refuse(label, value, str(refused))
                return False
            finally:
                self._ignore_notice = False
        else:
            # Buffered mode: end_edit() writes only the edited channels.
            self._pending_matrix_parts[(part, index)] = (value, label)
        if shown is not None:
            self._value = shown
        self._notify_value_changed()
        return True

    def _new_components(self, value: Any) -> List[Any]:
        """The numbers of ``value`` that differ from the current value.

        A matrix row gives all cells with one cell changed; only that cell
        is checked, so a cell with a non-finite value from the file does not
        block an edit of another cell.
        """
        if not isinstance(value, (tuple, list)):
            return [value]
        current = self._value
        if not isinstance(current, (tuple, list)) or len(current) != len(value):
            return list(value)
        return [
            new for new, old in zip(value, current) if not _same_number(new, old)
        ]

    def _refuse(self, field: str, value: Any, cause: str) -> None:
        """Do not store ``value``: tell the user, and keep the old value."""
        self._report(
            f"{field}: {_number_text(value)} is not accepted. {cause} "
            "The old value stays."
        )
        self._restore_edit_start()

    def _restore_edit_start(self) -> None:
        """Put back the value from before the active edit.

        A drag field writes each value that the user types, key by key
        (for example 1, 1000, 1e+30 while 1e+308 is typed). After a
        refusal, every selected object gets its value from before the edit
        again. The adapter restores its exact start state, and a new
        transaction takes the rest of the edit.
        """
        if self._editing == 0:
            return
        if self._metadata.change_on_edit_end:
            self._pending_components.clear()
            self._pending_matrix_parts.clear()
            self._value = self._prev_value
            return
        if not self._wrote_in_edit:
            return
        self._ignore_notice = True
        try:
            self._adapter.cancel_edit(self._attr_name)
            self._wrote_in_edit = False
            self._prev_value = self._adapter.get_value(self._attr_name)
            self._adapter.begin_edit(self._attr_name)
        finally:
            self._ignore_notice = False
        self._value = self._prev_value
        self._notify_value_changed()

    def _report(self, message: str) -> None:
        ErrorReporter.log_warning(_REPORT_MODULE, message)
        ErrorReporter.show_warning(message)

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
            self._pending_components.clear()
            self._pending_matrix_parts.clear()
            self._wrote_in_edit = False
            self._adapter.begin_edit(self._attr_name)
        self._editing += 1

    def end_edit(self) -> None:
        if self._editing == 0:
            return
        self._editing -= 1
        if self._editing > 0:
            return
        try:
            # Edited channels are always written: the shown value is
            # that of one object, so an equal shown value does not mean
            # that every object already has the new channel value.
            if self._metadata.change_on_edit_end and (
                self._pending_components
                or self._pending_matrix_parts
                or self._value != self._prev_value
            ):
                self._ignore_notice = True
                try:
                    if self._pending_components:
                        for index, component in self._pending_components.items():
                            self._adapter.set_component_value(
                                self._attr_name, index, component
                            )
                    elif self._pending_matrix_parts:
                        for (part, index), (component, label) in self._pending_matrix_parts.items():
                            self._adapter.set_matrix_part_value(
                                self._attr_name, part, index, component
                            )
                    else:
                        self._adapter.set_value(self._attr_name, self._value)
                finally:
                    self._ignore_notice = False
        except MatrixPartError as refused:
            # A selected object has a matrix that cannot give this part:
            # nothing of this edit stays, and the message names the cause.
            self._adapter.cancel_edit(self._attr_name)
            self._prev_value = None
            self._pending_components.clear()
            self._pending_matrix_parts.clear()
            self._report(
                f"{label}: {_number_text(component)} is not accepted. "
                f"{refused} The old value stays."
            )
            self._value = self._adapter.get_value(self._attr_name)
            self._notify_value_changed()
            return
        except BaseException as primary:  # noqa: BLE001 — structured cancel
            # The buffered write failed: the adapter transaction must not
            # stay active. Cancel it (restoring its exact baseline and
            # removing partial authorship) without displacing the primary
            # throwable; a cancel failure is attached as a note.
            try:
                self._adapter.cancel_edit(self._attr_name)
            except BaseException as secondary:  # noqa: BLE001 — noted
                add_note = getattr(primary, "add_note", None)
                if callable(add_note):
                    add_note(
                        "edit cancellation also failed: "
                        f"{type(secondary).__name__}: {secondary}"
                    )
            self._prev_value = None
            self._pending_components.clear()
            self._pending_matrix_parts.clear()
            raise
        self._adapter.end_edit(self._attr_name)
        self._prev_value = None
        self._pending_components.clear()
        self._pending_matrix_parts.clear()

    def cancel_edit(self) -> None:
        """Cancel the active edit transaction without recording history.

        Used when the user cancels the edit (Escape in a number field) and
        by rows whose commit raised after ``begin_edit``: the adapter
        restores its exact pre-edit baseline (removing any partial
        authorship), the model's edit state resets, and the model shows
        the restored value.
        """
        if self._editing == 0:
            return
        self._editing = 0
        self._prev_value = None
        self._pending_components.clear()
        self._pending_matrix_parts.clear()
        self._wrote_in_edit = False
        self._adapter.cancel_edit(self._attr_name)
        self._value = self._adapter.get_value(self._attr_name)
        self._notify_value_changed()

    # ── State queries ───────────────────────────────────────────────────

    @property
    def editing(self) -> bool:
        return self._editing > 0

    @property
    def adapter(self) -> PropertyAdapter:
        """Read-only accessor for the backing adapter.

        Step 4.3 of the property inspector implementation.
        ``ControlStateIndicator`` predicates (e.g. NotDefault checking the
        adapter's explicit property capabilities) need access to the adapter
        instance without reaching into ``_adapter``.
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
