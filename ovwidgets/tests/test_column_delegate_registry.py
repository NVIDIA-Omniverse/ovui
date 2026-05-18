# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 30 — :class:`AbstractColumnDelegate` +
:class:`ColumnDelegateRegistry`.

Covers the the content browser implementation step 30 done-signal checklist:

* :class:`AbstractColumnDelegate` + :class:`ColumnDelegateRegistry`
  import from the widget subpackage.
* ABC contract: :meth:`AbstractColumnDelegate.name` +
  :meth:`AbstractColumnDelegate.build_widget` are abstract;
  :attr:`initial_width` defaults to ``ui.Fraction(1)``;
  :meth:`build_header` is an optional no-op.
* Singleton: :meth:`ColumnDelegateRegistry.instance` returns the same
  object on every call; :meth:`_reset_for_tests` rebuilds on next
  call.
* :meth:`register` stores the class under its name, appends to
  registration order, returns a subscription whose :meth:`cancel`
  drops the entry.
* :meth:`register` rejects duplicates with :class:`ValueError`.
* :meth:`register` rejects non-:class:`AbstractColumnDelegate`
  classes with :class:`ValueError`.
* :meth:`get_registered_names` returns a fresh list in
  registration order.
* :meth:`get_delegate_class` returns ``None`` for unregistered names.
* :meth:`subscribe_changed` fires on register and unregister.
* :meth:`FileBrowserDelegate.build_widget` dispatches
  ``column_id >= BUILTIN_COLUMN_COUNT`` to the registered delegate.

Every test that touches the singleton resets it at setup / teardown so
one test's registrations never leak into another's assertions.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List

import omni.ui as ui
import pytest

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.content.widget import (
    AbstractColumnDelegate,
    ColumnDelegateRegistry,
    FileBrowserDelegate,
    FileBrowserModel,
)
from ovwidgets.content.widget.column_delegate import (
    _ChangedSubscription,
    _ColumnDelegateSubscription,
)
from ovwidgets.content.widget.file_item import FileItem

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_registry():
    """Drop the singleton before and after every test in this module.

    Every Step 30 test either registers something or asserts "no
    columns"; leaking state across tests would force callers to guess
    the right order. Autouse so individual tests never forget.
    """
    ColumnDelegateRegistry._reset_for_tests()
    yield
    ColumnDelegateRegistry._reset_for_tests()


@pytest.fixture
def dummy_class():
    """Minimal :class:`AbstractColumnDelegate` subclass for registry tests."""

    class DummyColumn(AbstractColumnDelegate):
        @property
        def name(self) -> str:
            return "Dummy"

        def build_widget(self, item: FileItem) -> None:
            ui.Label("dummy")

    return DummyColumn


@pytest.fixture
def second_dummy_class():
    """A second, distinct subclass so ordering assertions can tell them apart."""

    class SecondColumn(AbstractColumnDelegate):
        @property
        def name(self) -> str:
            return "Second"

        def build_widget(self, item: FileItem) -> None:
            ui.Label("second")

    return SecondColumn


@pytest.fixture
def model() -> FileBrowserModel:
    return FileBrowserModel(MockBackend(), "mock://Home")


@pytest.fixture
def leaf_item(model) -> FileItem:
    doc = next(
        c for c in model.get_item_children(None)
        if c.is_folder and c.name == "Documents"
    )
    proj = next(
        c for c in model.get_item_children(doc)
        if c.is_folder and c.name == "Projects"
    )
    return next(
        c for c in model.get_item_children(proj)
        if not c.is_folder and c.name == "demo.usda"
    )


@pytest.fixture(scope="module")
def ephemeral_window():
    win = ui.Window(
        "_test_column_delegate_registry", width=400, height=200,
    )
    yield win
    win.destroy()


@contextmanager
def in_window_frame(window):
    try:
        with window.frame:
            yield
    finally:
        window.frame.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Surface
