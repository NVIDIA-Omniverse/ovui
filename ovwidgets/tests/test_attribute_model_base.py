# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for AttributeModelBase — Step 1.1.

Covers the done-signal matrix from the property inspector 1.1:

* write-on-end (change_on_edit_end=True) vs write-through (False)
* nested begin_edit counter — single flush on outer end_edit
* is_ambiguous passthrough
* _on_backing_changed ignored while editing or while our own write is in flight
* subscribe/unsubscribe via cancel()

Plus a handful of edge anchors: initial read in __init__, editing property,
end_edit when not editing is a no-op, subscribers notified on write-through.
"""

from typing import Any, List

from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.property.models import AttributeModelBase


class _FakeAdapter:
    """Minimal PropertyAdapter double that records adapter calls.

    Stores one "backing" value for a single attribute and exposes helpers
    so tests can drive external-change scenarios without a real USD stage.
    """

    def __init__(self, initial: Any = 0.0, ambiguous: bool = False) -> None:
        self._value: Any = initial
        self._ambiguous = ambiguous
        self.calls: List[tuple] = []

    # PropertyAdapter surface used by AttributeModelBase
    def get_value(self, attr_name: str) -> Any:
        self.calls.append(("get_value", attr_name))
        return self._value

    def set_value(self, attr_name: str, value: Any) -> None:
        self.calls.append(("set_value", attr_name, value))
        self._value = value

    def begin_edit(self, attr_name: str) -> None:
        self.calls.append(("begin_edit", attr_name))

    def end_edit(self, attr_name: str) -> None:
        self.calls.append(("end_edit", attr_name))

    def is_ambiguous(self, attr_name: str) -> bool:
        self.calls.append(("is_ambiguous", attr_name))
        return self._ambiguous

    # Test helper: simulate an external change to the backing store
    def external_set(self, value: Any) -> None:
        self._value = value


def _metadata(
    change_on_edit_end: bool = True,
    hard_range_min=None,
    hard_range_max=None,
    is_time_sampled: bool = False,
    is_locked: bool = False,
    is_authored: bool = True,
) -> AttributeMetadata:
    return AttributeMetadata(
        name="radius",
        display_name="Radius",
        type_name="float",
        value_type=float,
        group="Geometry",
        change_on_edit_end=change_on_edit_end,
        hard_range_min=hard_range_min,
        hard_range_max=hard_range_max,
        is_time_sampled=is_time_sampled,
        is_locked=is_locked,
        is_authored=is_authored,
    )


class TestConstruction:
    def test_initial_value_read_from_adapter(self):
        adapter = _FakeAdapter(initial=1.5)
        model = AttributeModelBase(adapter, "radius", _metadata())
        assert model.get_value() == 1.5
        assert ("get_value", "radius") in adapter.calls

    def test_editing_property_starts_false(self):
        model = AttributeModelBase(_FakeAdapter(), "radius", _metadata())
        assert model.editing is False


class TestWriteOnEnd:
    """change_on_edit_end=True — buffer value; flush once on end_edit."""

    def test_set_value_does_not_touch_adapter_while_editing(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=True))
        model.begin_edit()
        adapter.calls.clear()
        model.set_value(1.0)
        model.set_value(2.0)
        model.set_value(3.0)
        # No set_value calls hit the adapter during the drag.
        assert not any(c[0] == "set_value" for c in adapter.calls)
        # Buffered value is what we last wrote.
        assert model.get_value() == 3.0

    def test_end_edit_flushes_buffered_value_once(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=True))
        model.begin_edit()
        model.set_value(1.0)
        model.set_value(2.0)
        model.set_value(3.0)
        adapter.calls.clear()
        model.end_edit()
        # Exactly one set_value write, then end_edit.
        assert adapter.calls == [
            ("set_value", "radius", 3.0),
            ("end_edit", "radius"),
        ]


class TestWriteThrough:
    """change_on_edit_end=False — every set_value goes to the adapter."""

    def test_set_value_writes_through_immediately(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=False))
        model.begin_edit()
        adapter.calls.clear()
        model.set_value(1.0)
        model.set_value(2.0)
        writes = [c for c in adapter.calls if c[0] == "set_value"]
        assert writes == [
            ("set_value", "radius", 1.0),
            ("set_value", "radius", 2.0),
        ]

    def test_end_edit_does_not_double_write(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=False))
        model.begin_edit()
        model.set_value(7.0)
        adapter.calls.clear()
        model.end_edit()
        # No second set_value on end_edit — just close the undo group.
        assert adapter.calls == [("end_edit", "radius")]


class TestNestedEditing:
    def test_nested_begin_edit_counter_flushes_on_zero(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=True))
        model.begin_edit()
        model.begin_edit()  # nested
        model.set_value(5.0)
        adapter.calls.clear()
        model.end_edit()  # counter 2 -> 1: no flush
        assert not any(c[0] == "set_value" for c in adapter.calls)
        assert not any(c[0] == "end_edit" for c in adapter.calls)
        assert model.editing is True
        model.end_edit()  # counter 1 -> 0: flush
        assert ("set_value", "radius", 5.0) in adapter.calls
        assert ("end_edit", "radius") in adapter.calls
        assert model.editing is False

    def test_end_edit_without_begin_edit_is_noop(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata())
        adapter.calls.clear()
        model.end_edit()
        assert adapter.calls == []


class TestIsAmbiguous:
    def test_is_ambiguous_passthrough_true(self):
        adapter = _FakeAdapter(ambiguous=True)
        model = AttributeModelBase(adapter, "radius", _metadata())
        assert model.is_ambiguous is True

    def test_is_ambiguous_passthrough_false(self):
        adapter = _FakeAdapter(ambiguous=False)
        model = AttributeModelBase(adapter, "radius", _metadata())
        assert model.is_ambiguous is False


class TestOnBackingChanged:
    def test_suppressed_while_editing(self):
        adapter = _FakeAdapter(initial=1.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=True))
        fires: List[int] = []
        model.subscribe_value_changed(lambda: fires.append(1))
        model.begin_edit()
        model.set_value(2.0)
        fires.clear()
        adapter.external_set(99.0)
        model._on_backing_changed()
        # Mid-edit: value must not be clobbered and no fan-out.
        assert model.get_value() == 2.0
        assert fires == []

    def test_refreshes_when_not_editing(self):
        adapter = _FakeAdapter(initial=1.0)
        model = AttributeModelBase(adapter, "radius", _metadata())
        fires: List[int] = []
        model.subscribe_value_changed(lambda: fires.append(1))
        adapter.external_set(42.0)
        model._on_backing_changed()
        assert model.get_value() == 42.0
        assert fires == [1]

    def test_suppressed_during_self_induced_write(self):
        """Write-through mode: set_value calls adapter.set_value, and if the
        adapter fires back into _on_backing_changed mid-call (Tf.Notice-style
        reentrancy), the _ignore_notice guard must suppress it so _value is
        not clobbered from an in-flight read.
        """
        adapter = _FakeAdapter(initial=1.0)
        reentered: List[Any] = []

        # Patch adapter.set_value to re-enter _on_backing_changed from inside
        # the adapter call — this is exactly the pattern AttributeModelBase guards.
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=False))

        original_set = adapter.set_value

        def reentrant_set(attr_name: str, value: Any) -> None:
            original_set(attr_name, value)
            reentered.append(model.get_value())
            model._on_backing_changed()
            reentered.append(model.get_value())

        adapter.set_value = reentrant_set  # type: ignore[method-assign]
        model.set_value(5.0)
        # Both snapshots taken during the reentrant call saw _value == 5.0
        # (_ignore_notice blocked the refresh from running).
        assert reentered == [5.0, 5.0]
        assert model.get_value() == 5.0


class TestSubscribeValueChanged:
    def test_subscribe_fires_on_write(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=False))
        fires: List[float] = []
        model.subscribe_value_changed(lambda: fires.append(model.get_value()))
        model.set_value(1.0)
        model.set_value(2.0)
        assert fires == [1.0, 2.0]

    def test_cancel_unsubscribes(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata(change_on_edit_end=False))
        fires: List[int] = []
        sub = model.subscribe_value_changed(lambda: fires.append(1))
        model.set_value(1.0)
        sub.cancel()
        model.set_value(2.0)
        assert fires == [1]

    def test_cancel_is_idempotent(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata())
        sub = model.subscribe_value_changed(lambda: None)
        sub.cancel()
        # Second cancel must not raise and must not mutate state.
        sub.cancel()


class TestHardRangeClamp:
    """Step 4.1 — ``AttributeModelBase.set_value`` clamps scalar writes into
    ``[hard_range_min, hard_range_max]`` before they land in ``_value``
    before notifying the adapter. The clamp fires on every call path — buffered
    drag, write-through, programmatic — so the adapter and downstream
    subscribers never see an out-of-range value.
    """

    def test_above_hard_max_clamps_down(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter, "radius", _metadata(hard_range_max=3.0),
        )
        model.set_value(5.0)
        assert model.get_value() == 3.0

    def test_below_hard_min_clamps_up(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter, "radius", _metadata(hard_range_min=0.0),
        )
        model.set_value(-2.5)
        assert model.get_value() == 0.0

    def test_in_range_value_unchanged(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter,
            "radius",
            _metadata(hard_range_min=0.0, hard_range_max=1.0),
        )
        model.set_value(0.5)
        assert model.get_value() == 0.5

    def test_no_range_leaves_value_unbounded(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(adapter, "radius", _metadata())
        model.set_value(1e9)
        assert model.get_value() == 1e9

    def test_write_through_adapter_receives_clamped_value(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter,
            "radius",
            _metadata(change_on_edit_end=False, hard_range_max=3.0),
        )
        model.set_value(5.0)
        writes = [c for c in adapter.calls if c[0] == "set_value"]
        assert writes == [("set_value", "radius", 3.0)]

    def test_buffered_flush_writes_clamped_value(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter,
            "radius",
            _metadata(change_on_edit_end=True, hard_range_max=3.0),
        )
        model.begin_edit()
        model.set_value(5.0)
        adapter.calls.clear()
        model.end_edit()
        assert adapter.calls == [
            ("set_value", "radius", 3.0),
            ("end_edit", "radius"),
        ]

    def test_only_min_set(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter, "radius", _metadata(hard_range_min=-1.0),
        )
        model.set_value(-5.0)
        assert model.get_value() == -1.0
        # No upper bound — large positive value passes through.
        model.set_value(1000.0)
        assert model.get_value() == 1000.0

    def test_only_max_set(self):
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter, "radius", _metadata(hard_range_max=2.0),
        )
        model.set_value(10.0)
        assert model.get_value() == 2.0
        model.set_value(-1000.0)
        assert model.get_value() == -1000.0

    def test_integer_value_clamped(self):
        adapter = _FakeAdapter(initial=0)
        meta = AttributeMetadata(
            name="count",
            display_name="Count",
            type_name="int",
            value_type=int,
            group="X",
            hard_range_min=0,
            hard_range_max=10,
        )
        model = AttributeModelBase(adapter, "count", meta)
        model.set_value(42)
        assert model.get_value() == 10
        model.set_value(-5)
        assert model.get_value() == 0

    def test_tuple_value_not_clamped(self):
        """Vector tuples fall through unchanged.

        ``min()`` / ``max()`` on a tuple does lexicographic compare and
        the single range pair on the metadata does not describe a
        per-channel policy. Tuples must pass through untouched so a
        Vec3 write like ``(0, 0, 5)`` isn't silently rewritten to
        ``(0, 0, 0)``.
        """
        adapter = _FakeAdapter(initial=(0.0, 0.0, 0.0))
        meta = AttributeMetadata(
            name="v",
            display_name="V",
            type_name="float3",
            value_type=tuple,
            group="X",
            hard_range_min=0.0,
            hard_range_max=1.0,
        )
        model = AttributeModelBase(adapter, "v", meta)
        model.set_value((0.5, 5.0, -2.0))
        assert model.get_value() == (0.5, 5.0, -2.0)

    def test_bool_value_not_clamped(self):
        """``bool`` subclasses ``int`` in Python — ensure the clamp's
        type guard keeps it out of the comparison arm so a ``True``
        write doesn't get coerced by an unrelated numeric range."""
        adapter = _FakeAdapter(initial=False)
        meta = AttributeMetadata(
            name="b",
            display_name="B",
            type_name="bool",
            value_type=bool,
            group="X",
            hard_range_min=10,
            hard_range_max=20,
        )
        model = AttributeModelBase(adapter, "b", meta)
        model.set_value(True)
        assert model.get_value() is True
        model.set_value(False)
        assert model.get_value() is False


