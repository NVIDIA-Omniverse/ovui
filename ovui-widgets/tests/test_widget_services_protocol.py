# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unit tests for the :class:`WidgetServices` protocol and the
explicit :class:`FakeWidgetServices` test fixture (Step 11.1/13).

Coverage:

* The protocol has exactly three members
  (``selection_bus``, ``undo_manager``, ``call_later``) and **no**
  ``open_file`` member -- per Plan Rev 2 §4 Step 11.1.
* The protocol is :func:`typing.runtime_checkable` so
  ``isinstance(obj, WidgetServices)`` works at runtime.
* The :func:`fake_widget_services` fixture yields a real
  :class:`FakeWidgetServices` instance, **not** a
  :class:`unittest.mock.MagicMock`.
* The fake instance satisfies ``isinstance(obj, WidgetServices)``
  (selection_bus, undo_manager, call_later all present with the
  right shapes).
* The fake's ``call_later`` dispatches synchronously and returns a
  :class:`CallbackHandle` whose ``is_fired`` is True.
* The fake exposes a ``scheduled_calls`` history for test assertions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ovui_widgets.common.scheduler import CallbackHandle
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.services import WidgetServices
from ovui_widgets.common.undo import UndoManager

# ────────────────────────────────────────────────────────────────────
# Protocol shape
# ────────────────────────────────────────────────────────────────────


def test_widget_services_has_exactly_three_members():
    """Protocol surface is fixed at exactly three members.

    ``open_file`` is intentionally NOT on the Protocol -- content
    widgets use an explicit ``open_file_fn`` callback instead
    (Plan Rev 2 §4 Step 11.4).
    """
    expected = {"selection_bus", "undo_manager", "call_later"}
    actual = {
        name for name in WidgetServices.__dict__
        if not name.startswith("_") and not name.startswith("__")
    }
    assert actual == expected, (
        f"WidgetServices Protocol surface must be exactly {expected}; "
        f"got {actual}"
    )


def test_widget_services_does_not_include_open_file():
    """Negative test mirroring Codex Step 11.1 caution explicitly."""
    assert not hasattr(WidgetServices, "open_file"), (
        "open_file must NOT be a WidgetServices member; "
        "the open-file seam is an explicit ``open_file_fn`` callback "
        "kwarg per Plan Rev 2 §4 Step 11.4."
    )


def test_widget_services_is_runtime_checkable():
    """``isinstance(obj, WidgetServices)`` must work at runtime."""

    class _Stub:
        @property
        def selection_bus(self) -> SelectionBus:
            return SelectionBus()

        @property
        def undo_manager(self) -> UndoManager:
            return UndoManager()

        def call_later(self, delay_secs, callback) -> CallbackHandle:
            handle = CallbackHandle(due_time=0.0, callback=callback)
            handle._callback = None
            return handle

    assert isinstance(_Stub(), WidgetServices)


# ────────────────────────────────────────────────────────────────────
# fake_widget_services fixture
# ────────────────────────────────────────────────────────────────────


def test_fake_widget_services_is_not_magicmock(fake_widget_services):
    """Fixture must be an explicit class, not a MagicMock.

    A MagicMock would silently accept attribute typos and bypass the
    Protocol's three-member contract -- exactly the failure mode the
    plan refuses.
    """
    assert not isinstance(fake_widget_services, MagicMock)


def test_fake_widget_services_satisfies_protocol(fake_widget_services):
    """Runtime-checkable isinstance must accept the fake."""
    assert isinstance(fake_widget_services, WidgetServices)


def test_fake_widget_services_members_have_right_types(fake_widget_services):
    assert isinstance(fake_widget_services.selection_bus, SelectionBus)
    assert isinstance(fake_widget_services.undo_manager, UndoManager)
    # ``call_later`` is a bound method on the fake instance; its
    # return type is exercised below.
    assert callable(fake_widget_services.call_later)


def test_fake_widget_services_call_later_dispatches_synchronously(
    fake_widget_services,
):
    """The fake's ``call_later`` runs the callback immediately.

    Tests that defer work via ``call_later`` should still execute the
    deferred body so assertions about the deferred behavior are
    meaningful in the same test step.
    """
    fired: list[str] = []

    def _cb() -> None:
        fired.append("ran")

    handle = fake_widget_services.call_later(0.0, _cb)
    assert fired == ["ran"]
    assert isinstance(handle, CallbackHandle)
    # After synchronous dispatch the handle reports as fired.
    assert handle.is_fired is True


def test_fake_widget_services_records_scheduled_calls(fake_widget_services):
    """Fake exposes a ``scheduled_calls`` log for test assertions."""

    def _cb() -> None:
        pass

    fake_widget_services.call_later(0.15, _cb)
    fake_widget_services.call_later(0.25, _cb)
    delays = [d for (d, _) in fake_widget_services.scheduled_calls]
    assert delays == [0.15, 0.25]


def test_fake_widget_services_isolated_per_test(fake_widget_services):
    """Each test gets a fresh fixture (no shared state across tests)."""
    assert fake_widget_services.scheduled_calls == []
