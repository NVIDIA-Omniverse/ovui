# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the group-header context menu — Step 5.3.

the property inspector 5.3 done-signal matrix:

* Right-click on a group frame routes through
  :meth:`AttributeGroupWidget._on_mouse_released` with ``button == 1``
  → the ``on_context_menu`` callback fires with ``(x, y)``.
* ``copy_group`` snapshots every prop value in a group (and all
  nested sub-groups) into the module-level clipboard under the
  requested ``clipboard_id``.
* ``paste_group`` reads the clipboard and writes each matching attr
  via ``adapter.set_value`` wrapped in ``begin_edit`` / ``end_edit``.
* ``reset_group`` calls ``adapter.clear_value`` on every group attr.
* ``can_paste`` / ``can_reset`` disable the menu items in the
  obvious dead-end cases (empty clipboard, no overlap, all locked,
  adapter does not advertise ``clear_values`` support).
* ``PropertyWindow._build_group_children`` wires each
  :class:`AttributeGroupWidget` with an ``on_context_menu`` callback
  that captures the correct :class:`UiDisplayGroup` — closures do
  *not* leak the last iteration's reference.

The tests exercise the pure helpers against a
:class:`MockPropertyAdapter` (no USD, no ``omni.ui`` import), plus
headless behavioural tests for ``AttributeGroupWidget`` that pin the
right-click routing. The ``show_group_context_menu`` driver itself
is not tested end-to-end because building a real ``ui.Menu`` requires
an initialised ``omni.ui`` root — the disabled/enabled predicate
wiring (the observable piece) is covered by the pure-helper tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from ovui_data_adapters.common import (
    AdapterCapability,
    AttributeMetadata,
    PropertyCapabilities,
)

