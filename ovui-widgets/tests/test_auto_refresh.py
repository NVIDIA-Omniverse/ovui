# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the content browser implementation step 16 — auto-refresh on backend change events.

Two surfaces are exercised:

* **MockBackend subscription tracking** — :meth:`subscribe_changes`
  registers a callback keyed on a URL, :meth:`emit_change` fans out a
  synthesized :class:`BackendChangeEvent`, and the returned
  :class:`Subscription` cancels cleanly.
* **FileBrowserModel wiring** — subscribes in the constructor, routes
  ``"created"`` / ``"deleted"`` / ``"updated"`` events into the cached
  :class:`FileItem` tree, coalesces dispatches via the existing
  :meth:`_schedule_item_changed` batcher, and releases the
  subscription on :meth:`destroy`.

No :class:`ovui_widgets.app.application.Application` singleton is built — the
model's ``_schedule_item_changed`` falls back to immediate flush when
the singleton is absent, which is the path these tests exercise. The
one batching test monkeypatches a fake ``Application`` to observe the
pending-set coalescing directly.
"""

from __future__ import annotations

from typing import List

import pytest

import ovui_widgets.app.application as application_module
from ovui_widgets.app.testing import MockBackend
from ovui_widgets.content.backends.backend_adapter import (
    BackendChangeEvent,
    BackendFileFlags,
    BackendListEntry,
)
from ovui_widgets.content.widget.file_browser_model import FileBrowserModel
from ovui_widgets.content.widget.file_item import FileItem

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def model(backend: MockBackend):
    """Home-rooted :class:`FileBrowserModel` that tears down its subscription.

    ``destroy`` is idempotent so a test that calls it explicitly is
    safe — the fixture teardown invocation is a no-op in that case.
    """
    m = FileBrowserModel(backend, "mock://Home")
    yield m
    m.destroy()


def _entry(
    name: str,
    *,
    is_folder: bool = False,
    size: int = 0,
    modified: float = 1767225600.0,
) -> BackendListEntry:
    """Build a :class:`BackendListEntry` with readable+writable flags.

    Mirrors the default flag set on every :class:`MockBackend` entry so
    tests comparing flags against live children do not need to re-derive
    the base mask each time.
    """
    flags = BackendFileFlags.IS_READABLE | BackendFileFlags.IS_WRITABLE
    if is_folder:
        flags |= BackendFileFlags.IS_FOLDER
    return BackendListEntry(
        name=name,
        flags=flags,
        size=size,
        modified_time=modified,
        created_time=modified,
    )


# ──────────────────────────────────────────────────────────────────────────────
# MockBackend.subscribe_changes / emit_change
# ──────────────────────────────────────────────────────────────────────────────

class TestMockBackendSubscribeChanges:
    """The subscription surface that Step 16 adds to :class:`MockBackend`.

    Every test holds the returned handle for the duration of its
    assertion: :class:`_MockBackendSubscription.__del__` cancels on
    GC (matches :class:`ovui_widgets.common.settings.Subscription`), so an
    unreferenced handle would self-cancel before the check could run.
    """

    def test_returns_handle_with_cancel(self, backend: MockBackend):
        sub = backend.subscribe_changes("mock://Home", lambda e: None)
        assert hasattr(sub, "cancel")
        del sub

    def test_registers_callback_under_url(self, backend: MockBackend):
        sub = backend.subscribe_changes("mock://Home", lambda e: None)
        assert len(backend._subscribers["mock://Home"]) == 1
        del sub

    def test_multiple_subscribers_per_url(self, backend: MockBackend):
        sub_a = backend.subscribe_changes("mock://Home", lambda e: None)
        sub_b = backend.subscribe_changes("mock://Home", lambda e: None)
        assert len(backend._subscribers["mock://Home"]) == 2
        del sub_a, sub_b

    def test_cancel_removes_callback(self, backend: MockBackend):
        received: List[BackendChangeEvent] = []
        sub = backend.subscribe_changes("mock://Home", received.append)
        sub.cancel()
        backend.emit_change("mock://Home", "created", _entry("a.txt"))
        assert received == []

    def test_cancel_is_idempotent(self, backend: MockBackend):
        received: List[BackendChangeEvent] = []
        sub = backend.subscribe_changes("mock://Home", received.append)
        sub.cancel()
        sub.cancel()
        backend.emit_change("mock://Home", "created", _entry("a.txt"))
        assert received == []

    def test_cancel_prunes_empty_url_entry(self, backend: MockBackend):
        sub = backend.subscribe_changes("mock://Home", lambda e: None)
        sub.cancel()
        # Empty subscriber lists are dropped so the dict stays small
        # across subscribe/cancel churn — matches the behaviour of
        # ``ovui_widgets.common.settings.Settings._remove_subscriber``.
        assert "mock://Home" not in backend._subscribers

    def test_reset_clears_subscribers(self, backend: MockBackend):
        sub = backend.subscribe_changes("mock://Home", lambda e: None)
        backend.reset()
        assert backend._subscribers == {}
        del sub

    def test_dropping_handle_cancels_subscription(
        self, backend: MockBackend,
    ):
        """``__del__``-cancellation matches the Settings subscription
        pattern: a caller that doesn't retain the handle gets an
        ephemeral subscription. Tested explicitly so the contract
        doesn't drift silently."""
        received: List[BackendChangeEvent] = []
        backend.subscribe_changes("mock://Home", received.append)
        # No reference held → handle is eligible for collection; its
        # __del__ cancels the subscription.
        import gc
        gc.collect()
        backend.emit_change("mock://Home", "created", _entry("a.txt"))
        assert received == []