class TestIsReadonly:
    """Step 4.2 — ``AttributeModelBase.is_readonly`` reads
    ``metadata.is_time_sampled or metadata.is_locked`` so rows can gate
    ``widget.enabled`` without re-deriving the OR. Pure metadata read,
    no adapter hit (property metadata behavior, the property inspector 4 Step 4.2).
    """

    def test_default_not_readonly(self):
        model = AttributeModelBase(_FakeAdapter(), "radius", _metadata())
        assert model.is_readonly is False

    def test_time_sampled_is_readonly(self):
        model = AttributeModelBase(
            _FakeAdapter(), "radius", _metadata(is_time_sampled=True),
        )
        assert model.is_readonly is True

    def test_locked_is_readonly(self):
        model = AttributeModelBase(
            _FakeAdapter(), "radius", _metadata(is_locked=True),
        )
        assert model.is_readonly is True

    def test_both_is_readonly(self):
        """Both flags set — still one readonly state (OR, not XOR)."""
        model = AttributeModelBase(
            _FakeAdapter(),
            "radius",
            _metadata(is_time_sampled=True, is_locked=True),
        )
        assert model.is_readonly is True

    def test_not_authored_is_NOT_readonly(self):
        """``is_authored=False`` is a visual hint (label muted); it does
        NOT disable the widget — users must be able to author a value
        into an unauthored attribute to transition it to authored."""
        model = AttributeModelBase(
            _FakeAdapter(), "radius", _metadata(is_authored=False),
        )
        assert model.is_readonly is False

    def test_is_readonly_does_not_touch_adapter(self):
        """Regression guard: the property is a pure metadata read, so a
        tight loop of ``model.is_readonly`` lookups does NOT fan out to
        ``adapter.get_value`` / ``adapter.is_ambiguous`` / etc."""
        adapter = _FakeAdapter(initial=0.0)
        model = AttributeModelBase(
            adapter, "radius", _metadata(is_time_sampled=True),
        )
        adapter.calls.clear()
        for _ in range(10):
            assert model.is_readonly is True
        assert adapter.calls == []

    def test_is_readonly_reflects_metadata_mutation(self):
        """``AttributeMetadata`` is a mutable dataclass; if a higher layer
        swaps ``is_locked`` on the live metadata object, the model picks
        it up on the next read. Pins the "no caching" contract."""
        meta = _metadata()
        model = AttributeModelBase(_FakeAdapter(), "radius", meta)
        assert model.is_readonly is False
        meta.is_locked = True
        assert model.is_readonly is True
        meta.is_locked = False
        meta.is_time_sampled = True
        assert model.is_readonly is True