from ovui_widgets.common.testing.mock_property import MockPropertyAdapter
from ovui_widgets.property.parts import UiDisplayGroup
from ovui_widgets.property.parts.group_context_menu import (
    DEFAULT_CLIPBOARD_ID,
    can_paste,
    can_reset,
    clear_clipboard,
    copy_group,
    get_clipboard,
    iter_group_props,
    paste_group,
    reset_group,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _meta(
    name: str,
    group: str = "",
    is_locked: bool = False,
    is_authored: bool = True,
) -> AttributeMetadata:
    """Minimal AttributeMetadata for grouping/clipboard tests.

    Default ``is_authored=True`` so :func:`can_reset` doesn't short-
    circuit the predicate unrelated branches; override when a test
    specifically pins the unauthored behaviour.
    """
    return AttributeMetadata(
        name=name,
        display_name=name,
        type_name="float",
        value_type=float,
        group=group,
        is_locked=is_locked,
        is_authored=is_authored,
    )


def _build_group(
    props: Dict[str, Any],
    metas: Optional[Dict[str, AttributeMetadata]] = None,
) -> UiDisplayGroup:
    """Build a single flat :class:`UiDisplayGroup` with the given props.

    ``props`` is ``{name: initial_value}``; the value is stored on the
    adapter via :meth:`MockPropertyAdapter.set_value`. Returns a group
    named ``"Flat"``; tests that want a different name should rebuild.
    """
    if metas is None:
        metas = {name: _meta(name) for name in props}
    group = UiDisplayGroup(name="Flat")
    for name in props:
        group.props.append(metas[name])
    return group


def _adapter_with(
    values: Dict[str, Any],
    metas: Optional[Dict[str, AttributeMetadata]] = None,
    clear_value_impl: Optional[Any] = None,
) -> MockPropertyAdapter:
    """Instantiate a :class:`MockPropertyAdapter` seeded with ``values``.

    When ``clear_value_impl`` is provided it replaces the adapter's
    ``clear_value`` method on the instance (not the class). Most reset
    tests use :class:`_RecordingAdapter` instead so the action path and
    declared ``clear_values`` capability are both explicit.
    """
    if metas is None:
        metas = {name: _meta(name) for name in values}
    adapter = MockPropertyAdapter(paths=["/World/X"], attributes=metas)
    for name, value in values.items():
        adapter.set_value(name, value)
    if clear_value_impl is not None:
        adapter.clear_value = clear_value_impl  # type: ignore[method-assign]
    return adapter


def _property_capabilities(clear_values_supported: bool) -> PropertyCapabilities:
    return PropertyCapabilities(
        clear_values=(
            AdapterCapability.supported()
            if clear_values_supported
            else AdapterCapability.unsupported("clear disabled by test adapter")
        )
    )


class _RecordingAdapter(MockPropertyAdapter):
    """Adapter subclass that records each ``clear_value`` + edit call.

    The reset gate reads :meth:`get_capabilities`, so tests can toggle
    ``clear_values_supported`` without changing the adapter class or its
    ``clear_value`` implementation.
    """

    def __init__(
        self,
        *args: Any,
        clear_values_supported: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._clear_values_supported = clear_values_supported
        self.cleared: List[str] = []
        self.edit_sequence: List[str] = []

    def get_capabilities(self) -> PropertyCapabilities:
        return _property_capabilities(self._clear_values_supported)

    def clear_value(self, attr_name: str) -> None:
        self.cleared.append(attr_name)
        self._values.pop(attr_name, None)

    def begin_edit(self, attr_name: str) -> None:  # type: ignore[override]
        super().begin_edit(attr_name)
        self.edit_sequence.append(f"begin:{attr_name}")

    def end_edit(self, attr_name: str) -> None:  # type: ignore[override]
        super().end_edit(attr_name)
        self.edit_sequence.append(f"end:{attr_name}")

    def set_value(self, attr_name: str, value: Any) -> None:  # type: ignore[override]
        super().set_value(attr_name, value)
        self.edit_sequence.append(f"set:{attr_name}={value}")


def _nested_group() -> UiDisplayGroup:
    """Build a two-level group with one attr per leaf.

    Structure::

        Transform
        ├── Translate
        │   └── translate_x = 1.0
        ├── Rotate
        │   └── rotate_z = 2.0
        └── flag       = True  (leaf prop under Transform itself)

    Tests reuse this to pin the "recursive walk" contract —
    ``iter_group_props`` must yield *all five* leaves across the three
    nesting levels regardless of branch order.
    """
    root = UiDisplayGroup(name="Transform")
    translate = UiDisplayGroup(name="Translate")
    translate.props.append(_meta("translate_x"))
    rotate = UiDisplayGroup(name="Rotate")
    rotate.props.append(_meta("rotate_z"))
    root.sub_groups["Translate"] = translate
    root.sub_groups["Rotate"] = rotate
    root.props.append(_meta("flag"))
    return root


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_clipboard():
    """Drop every clipboard namespace before and after each test.

    The clipboard module-level dict survives across tests by design —
    so Copy in test A could pollute Paste in test B. Autouse fixture
    forces a clean slate so ordering doesn't matter.
    """
    clear_clipboard()
    yield
    clear_clipboard()


# ---------------------------------------------------------------------------
# iter_group_props — depth-first recursive traversal
# ---------------------------------------------------------------------------


class TestIterGroupProps:
    """``iter_group_props`` is the primitive every other helper walks on."""

    def test_flat_group_yields_all_props(self) -> None:
        group = UiDisplayGroup(name="Flat")
        a = _meta("a")
        b = _meta("b")
        group.props.extend([a, b])
        assert list(iter_group_props(group)) == [a, b]

    def test_nested_group_walks_all_levels(self) -> None:
        root = _nested_group()
        names = [p.name for p in iter_group_props(root)]
        # Sub-groups yielded before props at every level — see
        # :meth:`UiDisplayGroup.get_children`.
        assert set(names) == {"translate_x", "rotate_z", "flag"}

    def test_empty_group_yields_nothing(self) -> None:
        assert list(iter_group_props(UiDisplayGroup(name="Empty"))) == []

    def test_deeply_nested_group_still_walks(self) -> None:
        """Three-level ``A.B.C`` tree with a single leaf should yield it."""
        root = UiDisplayGroup(name="A")
        b = UiDisplayGroup(name="B")
        c = UiDisplayGroup(name="C")
        leaf = _meta("leaf")
        c.props.append(leaf)
        b.sub_groups["C"] = c
        root.sub_groups["B"] = b
        assert list(iter_group_props(root)) == [leaf]


# ---------------------------------------------------------------------------
# copy_group — snapshots values into the clipboard
# ---------------------------------------------------------------------------


class TestCopyGroup:

    def test_copy_stores_flat_group_values(self) -> None:
        group = _build_group({"radius": 1.0, "height": 2.0})
        adapter = _adapter_with({"radius": 1.0, "height": 2.0})
        snapshot = copy_group(adapter, group)
        assert snapshot == {"radius": 1.0, "height": 2.0}
        assert get_clipboard() == {"radius": 1.0, "height": 2.0}

    def test_copy_walks_nested_sub_groups(self) -> None:
        """A Copy on ``Transform`` captures every leaf under it."""
        group = _nested_group()
        adapter = _adapter_with(
            {"translate_x": 1.0, "rotate_z": 2.0, "flag": True},
        )
        copy_group(adapter, group)
        cb = get_clipboard()
        assert cb == {"translate_x": 1.0, "rotate_z": 2.0, "flag": True}

    def test_copy_uses_namespace_clipboard_id(self) -> None:
        """Two different ``clipboard_id``s don't overwrite each other."""
        group = _build_group({"x": 1.0})
        adapter = _adapter_with({"x": 1.0})
        copy_group(adapter, group, clipboard_id="group_a")
        copy_group(adapter, group, clipboard_id="group_b")
        assert get_clipboard("group_a") == {"x": 1.0}
        assert get_clipboard("group_b") == {"x": 1.0}
        # The default namespace is untouched.
        assert get_clipboard() == {}

    def test_copy_overwrites_previous_snapshot(self) -> None:
        group = _build_group({"x": 1.0})
        adapter = _adapter_with({"x": 1.0})
        copy_group(adapter, group)
        adapter.set_value("x", 99.0)
        copy_group(adapter, group)
        assert get_clipboard() == {"x": 99.0}

    def test_copy_preserves_ambiguous_none(self) -> None:
        """An ambiguous attr (``get_value`` → ``None``) is stored as ``None``.

        Mock adapter returns ``None`` when values differ across
        selected paths. Copy records the ``None`` — Paste will later
        skip it so a concrete target doesn't get clobbered with mixed.
        """
        metas = {"x": _meta("x")}
        adapter = MockPropertyAdapter(
            paths=["/World/A", "/World/B"],
            attributes=metas,
        )
        adapter.set_path_value("/World/A", "x", 1.0)
        adapter.set_path_value("/World/B", "x", 2.0)
        assert adapter.is_ambiguous("x") is True
        group = _build_group({"x": 0.0}, metas=metas)
        copy_group(adapter, group)
        assert get_clipboard() == {"x": None}

    def test_default_clipboard_id_is_ovgear_group(self) -> None:
        """Plan pins ``clipboard_id="ovgear_group"`` as the default."""
        assert DEFAULT_CLIPBOARD_ID == "ovgear_group"


# ---------------------------------------------------------------------------
# paste_group — applies clipboard onto matching attrs
# ---------------------------------------------------------------------------


class TestPasteGroup:

    def test_paste_writes_via_begin_end_edit(self) -> None:
        """Every paste must wrap ``set_value`` in begin/end_edit for the adapter."""
        metas = {"x": _meta("x")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("x", 5.0)
        group = _build_group({"x": 5.0}, metas=metas)
        copy_group(adapter, group)
        adapter.set_value("x", 0.0)  # user drifted the value
        adapter.edit_sequence = []  # drop the prep writes from the log

        written = paste_group(adapter, group)
        assert written == 1
        # The helper wraps set_value in begin/end_edit.
        assert adapter.edit_sequence == [
            "begin:x",
            "set:x=5.0",
            "end:x",
        ]
        assert adapter.get_value("x") == 5.0

    def test_paste_writes_all_matching_attrs(self) -> None:
        metas = {name: _meta(name) for name in ("a", "b", "c")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        for name, value in (("a", 1.0), ("b", 2.0), ("c", 3.0)):
            adapter.set_value(name, value)
        group = _build_group({"a": 0.0, "b": 0.0, "c": 0.0}, metas=metas)
        copy_group(adapter, group)
        for name in ("a", "b", "c"):
            adapter.set_value(name, 99.0)

        written = paste_group(adapter, group)
        assert written == 3
        assert adapter.get_value("a") == 1.0
        assert adapter.get_value("b") == 2.0
        assert adapter.get_value("c") == 3.0

    def test_paste_walks_nested_sub_groups(self) -> None:
        """Paste on ``Transform`` writes every nested leaf's value."""
        metas = {
            "translate_x": _meta("translate_x"),
            "rotate_z": _meta("rotate_z"),
            "flag": _meta("flag"),
        }
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("translate_x", 1.0)
        adapter.set_value("rotate_z", 2.0)
        adapter.set_value("flag", True)
        group = UiDisplayGroup(name="Transform")
        t = UiDisplayGroup(name="Translate")
        t.props.append(metas["translate_x"])
        r = UiDisplayGroup(name="Rotate")
        r.props.append(metas["rotate_z"])
        group.sub_groups["Translate"] = t
        group.sub_groups["Rotate"] = r
        group.props.append(metas["flag"])
        copy_group(adapter, group)

        # Drift every attr so the paste has work to do.
        adapter.set_value("translate_x", 99.0)
        adapter.set_value("rotate_z", 99.0)
        adapter.set_value("flag", False)

        written = paste_group(adapter, group)
        assert written == 3
        assert adapter.get_value("translate_x") == 1.0
        assert adapter.get_value("rotate_z") == 2.0
        assert adapter.get_value("flag") is True

    def test_paste_on_empty_clipboard_is_noop(self) -> None:
        metas = {"x": _meta("x")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("x", 5.0)
        adapter.edit_sequence = []
        group = _build_group({"x": 5.0}, metas=metas)
        # Clipboard empty: paste_group returns 0 and touches nothing.
        written = paste_group(adapter, group)
        assert written == 0
        assert adapter.edit_sequence == []

    def test_paste_skips_non_matching_attrs(self) -> None:
        """Clipboard has ``{foo: 1}``; group has only ``bar``. Zero writes."""
        metas_src = {"foo": _meta("foo")}
        adapter_src = _adapter_with({"foo": 1.0}, metas=metas_src)
        group_src = _build_group({"foo": 1.0}, metas=metas_src)
        copy_group(adapter_src, group_src)

        metas_dst = {"bar": _meta("bar")}
        adapter_dst = _RecordingAdapter(
            paths=["/World/X"], attributes=metas_dst,
        )
        adapter_dst.set_value("bar", 9.0)
        adapter_dst.edit_sequence = []
        group_dst = _build_group({"bar": 9.0}, metas=metas_dst)
        written = paste_group(adapter_dst, group_dst)
        assert written == 0
        assert adapter_dst.get_value("bar") == 9.0
        assert adapter_dst.edit_sequence == []

    def test_paste_skips_locked_attrs(self) -> None:
        """An attr with ``is_locked=True`` must not receive the paste."""
        metas = {"x": _meta("x", is_locked=True)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("x", 5.0)
        group = _build_group({"x": 5.0}, metas=metas)
        copy_group(adapter, group)
        adapter.set_value("x", 0.0)
        adapter.edit_sequence = []
        written = paste_group(adapter, group)
        assert written == 0
        assert adapter.edit_sequence == []
        assert adapter.get_value("x") == 0.0

    def test_paste_skips_none_values(self) -> None:
        """Ambiguous-at-copy attrs (``None`` in clipboard) are skipped.

        Prevents a Paste from overwriting a concrete target with
        "mixed". Mirrors Kit's type-check shape (§17.4): unknown
        values don't get written.
        """
        metas = {"x": _meta("x")}
        adapter_src = MockPropertyAdapter(
            paths=["/World/A", "/World/B"],
            attributes=metas,
        )
        adapter_src.set_path_value("/World/A", "x", 1.0)
        adapter_src.set_path_value("/World/B", "x", 2.0)
        group = _build_group({"x": 0.0}, metas=metas)
        copy_group(adapter_src, group)

        adapter_dst = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter_dst.set_value("x", 5.0)
        adapter_dst.edit_sequence = []
        written = paste_group(adapter_dst, group)
        assert written == 0
        assert adapter_dst.edit_sequence == []
        assert adapter_dst.get_value("x") == 5.0

    def test_paste_namespace_isolation(self) -> None:
        """Paste on ``group_a`` ignores what ``group_b`` copied."""
        metas = {"x": _meta("x")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("x", 5.0)
        group = _build_group({"x": 5.0}, metas=metas)
        copy_group(adapter, group, clipboard_id="group_b")
        adapter.set_value("x", 0.0)
        adapter.edit_sequence = []

        written = paste_group(adapter, group, clipboard_id="group_a")
        assert written == 0
        assert adapter.edit_sequence == []


# ---------------------------------------------------------------------------
# reset_group — calls adapter.clear_value on every attr
# ---------------------------------------------------------------------------


class TestResetGroup:

    def test_reset_calls_clear_value_on_each_attr(self) -> None:
        metas = {name: _meta(name) for name in ("a", "b", "c")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = _build_group({name: 0.0 for name in metas}, metas=metas)
        reset = reset_group(adapter, group)
        assert reset == 3
        assert sorted(adapter.cleared) == ["a", "b", "c"]

    def test_reset_walks_nested_sub_groups(self) -> None:
        """Reset on Transform clears every nested leaf's opinion."""
        metas = {
            "translate_x": _meta("translate_x"),
            "rotate_z": _meta("rotate_z"),
            "flag": _meta("flag"),
        }
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = UiDisplayGroup(name="Transform")
        t = UiDisplayGroup(name="Translate")
        t.props.append(metas["translate_x"])
        r = UiDisplayGroup(name="Rotate")
        r.props.append(metas["rotate_z"])
        group.sub_groups["Translate"] = t
        group.sub_groups["Rotate"] = r
        group.props.append(metas["flag"])
        reset = reset_group(adapter, group)
        assert reset == 3
        assert set(adapter.cleared) == {"translate_x", "rotate_z", "flag"}

    def test_reset_skips_locked_attrs(self) -> None:
        metas = {
            "x": _meta("x", is_locked=False),
            "y": _meta("y", is_locked=True),
        }
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = _build_group({name: 0.0 for name in metas}, metas=metas)
        reset = reset_group(adapter, group)
        assert reset == 1
        assert adapter.cleared == ["x"]

    def test_reset_disabled_when_capability_unsupported(self) -> None:
        metas = {"x": _meta("x", is_authored=True)}
        adapter = _RecordingAdapter(
            paths=["/World/X"],
            attributes=metas,
            clear_values_supported=False,
        )
        group = _build_group({"x": 1.0}, metas=metas)
        reset = reset_group(adapter, group)
        assert reset == 0
        assert adapter.cleared == []

    def test_reset_swallows_not_implemented_per_attr(self) -> None:
        """A per-attr ``NotImplementedError`` doesn't abort the reset.

        Mirrors the ``ControlStateIndicator`` click handler's swallow:
        a subclass-of-``MockPropertyAdapter`` may fail on one attr
        without blocking the rest of the reset. Ensures a transient
        fault on (e.g.) a relationship type doesn't leave a half-
        reset group.
        """

        class _PartiallyBrokenAdapter(_RecordingAdapter):
            def clear_value(self, attr_name: str) -> None:
                if attr_name == "b":
                    raise NotImplementedError
                super().clear_value(attr_name)

        metas = {name: _meta(name) for name in ("a", "b", "c")}
        adapter = _PartiallyBrokenAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = _build_group({name: 0.0 for name in metas}, metas=metas)
        reset = reset_group(adapter, group)
        assert reset == 2
        assert sorted(adapter.cleared) == ["a", "c"]

    def test_reset_on_empty_group_is_noop(self) -> None:
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes={}, clear_values_supported=True,
        )
        group = UiDisplayGroup(name="Empty")
        reset = reset_group(adapter, group)
        assert reset == 0
        assert adapter.cleared == []


# ---------------------------------------------------------------------------
# can_paste / can_reset — menu-item enabled state
# ---------------------------------------------------------------------------


class TestCanPaste:

    def test_empty_clipboard_disables_paste(self) -> None:
        metas = {"x": _meta("x")}
        adapter = _adapter_with({"x": 1.0}, metas=metas)
        group = _build_group({"x": 1.0}, metas=metas)
        assert can_paste(adapter, group) is False

    def test_matching_attrs_in_clipboard_enables_paste(self) -> None:
        metas = {"x": _meta("x")}
        adapter = _adapter_with({"x": 1.0}, metas=metas)
        group = _build_group({"x": 1.0}, metas=metas)
        copy_group(adapter, group)
        assert can_paste(adapter, group) is True

    def test_no_overlap_disables_paste(self) -> None:
        """Copy from group A, paste target is group B with no shared attr."""
        metas_a = {"foo": _meta("foo")}
        adapter_a = _adapter_with({"foo": 1.0}, metas=metas_a)
        group_a = _build_group({"foo": 1.0}, metas=metas_a)
        copy_group(adapter_a, group_a)

        metas_b = {"bar": _meta("bar")}
        adapter_b = _adapter_with({"bar": 2.0}, metas=metas_b)
        group_b = _build_group({"bar": 2.0}, metas=metas_b)
        assert can_paste(adapter_b, group_b) is False

    def test_all_locked_disables_paste(self) -> None:
        metas = {"x": _meta("x", is_locked=True)}
        adapter = _adapter_with({"x": 1.0}, metas=metas)
        group = _build_group({"x": 1.0}, metas=metas)
        copy_group(adapter, group)
        assert can_paste(adapter, group) is False

    def test_all_none_disables_paste(self) -> None:
        """Clipboard full of ambiguous ``None`` values → disabled."""
        metas = {"x": _meta("x")}
        adapter_src = MockPropertyAdapter(
            paths=["/World/A", "/World/B"],
            attributes=metas,
        )
        adapter_src.set_path_value("/World/A", "x", 1.0)
        adapter_src.set_path_value("/World/B", "x", 2.0)
        group = _build_group({"x": 0.0}, metas=metas)
        copy_group(adapter_src, group)
        adapter_dst = _adapter_with({"x": 0.0}, metas=metas)
        assert can_paste(adapter_dst, group) is False


class TestCanReset:

    def test_default_capability_disables_reset(self) -> None:
        """MockPropertyAdapter inherits the unsupported default capability."""
        metas = {"x": _meta("x", is_authored=True)}
        adapter = MockPropertyAdapter(
            paths=["/World/X"], attributes=metas,
        )
        group = _build_group({"x": 1.0}, metas=metas)
        assert can_reset(adapter, group) is False

    def test_supported_capability_and_authored_prop_enables_reset(self) -> None:
        metas = {"x": _meta("x", is_authored=True)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = _build_group({"x": 1.0}, metas=metas)
        assert can_reset(adapter, group) is True

    def test_unsupported_capability_disables_same_adapter_class(self) -> None:
        metas = {"x": _meta("x", is_authored=True)}
        supported = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
            clear_values_supported=True,
        )
        unsupported = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
            clear_values_supported=False,
        )
        group = _build_group({"x": 1.0}, metas=metas)
        assert type(supported) is type(unsupported)
        assert can_reset(supported, group) is True
        assert can_reset(unsupported, group) is False

    def test_all_unauthored_disables_reset(self) -> None:
        metas = {"x": _meta("x", is_authored=False)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = _build_group({"x": 1.0}, metas=metas)
        assert can_reset(adapter, group) is False

    def test_all_locked_disables_reset(self) -> None:
        metas = {"x": _meta("x", is_locked=True, is_authored=True)}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = _build_group({"x": 1.0}, metas=metas)
        assert can_reset(adapter, group) is False

    def test_mixed_locked_and_authored_enables_reset(self) -> None:
        """One locked + one authored-unlocked → still enabled (we reset the unlocked)."""
        metas = {
            "locked": _meta("locked", is_locked=True, is_authored=True),
            "free": _meta("free", is_locked=False, is_authored=True),
        }
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        group = _build_group({"locked": 1.0, "free": 2.0}, metas=metas)
        assert can_reset(adapter, group) is True


# ---------------------------------------------------------------------------
# clear_clipboard / get_clipboard
# ---------------------------------------------------------------------------


class TestClipboardUtilities:

    def test_get_clipboard_returns_defensive_copy(self) -> None:
        """Mutating the returned dict doesn't corrupt module state."""
        metas = {"x": _meta("x")}
        adapter = _adapter_with({"x": 1.0}, metas=metas)
        group = _build_group({"x": 1.0}, metas=metas)
        copy_group(adapter, group)
        cb = get_clipboard()
        cb["evil"] = 666
        assert "evil" not in get_clipboard()

    def test_clear_clipboard_by_id(self) -> None:
        metas = {"x": _meta("x")}
        adapter = _adapter_with({"x": 1.0}, metas=metas)
        group = _build_group({"x": 1.0}, metas=metas)
        copy_group(adapter, group, clipboard_id="a")
        copy_group(adapter, group, clipboard_id="b")
        clear_clipboard("a")
        assert get_clipboard("a") == {}
        assert get_clipboard("b") == {"x": 1.0}

    def test_clear_clipboard_all(self) -> None:
        metas = {"x": _meta("x")}
        adapter = _adapter_with({"x": 1.0}, metas=metas)
        group = _build_group({"x": 1.0}, metas=metas)
        copy_group(adapter, group, clipboard_id="a")
        copy_group(adapter, group, clipboard_id="b")
        clear_clipboard()  # all
        assert get_clipboard("a") == {}
        assert get_clipboard("b") == {}

    def test_get_clipboard_unknown_id_returns_empty(self) -> None:
        assert get_clipboard("never_populated") == {}


# ---------------------------------------------------------------------------
# AttributeGroupWidget — right-click wiring (headless)
# ---------------------------------------------------------------------------


class _FakeFrameWithMouseRelease:
    """Stand-in for ``ui.CollapsableFrame`` that captures mouse-release wiring."""

    def __init__(self, collapsed: bool = False) -> None:
        self._collapsed = collapsed
        self._collapse_fn = None
        self.mouse_released_fn = None

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, value: bool) -> None:
        if self._collapsed == value:
            return
        self._collapsed = value
        if self._collapse_fn is not None:
            self._collapse_fn(value)

    def set_collapsed_changed_fn(self, fn: Any) -> None:
        self._collapse_fn = fn

    def set_mouse_released_fn(self, fn: Any) -> None:
        self.mouse_released_fn = fn


def _make_headless_group(
    name: str = "Transform",
    on_context_menu: Optional[Any] = None,
    initially_collapsed: bool = False,
):
    """Build an ``AttributeGroupWidget`` with no omni.ui runtime.

    Like ``_make_headless`` in :mod:`test_group_widget`, but also
    exercises the Step-5.3 ``on_context_menu`` wiring path.
    """
    from ovui_widgets.property.group_widget import AttributeGroupWidget

    g = AttributeGroupWidget.__new__(AttributeGroupWidget)
    g._name = name
    g._on_collapse_change = None
    g._on_context_menu = on_context_menu
    g._frame = _FakeFrameWithMouseRelease(initially_collapsed)
    g._content = None
    g._frame.set_collapsed_changed_fn(g._on_frame_collapsed_changed)
    if on_context_menu is not None:
        g._frame.set_mouse_released_fn(g._on_mouse_released)
    return g


class TestGroupWidgetContextMenuWiring:

    def test_right_click_fires_context_menu_callback(self) -> None:
        calls: List[Any] = []
        g = _make_headless_group(
            on_context_menu=lambda x, y: calls.append((x, y)),
        )
        # button=1 is right-click in omni.ui's encoding.
        g._on_mouse_released(10.0, 20.0, 1, 0)
        assert calls == [(10.0, 20.0)]

    def test_left_click_ignored(self) -> None:
        """Left-click (button == 0) must not open the menu."""
        calls: List[Any] = []
        g = _make_headless_group(
            on_context_menu=lambda x, y: calls.append((x, y)),
        )
        g._on_mouse_released(10.0, 20.0, 0, 0)
        assert calls == []

    def test_middle_click_ignored(self) -> None:
        """Middle-click (button == 2) also has no effect."""
        calls: List[Any] = []
        g = _make_headless_group(
            on_context_menu=lambda x, y: calls.append((x, y)),
        )
        g._on_mouse_released(10.0, 20.0, 2, 0)
        assert calls == []

    def test_no_callback_right_click_is_noop(self) -> None:
        """Right-click without a registered callback does nothing / no crash."""
        g = _make_headless_group(on_context_menu=None)
        # Must not raise.
        g._on_mouse_released(10.0, 20.0, 1, 0)

    def test_set_mouse_released_fn_wired_only_when_callback_present(self) -> None:
        """No callback → widget doesn't set a mouse-released handler.

        Rationale: absent handler = omni.ui forwards the event to the
        default hit path (hover, etc.), keeping unrelated behaviour
        intact.
        """
        g_with = _make_headless_group(on_context_menu=lambda x, y: None)
        g_without = _make_headless_group(on_context_menu=None)
        assert g_with._frame.mouse_released_fn is not None
        assert g_without._frame.mouse_released_fn is None


# ---------------------------------------------------------------------------
# PropertyWindow wiring — on_context_menu propagation
# ---------------------------------------------------------------------------


class _FakeGroupWidget:
    """Recording double for :class:`AttributeGroupWidget`.

    Captures all construction kwargs, including the Step-5.3
    ``on_context_menu`` callback, so tests can assert it was passed
    and fires the expected pop.
    """

    calls: List["_FakeGroupWidget"] = []

    def __init__(
        self,
        name: str,
        initially_collapsed: bool = False,
        on_collapse_change: Any = None,
        on_context_menu: Any = None,
        level: int = 0,
    ) -> None:
        self.name = name
        self.initially_collapsed = initially_collapsed
        self.on_collapse_change = on_collapse_change
        self.on_context_menu = on_context_menu
        self.level = level
        self.content = self
        _FakeGroupWidget.calls.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture()
def fake_group_widget(monkeypatch):
    import ovui_widgets.property.group_widget as gw_mod
    import ovui_widgets.property.window as pw_mod
    _FakeGroupWidget.calls = []
    monkeypatch.setattr(gw_mod, "AttributeGroupWidget", _FakeGroupWidget)
    monkeypatch.setattr(pw_mod, "AttributeGroupWidget", _FakeGroupWidget, raising=False)
    return _FakeGroupWidget


def _make_headless_property_widget():
    from ovui_widgets.property.widget.attributes_widget import AttributesWidget
    from ovui_widgets.property.window import PropertyWindow
    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._content = None
    w._group_collapse_state = {}
    w._active_context_menu = None
    w._widgets = []
    w._default_attributes = AttributesWidget(w)
    return w


def _nested_adapter_and_groups():
    """Build a nested-group adapter matching the Step-5.2 fixture."""
    attrs = {
        "t_x": AttributeMetadata(
            name="t_x", display_name="X", type_name="float",
            value_type=None, group="Transform.Translate",
        ),
        "t_y": AttributeMetadata(
            name="t_y", display_name="Y", type_name="float",
            value_type=None, group="Transform.Translate",
        ),
        "r_z": AttributeMetadata(
            name="r_z", display_name="Z", type_name="float",
            value_type=None, group="Transform.Rotate",
        ),
    }
    adapter = MockPropertyAdapter(paths=["/World/X"], attributes=attrs)
    for name, value in (("t_x", 1.0), ("t_y", 2.0), ("r_z", 3.0)):
        adapter.set_value(name, value)
    return adapter


class TestPropertyWindowContextMenuWiring:

    def test_build_group_children_passes_on_context_menu(self, fake_group_widget):
        """Every group widget receives an ``on_context_menu`` callable."""
        w = _make_headless_property_widget()
        w._adapter = _nested_adapter_and_groups()
        w._selection = ["/World/X"]
        w._build_attribute_row = lambda prop: None  # type: ignore[method-assign]

        w._build_groups()

        assert len(fake_group_widget.calls) > 0
        for g in fake_group_widget.calls:
            assert callable(g.on_context_menu), (
                f"group {g.name!r} built without an on_context_menu callback"
            )

    def test_on_context_menu_captures_correct_group_per_frame(
        self, fake_group_widget, monkeypatch
    ):
        """Closure default-arg must bind each frame's own group.

        Without the ``g=child`` default binding, every callback would
        close over the last loop iteration's reference and firing any
        frame's callback would act on the wrong group.
        """
        w = _make_headless_property_widget()
        w._adapter = _nested_adapter_and_groups()
        w._selection = ["/World/X"]
        w._build_attribute_row = lambda prop: None  # type: ignore[method-assign]

        seen_groups: List[Any] = []

        def _spy_show(adapter, group, x, y, clipboard_id="ovgear_group"):
            seen_groups.append(group.name)
            return object()

        monkeypatch.setattr(
            "ovui_widgets.property.parts.group_context_menu.show_group_context_menu",
            _spy_show,
        )

        w._build_groups()
        # Fire the callback of the ``Translate`` frame and the ``Rotate`` frame.
        by_name = {g.name: g for g in fake_group_widget.calls}
        by_name["Translate"].on_context_menu(0.0, 0.0)
        by_name["Rotate"].on_context_menu(0.0, 0.0)
        by_name["Transform"].on_context_menu(0.0, 0.0)
        assert seen_groups == ["Translate", "Rotate", "Transform"]

    def test_show_group_context_menu_is_noop_when_adapter_none(
        self, fake_group_widget, monkeypatch
    ):
        """Defensive: no adapter → ``_show_group_context_menu`` short-circuits.

        Happens during the brief window between ``set_selection``
        clearing the adapter and the rebuild wiring a new one; should
        not reach into :func:`show_group_context_menu` with ``None``.
        """
        calls: List[Any] = []

        def _spy_show(*args, **kwargs):
            calls.append(args)
            return object()

        monkeypatch.setattr(
            "ovui_widgets.property.parts.group_context_menu.show_group_context_menu",
            _spy_show,
        )
        w = _make_headless_property_widget()
        group = UiDisplayGroup(name="Transform")
        w._show_group_context_menu(group, 10.0, 20.0)
        assert calls == []
        assert w._active_context_menu is None

    def test_show_group_context_menu_stores_menu_reference(
        self, fake_group_widget, monkeypatch
    ):
        """Returned ``ui.Menu`` is pinned on the widget so it doesn't GC."""
        sentinel = object()

        def _spy_show(*args, **kwargs):
            return sentinel

        monkeypatch.setattr(
            "ovui_widgets.property.parts.group_context_menu.show_group_context_menu",
            _spy_show,
        )
        w = _make_headless_property_widget()
        w._adapter = _nested_adapter_and_groups()
        group = UiDisplayGroup(name="Transform")
        w._show_group_context_menu(group, 0.0, 0.0)
        assert w._active_context_menu is sentinel


# ---------------------------------------------------------------------------
# End-to-end: copy → paste across re-selection
# ---------------------------------------------------------------------------


class TestEndToEndGroupClipboard:
    """Compose the helpers into the realistic user flow.

    These tests don't touch the UI — they drive the helpers directly
    in the order the menu callbacks would, then assert the adapter
    state. Catches any wiring regression in the helper triplet.
    """

    def test_copy_paste_roundtrip_on_nested_tree(self) -> None:
        metas = {
            "translate_x": _meta("translate_x"),
            "rotate_z": _meta("rotate_z"),
        }
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas,
        )
        adapter.set_value("translate_x", 1.0)
        adapter.set_value("rotate_z", 2.0)
        group = UiDisplayGroup(name="Transform")
        t = UiDisplayGroup(name="Translate")
        t.props.append(metas["translate_x"])
        r = UiDisplayGroup(name="Rotate")
        r.props.append(metas["rotate_z"])
        group.sub_groups["Translate"] = t
        group.sub_groups["Rotate"] = r

        # User right-clicks Transform and picks Copy All.
        copy_group(adapter, group)
        # User drifts the values editing inline.
        adapter.set_value("translate_x", 99.0)
        adapter.set_value("rotate_z", 99.0)
        # User right-clicks Transform and picks Paste All.
        written = paste_group(adapter, group)
        assert written == 2
        assert adapter.get_value("translate_x") == 1.0
        assert adapter.get_value("rotate_z") == 2.0

    def test_reset_after_copy_does_not_affect_clipboard(self) -> None:
        """Reset shouldn't touch the clipboard (confirms namespacing)."""
        metas = {"x": _meta("x")}
        adapter = _RecordingAdapter(
            paths=["/World/X"], attributes=metas, clear_values_supported=True,
        )
        adapter.set_value("x", 5.0)
        group = _build_group({"x": 5.0}, metas=metas)
        copy_group(adapter, group)
        assert get_clipboard() == {"x": 5.0}

        reset_group(adapter, group)
        # Clipboard survives the reset; paste would still restore the value.
        assert get_clipboard() == {"x": 5.0}

    def test_switch_selection_preserves_clipboard(self) -> None:
        """Copy on Selection A, paste on Selection B's same-named attr."""
        metas = {"radius": _meta("radius")}
        adapter_a = _adapter_with({"radius": 7.0}, metas=metas)
        group_a = _build_group({"radius": 7.0}, metas=metas)
        copy_group(adapter_a, group_a)

        adapter_b = _RecordingAdapter(
            paths=["/World/Y"], attributes=metas,
        )
        adapter_b.set_value("radius", 0.0)
        group_b = _build_group({"radius": 0.0}, metas=metas)
        written = paste_group(adapter_b, group_b)
        assert written == 1
        assert adapter_b.get_value("radius") == 7.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