class TestMockBackendEmitChange:
    """The :meth:`MockBackend.emit_change` test hook fans out events."""

    def test_fires_subscribed_callback(self, backend: MockBackend):
        received: List[BackendChangeEvent] = []
        sub = backend.subscribe_changes("mock://Home", received.append)
        entry = _entry("new.txt")
        backend.emit_change("mock://Home", "created", entry)
        assert len(received) == 1
        event = received[0]
        assert event.url == "mock://Home"
        assert event.event_type == "created"
        assert event.entry is entry
        del sub

    def test_other_url_does_not_fire(self, backend: MockBackend):
        received: List[BackendChangeEvent] = []
        sub = backend.subscribe_changes("mock://Home", received.append)
        backend.emit_change("mock://Shared", "created", _entry("a.txt"))
        assert received == []
        del sub

    def test_all_subscribers_for_url_fire(self, backend: MockBackend):
        a: List[BackendChangeEvent] = []
        b: List[BackendChangeEvent] = []
        sub_a = backend.subscribe_changes("mock://Home", a.append)
        sub_b = backend.subscribe_changes("mock://Home", b.append)
        backend.emit_change("mock://Home", "deleted", _entry("x.txt"))
        assert len(a) == 1 and len(b) == 1
        del sub_a, sub_b

    def test_no_subscribers_is_noop(self, backend: MockBackend):
        # Must not raise even when nobody is listening.
        backend.emit_change("mock://Home", "created", _entry("a.txt"))

    def test_callback_that_cancels_mid_dispatch_is_safe(
        self, backend: MockBackend,
    ):
        """A callback cancelling its own sub mustn't break iteration.

        :meth:`emit_change` snapshots the subscriber list so the
        mutation inside the dispatch only takes effect on the next
        emit.
        """
        calls: List[str] = []
        # Mutable holder lets closure `a` cancel `sub_b` without a forward-ref
        # issue: the list cell is bound before `a` is defined, and filled in
        # before the first emit.
        sub_b_holder: List[object] = []

        def a(e: BackendChangeEvent) -> None:
            calls.append("a")
            # Cancel the other subscription in-flight.
            sub_b_holder[0].cancel()

        def b(e: BackendChangeEvent) -> None:
            calls.append("b")

        sub_a = backend.subscribe_changes("mock://Home", a)
        sub_b = backend.subscribe_changes("mock://Home", b)
        sub_b_holder.append(sub_b)
        backend.emit_change("mock://Home", "created", _entry("x.txt"))
        # Both ran on this dispatch (snapshot taken before iteration).
        assert calls == ["a", "b"]
        # Next emit — ``b`` is gone.
        calls.clear()
        backend.emit_change("mock://Home", "created", _entry("y.txt"))
        assert calls == ["a"]
        del sub_a, sub_b

    def test_event_type_is_free_form_string(self, backend: MockBackend):
        """Adapter contract (§3) allows backend-specific event types."""
        received: List[BackendChangeEvent] = []
        sub = backend.subscribe_changes("mock://Home", received.append)
        backend.emit_change("mock://Home", "obliterated", None)
        assert received[0].event_type == "obliterated"
        assert received[0].entry is None
        del sub