# ──────────────────────────────────────────────────────────────────────────────


class TestSurface:
    def test_abstract_column_delegate_reexported(self):
        from ovwidgets.content.widget import AbstractColumnDelegate as E
        assert E is AbstractColumnDelegate

    def test_registry_reexported(self):
        from ovwidgets.content.widget import ColumnDelegateRegistry as E
        assert E is ColumnDelegateRegistry

    def test_abstract_column_delegate_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            AbstractColumnDelegate()  # type: ignore[abstract]

    def test_subclass_missing_name_is_abstract(self):
        class NoName(AbstractColumnDelegate):
            def build_widget(self, item):
                pass

        with pytest.raises(TypeError):
            NoName()  # type: ignore[abstract]

    def test_subclass_missing_build_widget_is_abstract(self):
        class NoBuild(AbstractColumnDelegate):
            @property
            def name(self) -> str:
                return "X"

        with pytest.raises(TypeError):
            NoBuild()  # type: ignore[abstract]


# ──────────────────────────────────────────────────────────────────────────────
# AbstractColumnDelegate defaults
# ──────────────────────────────────────────────────────────────────────────────


class TestAbstractColumnDelegateDefaults:
    def test_initial_width_default_is_fraction_one(self, dummy_class):
        d = dummy_class()
        width = d.initial_width
        assert isinstance(width, ui.Fraction)
        # ovui :class:`ui.Fraction` stringifies / compares through its
        # :attr:`Length.value`; direct float compare is the reliable path.
        assert float(width.value) == pytest.approx(1.0)

    def test_build_header_default_is_noop(self, dummy_class, ephemeral_window):
        d = dummy_class()
        # Should not raise inside a live build context.
        with in_window_frame(ephemeral_window):
            assert d.build_header() is None

    def test_subclass_can_override_initial_width(self):
        class Wide(AbstractColumnDelegate):
            @property
            def name(self) -> str:
                return "Wide"

            @property
            def initial_width(self):
                return ui.Pixel(40)

            def build_widget(self, item):
                pass

        w = Wide().initial_width
        assert isinstance(w, ui.Pixel)
        assert float(w.value) == pytest.approx(40.0)


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_instance_returns_same_object(self):
        a = ColumnDelegateRegistry.instance()
        b = ColumnDelegateRegistry.instance()
        assert a is b

    def test_reset_for_tests_rebuilds(self):
        a = ColumnDelegateRegistry.instance()
        ColumnDelegateRegistry._reset_for_tests()
        b = ColumnDelegateRegistry.instance()
        assert a is not b

    def test_fresh_registry_has_no_delegates(self):
        assert ColumnDelegateRegistry.instance().get_registered_names() == []


# ──────────────────────────────────────────────────────────────────────────────
# Register / get_delegate_class / get_registered_names
# ──────────────────────────────────────────────────────────────────────────────


class TestRegister:
    def test_register_stores_class(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Dummy", dummy_class)
        try:
            assert reg.get_delegate_class("Dummy") is dummy_class
        finally:
            sub.cancel()

    def test_register_appends_to_registered_names(
        self, dummy_class, second_dummy_class,
    ):
        reg = ColumnDelegateRegistry.instance()
        s1 = reg.register("Dummy", dummy_class)
        s2 = reg.register("Second", second_dummy_class)
        try:
            assert reg.get_registered_names() == ["Dummy", "Second"]
        finally:
            s2.cancel()
            s1.cancel()

    def test_registered_names_is_a_fresh_list(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Dummy", dummy_class)
        try:
            a = reg.get_registered_names()
            b = reg.get_registered_names()
            assert a == b
            assert a is not b
            # Caller mutating the returned list must not affect the
            # registry's internal order bookkeeping.
            a.append("Ghost")
            assert reg.get_registered_names() == ["Dummy"]
        finally:
            sub.cancel()

    def test_register_returns_column_delegate_subscription(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Dummy", dummy_class)
        try:
            assert isinstance(sub, _ColumnDelegateSubscription)
        finally:
            sub.cancel()

    def test_register_duplicate_name_raises(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Dummy", dummy_class)
        try:
            with pytest.raises(ValueError):
                reg.register("Dummy", dummy_class)
        finally:
            sub.cancel()

    def test_register_non_subclass_raises(self):
        reg = ColumnDelegateRegistry.instance()

        class NotADelegate:
            pass

        with pytest.raises(ValueError):
            reg.register("Bogus", NotADelegate)  # type: ignore[arg-type]

    def test_register_non_class_raises(self):
        reg = ColumnDelegateRegistry.instance()
        with pytest.raises(ValueError):
            reg.register("Bogus", "not a class")  # type: ignore[arg-type]

    def test_get_delegate_class_unknown_name_is_none(self):
        reg = ColumnDelegateRegistry.instance()
        assert reg.get_delegate_class("NoSuch") is None


# ──────────────────────────────────────────────────────────────────────────────
# Cancel / unregister
# ──────────────────────────────────────────────────────────────────────────────


class TestCancel:
    def test_cancel_removes_from_registry(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Dummy", dummy_class)
        assert reg.get_delegate_class("Dummy") is dummy_class
        sub.cancel()
        assert reg.get_delegate_class("Dummy") is None
        assert reg.get_registered_names() == []

    def test_cancel_is_idempotent(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Dummy", dummy_class)
        sub.cancel()
        # Second cancel must not raise and must not touch a stranger's
        # registration under the same name.
        sub.cancel()
        sub2 = reg.register("Dummy", dummy_class)
        try:
            assert reg.get_delegate_class("Dummy") is dummy_class
            # First handle's third cancel still no-ops after the
            # replacement landed — the handle self-nulled on its first
            # call, so a stale handle can never drop a stranger's entry.
            sub.cancel()
            assert reg.get_delegate_class("Dummy") is dummy_class
        finally:
            sub2.cancel()

    def test_cancel_preserves_order_of_other_entries(
        self, dummy_class, second_dummy_class,
    ):
        reg = ColumnDelegateRegistry.instance()
        s1 = reg.register("A", dummy_class)
        s2 = reg.register("B", second_dummy_class)
        s3 = reg.register("C", dummy_class)
        try:
            s2.cancel()
            assert reg.get_registered_names() == ["A", "C"]
        finally:
            s3.cancel()
            s1.cancel()

    def test_register_after_cancel_allows_reuse(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Dummy", dummy_class)
        sub.cancel()
        # Name is free — must register without raising.
        sub2 = reg.register("Dummy", dummy_class)
        try:
            assert reg.get_delegate_class("Dummy") is dummy_class
        finally:
            sub2.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# subscribe_changed
# ──────────────────────────────────────────────────────────────────────────────


class TestSubscribeChanged:
    def test_fires_on_register(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        calls: List[int] = []
        sub_cb = reg.subscribe_changed(lambda: calls.append(1))
        try:
            reg_sub = reg.register("Dummy", dummy_class)
            try:
                assert calls == [1]
            finally:
                reg_sub.cancel()
        finally:
            sub_cb.cancel()

    def test_fires_on_unregister(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        reg_sub = reg.register("Dummy", dummy_class)
        calls: List[int] = []
        sub_cb = reg.subscribe_changed(lambda: calls.append(1))
        try:
            reg_sub.cancel()
            assert calls == [1]
        finally:
            sub_cb.cancel()

    def test_returns_changed_subscription(self):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.subscribe_changed(lambda: None)
        try:
            assert isinstance(sub, _ChangedSubscription)
        finally:
            sub.cancel()

    def test_multiple_subscribers_each_get_called(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        a_calls: List[int] = []
        b_calls: List[int] = []
        sa = reg.subscribe_changed(lambda: a_calls.append(1))
        sb = reg.subscribe_changed(lambda: b_calls.append(1))
        try:
            reg_sub = reg.register("Dummy", dummy_class)
            try:
                assert a_calls == [1]
                assert b_calls == [1]
            finally:
                reg_sub.cancel()
        finally:
            sb.cancel()
            sa.cancel()

    def test_cancel_stops_firing(self, dummy_class):
        reg = ColumnDelegateRegistry.instance()
        calls: List[int] = []
        sub_cb = reg.subscribe_changed(lambda: calls.append(1))
        sub_cb.cancel()
        reg_sub = reg.register("Dummy", dummy_class)
        try:
            assert calls == []
        finally:
            reg_sub.cancel()

    def test_cancel_is_idempotent(self):
        reg = ColumnDelegateRegistry.instance()
        sub_cb = reg.subscribe_changed(lambda: None)
        sub_cb.cancel()
        sub_cb.cancel()  # Must not raise.

    def test_callback_may_cancel_another_subscription_safely(
        self, dummy_class,
    ):
        # A callback that cancels another subscription mid-notify must
        # not crash the iteration over ``_changed_cbs``. The original
        # failure mode: if ``_notify_changed`` walks the live list, the
        # mutation shifts remaining indices and a later callback is
        # skipped (or ``IndexError`` is raised). The snapshot-on-iterate
        # pattern in :meth:`ColumnDelegateRegistry._notify_changed`
        # closes that gap.
        reg = ColumnDelegateRegistry.instance()
        a_calls: List[int] = []
        b_calls: List[int] = []

        sub_b_holder: List[_ChangedSubscription] = []

        def cb_a() -> None:
            a_calls.append(1)
            # Mid-notify, cancel B — the subsequent iteration step
            # inside :meth:`_notify_changed` must still invoke B's
            # snapshot entry (or skip it cleanly) without raising.
            if sub_b_holder:
                sub_b_holder[0].cancel()
                sub_b_holder.clear()

        def cb_b() -> None:
            b_calls.append(1)

        sub_a = reg.subscribe_changed(cb_a)
        sub_b = reg.subscribe_changed(cb_b)
        sub_b_holder.append(sub_b)
        try:
            reg_sub = reg.register("Dummy", dummy_class)
            try:
                # A always fires; B may or may not on the same tick
                # (depends on iteration direction). What matters: no
                # exception was raised and the registration succeeded.
                assert a_calls == [1]
                assert reg.get_delegate_class("Dummy") is dummy_class
            finally:
                reg_sub.cancel()
        finally:
            sub_a.cancel()
            # B is already cancelled by cb_a; double-cancel is safe.
            sub_b.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# Delegate dispatch in :class:`FileBrowserDelegate`
# ──────────────────────────────────────────────────────────────────────────────


class _RecordingDelegate(AbstractColumnDelegate):
    """Records every :meth:`build_widget` invocation + renders a label.

    Class-level list so a delegate instance constructed per-cell by
    :class:`FileBrowserDelegate` still reports its calls back to the
    test. Cleared in ``setup_method`` on :class:`TestDelegateDispatch`
    so each test starts fresh.
    """

    calls: List[str] = []

    @property
    def name(self) -> str:
        return "Recorder"

    def build_widget(self, item: FileItem) -> None:
        _RecordingDelegate.calls.append(item.name)
        ui.Label("rec")


class TestDelegateDispatch:
    def setup_method(self) -> None:
        _RecordingDelegate.calls = []

    def test_plugin_column_dispatches_to_registered_delegate(
        self, ephemeral_window, model, leaf_item,
    ):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Recorder", _RecordingDelegate)
        try:
            d = FileBrowserDelegate()
            plugin_column = FileBrowserModel.BUILTIN_COLUMN_COUNT
            with in_window_frame(ephemeral_window):
                d.build_widget(model, leaf_item, plugin_column, 0, False)
            assert _RecordingDelegate.calls == [leaf_item.name]
        finally:
            sub.cancel()

    def test_plugin_column_with_no_registration_is_noop(
        self, ephemeral_window, model, leaf_item,
    ):
        d = FileBrowserDelegate()
        plugin_column = FileBrowserModel.BUILTIN_COLUMN_COUNT
        # Registry is empty; dispatch must render nothing and not raise.
        with in_window_frame(ephemeral_window):
            d.build_widget(model, leaf_item, plugin_column, 0, False)
        assert _RecordingDelegate.calls == []

    def test_builtin_columns_do_not_dispatch_to_registry(
        self, ephemeral_window, model, leaf_item,
    ):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Recorder", _RecordingDelegate)
        try:
            d = FileBrowserDelegate()
            with in_window_frame(ephemeral_window):
                for col in range(FileBrowserModel.BUILTIN_COLUMN_COUNT):
                    d.build_widget(model, leaf_item, col, 0, False)
            assert _RecordingDelegate.calls == []
        finally:
            sub.cancel()

    def test_dispatch_uses_registration_order(
        self, ephemeral_window, model, leaf_item, second_dummy_class,
    ):
        reg = ColumnDelegateRegistry.instance()
        s1 = reg.register("Second", second_dummy_class)  # at plugin index 0
        s2 = reg.register("Recorder", _RecordingDelegate)  # at plugin index 1
        try:
            d = FileBrowserDelegate()
            builtin = FileBrowserModel.BUILTIN_COLUMN_COUNT
            with in_window_frame(ephemeral_window):
                # Index 0 → "Second" (no recording); Index 1 → Recorder.
                d.build_widget(model, leaf_item, builtin + 0, 0, False)
                d.build_widget(model, leaf_item, builtin + 1, 0, False)
            assert _RecordingDelegate.calls == [leaf_item.name]
        finally:
            s2.cancel()
            s1.cancel()

    def test_dispatch_out_of_range_is_noop(
        self, ephemeral_window, model, leaf_item,
    ):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Recorder", _RecordingDelegate)
        try:
            d = FileBrowserDelegate()
            # One column registered → plugin index 0 is valid, index 1
            # is past the end and must render nothing without raising.
            builtin = FileBrowserModel.BUILTIN_COLUMN_COUNT
            with in_window_frame(ephemeral_window):
                d.build_widget(model, leaf_item, builtin + 5, 0, False)
            assert _RecordingDelegate.calls == []
        finally:
            sub.cancel()

    def test_dispatch_non_int_column_id_is_noop(
        self, ephemeral_window, model, leaf_item,
    ):
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Recorder", _RecordingDelegate)
        try:
            d = FileBrowserDelegate()
            with in_window_frame(ephemeral_window):
                # ovui delegates accept ``Any`` for column_id — guard.
                d.build_widget(model, leaf_item, "bogus", 0, False)
            assert _RecordingDelegate.calls == []
        finally:
            sub.cancel()

    def test_dispatch_builds_fresh_instance_per_call(
        self, ephemeral_window, model, leaf_item,
    ):
        # Two calls → two instances (sync build_widget, no caching).
        class Counting(AbstractColumnDelegate):
            instances: List[object] = []

            def __init__(self) -> None:
                super().__init__()
                Counting.instances.append(self)

            @property
            def name(self) -> str:
                return "Count"

            def build_widget(self, item: FileItem) -> None:
                ui.Label("c")

        Counting.instances = []
        reg = ColumnDelegateRegistry.instance()
        sub = reg.register("Count", Counting)
        try:
            d = FileBrowserDelegate()
            builtin = FileBrowserModel.BUILTIN_COLUMN_COUNT
            with in_window_frame(ephemeral_window):
                d.build_widget(model, leaf_item, builtin, 0, False)
                d.build_widget(model, leaf_item, builtin, 0, False)
            assert len(Counting.instances) == 2
            assert Counting.instances[0] is not Counting.instances[1]
        finally:
            sub.cancel()