# ──────────────────────────────────────────────────────────────────────────────
# Model subscribes on construction
# ──────────────────────────────────────────────────────────────────────────────

class TestModelSubscribesOnConstruction:
    def test_subscription_registered_on_root_url(self, backend: MockBackend):
        assert backend._subscribers.get("mock://Home") is None
        m = FileBrowserModel(backend, "mock://Home")
        try:
            assert len(backend._subscribers["mock://Home"]) == 1
        finally:
            m.destroy()

    def test_change_sub_attr_is_set(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home")
        try:
            assert m._change_sub is not None
        finally:
            m.destroy()

    def test_normalized_root_url_is_subscription_key(
        self, backend: MockBackend,
    ):
        # Subscription keys on the *normalized* root URL, so redundant
        # slashes / dot segments round-trip through the same key the
        # model uses for cache lookups.
        m = FileBrowserModel(backend, "mock://Home/./")
        try:
            assert "mock://Home" in backend._subscribers
            assert "mock://Home/./" not in backend._subscribers
        finally:
            m.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# _on_backend_change: "created"
# ──────────────────────────────────────────────────────────────────────────────

class TestCreatedEvent:
    def test_created_adds_child_under_cached_target(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        before = [c.name for c in model.get_item_children(model.root)]
        entry = _entry("new_file.txt", size=42)
        backend.emit_change("mock://Home", "created", entry)
        after = [c.name for c in model.get_item_children(model.root)]
        assert "new_file.txt" in after
        assert len(after) == len(before) + 1

    def test_created_child_url_registered_in_cache(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        backend.emit_change("mock://Home", "created", _entry("new.txt"))
        new_url = "mock://Home/new.txt"
        assert new_url in model._cache
        assert model._cache[new_url].name == "new.txt"

    def test_created_child_parent_pointer_set(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        backend.emit_change("mock://Home", "created", _entry("new.txt"))
        new_child = model._cache["mock://Home/new.txt"]
        assert new_child.parent is model.root

    def test_created_folder_flag_preserved(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        backend.emit_change(
            "mock://Home", "created", _entry("NewDir", is_folder=True),
        )
        children = model.get_item_children(model.root)
        new = next(c for c in children if c.name == "NewDir")
        assert new.is_folder is True

    def test_created_size_and_modified_preserved(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        backend.emit_change(
            "mock://Home",
            "created",
            _entry("new.bin", size=4096, modified=1800000000.0),
        )
        new = next(
            c for c in model.get_item_children(model.root)
            if c.name == "new.bin"
        )
        assert new.size == 4096
        assert new.modified == 1800000000.0

    def test_created_on_untracked_folder_is_dropped(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        """URL not in cache → model ignores the event. Populate later
        will fetch the authoritative state directly."""
        backend.emit_change("mock://Shared", "created", _entry("x.txt"))
        assert "mock://Shared/x.txt" not in model._cache


# ──────────────────────────────────────────────────────────────────────────────
# _on_backend_change: "deleted"
# ──────────────────────────────────────────────────────────────────────────────

class TestDeletedEvent:
    def test_deleted_removes_child_from_snapshot(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        assert "Documents" in [
            c.name for c in model.get_item_children(model.root)
        ]
        backend.emit_change(
            "mock://Home", "deleted", _entry("Documents", is_folder=True),
        )
        after = [c.name for c in model.get_item_children(model.root)]
        assert "Documents" not in after

    def test_deleted_drops_child_url_from_cache(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        assert "mock://Home/Documents" in model._cache
        backend.emit_change(
            "mock://Home", "deleted", _entry("Documents", is_folder=True),
        )
        assert "mock://Home/Documents" not in model._cache

    def test_deleted_missing_name_is_noop(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        backend.emit_change(
            "mock://Home", "deleted", _entry("never_existed"),
        )
        # Existing structure unchanged.
        assert "Documents" in [
            c.name for c in model.get_item_children(model.root)
        ]


# ──────────────────────────────────────────────────────────────────────────────
# _on_backend_change: "updated"
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdatedEvent:
    def test_updated_rewrites_size_on_existing_child(
        self, backend: MockBackend,
    ):
        """Model rooted directly at Projects so the emit URL matches
        its subscription key (mock backend is exact-URL match)."""
        m = FileBrowserModel(backend, "mock://Home/Documents/Projects")
        try:
            children = m.get_item_children(m.root)
            demo = next(c for c in children if c.name == "demo.usda")
            assert demo.size == 128
            backend.emit_change(
                "mock://Home/Documents/Projects",
                "updated",
                _entry("demo.usda", size=999),
            )
            assert demo.size == 999
        finally:
            m.destroy()

    def test_updated_refreshes_size_model_text(
        self, backend: MockBackend,
    ):
        """Pushing through ``update_metadata`` updates the lazy
        :class:`SimpleStringModel` so a bound view repaints."""
        m = FileBrowserModel(backend, "mock://Home/Documents/Projects")
        try:
            children = m.get_item_children(m.root)
            demo = next(c for c in children if c.name == "demo.usda")
            # Force allocation — update_metadata short-circuits on
            # models that were never requested.
            demo.get_size_model()
            backend.emit_change(
                "mock://Home/Documents/Projects",
                "updated",
                _entry("demo.usda", size=2048),
            )
            assert demo.get_size_model().get_value_as_string() == "2.0 KB"
        finally:
            m.destroy()

    def test_updated_refreshes_modified_time(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home/Documents/Projects")
        try:
            children = m.get_item_children(m.root)
            demo = next(c for c in children if c.name == "demo.usda")
            backend.emit_change(
                "mock://Home/Documents/Projects",
                "updated",
                _entry("demo.usda", size=128, modified=1900000000.0),
            )
            assert demo.modified == 1900000000.0
        finally:
            m.destroy()

    def test_updated_missing_name_is_noop(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home/Documents/Projects")
        try:
            m.get_item_children(m.root)
            backend.emit_change(
                "mock://Home/Documents/Projects",
                "updated",
                _entry("never_existed", size=1),
            )
            # No exception; existing children intact.
            children = m.get_item_children(m.root)
            assert {c.name for c in children} == {
                "demo.usda", "demo.usdc", "readme.md",
            }
        finally:
            m.destroy()


# ──────────────────────────────────────────────────────────────────────────────
# Unknown / malformed events
# ──────────────────────────────────────────────────────────────────────────────

class TestUnknownEventTypes:
    def test_unknown_event_type_is_dropped(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        # Custom event type (e.g. Nucleus-specific) is ignored per
        # the content browser behavior
        backend.emit_change(
            "mock://Home", "obliterated", _entry("Documents", is_folder=True),
        )
        after = [c.name for c in model.get_item_children(model.root)]
        assert "Documents" in after  # not affected

    def test_event_without_entry_is_dropped(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        # No entry → model has no name to key on; silently ignored.
        backend.emit_change("mock://Home", "created", None)
        # No orphan cache entries added.
        assert all(
            url.startswith("mock://Home") for url in model._cache
        )


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch: item_changed is scheduled after handled events
# ──────────────────────────────────────────────────────────────────────────────

class TestItemChangedDispatch:
    def test_handled_event_dispatches_item_changed(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        """Without an :class:`Application` singleton, the deferred
        dispatch path falls back to immediate flush, so a
        ``subscribe_item_changed_fn`` subscriber sees the dispatch
        synchronously."""
        model.get_item_children(model.root)
        received: List[FileItem] = []

        def _cb(mdl, item):
            if isinstance(item, FileItem):
                received.append(item)

        sub = model.subscribe_item_changed_fn(_cb)
        backend.emit_change("mock://Home", "created", _entry("a.txt"))
        assert model.root in received
        del sub

    def test_unknown_event_does_not_dispatch(
        self, backend: MockBackend, model: FileBrowserModel,
    ):
        model.get_item_children(model.root)
        received: List[FileItem] = []

        def _cb(mdl, item):
            if isinstance(item, FileItem):
                received.append(item)

        sub = model.subscribe_item_changed_fn(_cb)
        backend.emit_change("mock://Home", "obliterated", _entry("x"))
        assert received == []
        del sub


# ──────────────────────────────────────────────────────────────────────────────
# Batching: multiple events fold into one pending set entry
# ──────────────────────────────────────────────────────────────────────────────

class TestBatching:
    def test_multiple_events_coalesce_when_application_is_present(
        self, backend: MockBackend, monkeypatch: pytest.MonkeyPatch,
    ):
        """A burst of events targeting the same folder produces one
        pending entry — the set-based batcher deduplicates.

        Per Rev 8 §5.5 (Step 5), widget code routes through
        :func:`ovui_widgets.common.scheduler.call_later`. This test
        registers a fake ``call_later`` backend so dispatch stays queued
        (returns a truthy handle) and the pending set is observable.
        """

        class _FakeHandle:
            def cancel(self):
                pass

        def fake_call_later(delay, callback):
            # Return a truthy handle with a cancel() method so the
            # model marks the dispatch as pending and stops scheduling
            # duplicates. The callback itself is intentionally never
            # fired — this test only observes the pending set.
            return _FakeHandle()

        from ovui_widgets.common import scheduler as _scheduler
        prior_fn = _scheduler._call_later_fn
        _scheduler.set_call_later(fake_call_later)
        try:
            m = FileBrowserModel(backend, "mock://Home")
            try:
                m.get_item_children(m.root)
                m._pending_item_changed.clear()
                backend.emit_change("mock://Home", "created", _entry("a.txt"))
                backend.emit_change("mock://Home", "created", _entry("b.txt"))
                backend.emit_change(
                    "mock://Home", "updated",
                    _entry("Documents", is_folder=True),
                )
                # Set semantics — same target item, single entry.
                assert m._pending_item_changed == {m.root}
            finally:
                m.destroy()
        finally:
            _scheduler.set_call_later(prior_fn)


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle: destroy cancels subscription
# ──────────────────────────────────────────────────────────────────────────────

class TestDestroyCancelsSubscription:
    def test_destroy_removes_backend_subscriber(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home")
        assert len(backend._subscribers["mock://Home"]) == 1
        m.destroy()
        # Pruned entirely when list empties.
        assert "mock://Home" not in backend._subscribers

    def test_destroy_nulls_subscription_handle(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home")
        assert m._change_sub is not None
        m.destroy()
        assert m._change_sub is None

    def test_emit_after_destroy_does_not_crash(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home")
        m.get_item_children(m.root)
        m.destroy()
        # No exception — no one listens any more.
        backend.emit_change("mock://Home", "created", _entry("ghost.txt"))

    def test_destroy_is_idempotent(self, backend: MockBackend):
        m = FileBrowserModel(backend, "mock://Home")
        m.destroy()
        m.destroy()  # Must not raise.

    def test_destroy_clears_pending_item_changed(
        self, backend: MockBackend, monkeypatch: pytest.MonkeyPatch,
    ):
        """Pending set must be drained so a deferred flush cannot fire
        with a stale item after the widget has torn down the model.

        Per Rev 8 §5.5 (Step 5), widget code routes through
        ``ovui_widgets.common.scheduler.call_later``; this test registers
        a fake backend that returns a truthy ``_FakeHandle`` so the
        model marks the dispatch as pending.
        """

        class _FakeHandle:
            def cancel(self):
                pass

        def fake_call_later(delay, callback):
            return _FakeHandle()

        from ovui_widgets.common import scheduler as _scheduler
        prior_fn = _scheduler._call_later_fn
        _scheduler.set_call_later(fake_call_later)
        try:
            m = FileBrowserModel(backend, "mock://Home")
            m.get_item_children(m.root)
            backend.emit_change("mock://Home", "created", _entry("x.txt"))
            assert m._pending_item_changed  # non-empty
            m.destroy()
            assert m._pending_item_changed == set()
        finally:
            _scheduler.set_call_later(prior_fn)
