# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 7.3 — ``ScrollPreserver``.

the property inspector step 7.3 done signal: "select A, scroll down, re-select
A → scroll preserved; select B (different scheme) → scroll reset".

Architecture: :class:`~ovui_widgets.property.widget.scroll_preserver.ScrollPreserver`
is a plain helper owned by :class:`~ovui_widgets.property.window.PropertyWindow`.
It reads ``scroll_y`` off an injected :class:`ui.ScrollingFrame` getter
on :meth:`save_position` and schedules a two-frame deferred write back
on :meth:`restore_position`. Whether the write is the saved value
(preserve) or ``0.0`` (reset) depends on whether the new payload's
scheme matches the prior payload's scheme. The two-frame deferral
survives omni.ui's layout pass so the write doesn't get clamped against
a still-zero ``scroll_y_max``.

The tests drive the preserver through a stub frame (a plain class with
a ``scroll_y`` attribute) and a stub ``call_later`` that captures the
scheduled callbacks into a FIFO queue so the test can fire them on
demand. This keeps the timing mechanism observable without needing a
running :class:`Application` or an initialised ``omni.ui`` root.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeScrollFrame:
    """Plain carrier for ``scroll_y``; stands in for :class:`ui.ScrollingFrame`."""

    def __init__(self, scroll_y: float = 0.0) -> None:
        self.scroll_y = scroll_y


class _FakeHandle:
    """Handle returned by the stub ``call_later`` — records cancellation."""

    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeCallLater:
    """Synchronous ``call_later`` stub.

    The real :meth:`ovui_widgets.app.application.Application.call_later` fires its
    callback on the next frame tick. The preserver chains two calls so
    the write lands two frames after the rebuild. Tests need a way to
    walk those two ticks deterministically — this stub stores each
    scheduled callback in a FIFO list that :meth:`fire_next` / :meth:`fire_all`
    pop and invoke.
    """

    def __init__(self) -> None:
        self.pending: List[_FakeHandle] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> _FakeHandle:
        handle = _FakeHandle(callback)
        self.pending.append(handle)
        return handle

    def fire_next(self) -> None:
        """Fire the first pending non-cancelled callback."""
        while self.pending:
            h = self.pending.pop(0)
            if not h.cancelled:
                h.callback()
                return

    def fire_all(self) -> None:
        """Fire every scheduled callback until the queue stabilises.

        Each callback may schedule more callbacks (the preserver's first
        tick schedules the second tick). Loop until the queue is empty
        of non-cancelled entries.
        """
        while any(not h.cancelled for h in self.pending):
            self.fire_next()


def _make_preserver(frame: Optional[_FakeScrollFrame] = None):
    """Build a :class:`ScrollPreserver` + the call_later stub it drives."""
    from ovui_widgets.property.widget.scroll_preserver import ScrollPreserver
    call_later = _FakeCallLater()
    frame_box: List[Optional[_FakeScrollFrame]] = [frame]
    p = ScrollPreserver(
        frame_getter=lambda: frame_box[0],
        call_later=call_later,
    )
    return p, call_later, frame_box


# ---------------------------------------------------------------------------
# Module / export shape
# ---------------------------------------------------------------------------


class TestPackageStructure:
    def test_module_importable(self) -> None:
        import ovui_widgets.property.widget.scroll_preserver as mod  # noqa: F401

    def test_class_exported_from_widget_package(self) -> None:
        from ovui_widgets.property.widget import ScrollPreserver as Exported
        from ovui_widgets.property.widget.scroll_preserver import ScrollPreserver as Direct
        assert Exported is Direct

    def test_class_in_widget_package_all(self) -> None:
        import ovui_widgets.property.widget as pkg
        assert "ScrollPreserver" in pkg.__all__


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_construct_with_live_frame(self) -> None:
        p, _, _ = _make_preserver(_FakeScrollFrame())
        assert p is not None

    def test_construct_without_frame(self) -> None:
        """``frame_getter`` returning ``None`` is a valid initial state
        — the window's UI is built after the preserver is constructed."""
        p, _, _ = _make_preserver(frame=None)
        assert p is not None

    def test_initial_state_has_no_prev_scheme(self) -> None:
        p, _, _ = _make_preserver(_FakeScrollFrame())
        assert p._prev_scheme is None

    def test_initial_state_has_no_saved_scroll(self) -> None:
        p, _, _ = _make_preserver(_FakeScrollFrame())
        assert p._saved_scroll_y is None


# ---------------------------------------------------------------------------
# Save position
# ---------------------------------------------------------------------------


class TestSavePosition:
    def test_saves_current_scroll_y(self) -> None:
        frame = _FakeScrollFrame(scroll_y=42.5)
        p, _, _ = _make_preserver(frame)
        p.save_position()
        assert p._saved_scroll_y == 42.5

    def test_save_without_frame_is_no_op(self) -> None:
        p, _, frame_box = _make_preserver(frame=None)
        p.save_position()
        assert p._saved_scroll_y is None

    def test_save_converts_to_float(self) -> None:
        frame = _FakeScrollFrame(scroll_y=17)
        p, _, _ = _make_preserver(frame)
        p.save_position()
        assert isinstance(p._saved_scroll_y, float)
        assert p._saved_scroll_y == 17.0

    def test_save_handles_broken_frame_gracefully(self) -> None:
        """If a stub frame's ``scroll_y`` property raises (headless
        edge-cases sometimes do) the preserver falls back to
        ``None`` instead of crashing the owning rebuild."""
        class _BrokenFrame:
            @property
            def scroll_y(self) -> float:  # pragma: no cover - behaviour is the raise
                raise RuntimeError("no ui root")
        p, _, frame_box = _make_preserver()
        frame_box[0] = _BrokenFrame()  # type: ignore[assignment]
        p.save_position()
        assert p._saved_scroll_y is None


# ---------------------------------------------------------------------------
# Restore — first-time (no prior scheme) always resets to 0
# ---------------------------------------------------------------------------


class TestFirstRestoreResetsToZero:
    def test_first_restore_without_save_resets_to_zero(self) -> None:
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        p.restore_position("default")
        call_later.fire_all()
        assert frame.scroll_y == 0.0

    def test_first_restore_after_save_still_resets(self) -> None:
        """Even if :meth:`save_position` ran, the very first restore
        has no prior scheme to compare against so the reset branch
        fires. The saved value is effectively ignored on the first
        rebuild (which matches real-world behaviour: the first
        selection has no prior state to preserve from)."""
        frame = _FakeScrollFrame(scroll_y=200.0)
        p, call_later, _ = _make_preserver(frame)
        p.save_position()
        # scroll_y still 200 on the frame — simulate the rebuild
        # clearing and recreating content; the frame's scroll_y drops
        # back to 0 internally.
        frame.scroll_y = 0.0
        p.restore_position("default")
        call_later.fire_all()
        assert frame.scroll_y == 0.0  # reset, not preserved

    def test_first_restore_records_new_scheme(self) -> None:
        p, call_later, _ = _make_preserver(_FakeScrollFrame())
        p.restore_position("default")
        assert p._prev_scheme == "default"


# ---------------------------------------------------------------------------
# Restore — same scheme preserves the saved position
# ---------------------------------------------------------------------------


class TestSameSchemePreserves:
    def test_second_restore_same_scheme_preserves(self) -> None:
        """Select A (scheme ``default``), scroll down, re-select A →
        scroll position is restored."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        # Rebuild #1: no prior scheme, so scroll resets.
        p.save_position()  # nothing to save — scroll_y is 0
        p.restore_position("default")
        call_later.fire_all()
        assert frame.scroll_y == 0.0

        # User scrolls down 120 px.
        frame.scroll_y = 120.0

        # Rebuild #2: same scheme, scroll should preserve.
        p.save_position()  # saves 120
        frame.scroll_y = 0.0  # simulate rebuild clearing content
        p.restore_position("default")
        call_later.fire_all()
        assert frame.scroll_y == 120.0

    def test_preserve_through_multiple_same_scheme_rebuilds(self) -> None:
        """Several rebuilds on the same scheme keep walking the saved
        scroll forward: whatever the user last set is what the next
        rebuild should restore."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        # First rebuild establishes the scheme.
        p.save_position()
        p.restore_position("default")
        call_later.fire_all()

        for target in (50.0, 100.0, 75.0, 200.0):
            frame.scroll_y = target  # user scrolls
            p.save_position()
            frame.scroll_y = 0.0  # simulated rebuild
            p.restore_position("default")
            call_later.fire_all()
            assert frame.scroll_y == target


# ---------------------------------------------------------------------------
# Restore — different scheme resets to 0
# ---------------------------------------------------------------------------


class TestSchemeChangeResets:
    def test_scheme_change_resets_scroll_to_zero(self) -> None:
        """Select A (scheme ``shape``), scroll, then select B
        (scheme ``light``) → scroll resets to 0."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        # Rebuild #1: establish the scheme.
        p.save_position()
        p.restore_position("shape")
        call_later.fire_all()

        # User scrolls down.
        frame.scroll_y = 150.0

        # Rebuild #2: different scheme → reset.
        p.save_position()  # saves 150
        frame.scroll_y = 0.0  # simulated rebuild
        p.restore_position("light")  # scheme changes
        call_later.fire_all()
        assert frame.scroll_y == 0.0

    def test_scheme_change_updates_prev_scheme(self) -> None:
        """After a scheme change, the preserver stores the new scheme so
        the subsequent restore compares against it correctly (not
        against the two-rebuilds-ago scheme)."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        p.restore_position("shape")
        call_later.fire_all()
        p.restore_position("light")
        call_later.fire_all()
        assert p._prev_scheme == "light"

    def test_preserve_after_reset_tracks_new_scheme(self) -> None:
        """Select A, scroll, select B (reset), scroll in B, re-select B →
        should preserve B's scroll because the scheme matched."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        # A: establish scheme ``shape``.
        p.save_position()
        p.restore_position("shape")
        call_later.fire_all()
        frame.scroll_y = 100.0
        # Switch to B — reset.
        p.save_position()
        frame.scroll_y = 0.0
        p.restore_position("light")
        call_later.fire_all()
        assert frame.scroll_y == 0.0

        # Scroll in B.
        frame.scroll_y = 60.0
        p.save_position()
        frame.scroll_y = 0.0
        p.restore_position("light")
        call_later.fire_all()
        assert frame.scroll_y == 60.0


# ---------------------------------------------------------------------------
# Timing — the two-frame deferred write
# ---------------------------------------------------------------------------


class TestDeferredTiming:
    def test_restore_schedules_callback(self) -> None:
        """:meth:`restore_position` does not write ``scroll_y`` directly
        — the write is a scheduled deferred callback."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        p.restore_position("default")
        # The write has not fired yet — at least one callback pending.
        assert any(not h.cancelled for h in call_later.pending)

    def test_scroll_y_unchanged_before_any_tick_fires(self) -> None:
        frame = _FakeScrollFrame(scroll_y=99.0)
        p, call_later, _ = _make_preserver(frame)
        p.restore_position("default")
        # Deliberately do NOT fire the callback.
        assert frame.scroll_y == 99.0

    def test_first_tick_does_not_write_scroll(self) -> None:
        """The first :meth:`call_later` tick only schedules the second
        tick — the actual write fires on the second."""
        frame = _FakeScrollFrame(scroll_y=99.0)
        p, call_later, _ = _make_preserver(frame)
        p.restore_position("default")
        # Fire first tick only.
        call_later.fire_next()
        assert frame.scroll_y == 99.0  # unchanged

    def test_second_tick_writes_scroll(self) -> None:
        frame = _FakeScrollFrame(scroll_y=99.0)
        p, call_later, _ = _make_preserver(frame)
        p.restore_position("default")
        call_later.fire_next()  # first tick: schedules second
        call_later.fire_next()  # second tick: writes scroll
        assert frame.scroll_y == 0.0  # reset (first restore)

    def test_restore_scheduled_even_when_frame_is_none(self) -> None:
        """The preserver doesn't know whether the frame will come back
        by the time the deferred write fires. Schedule the callback
        anyway; the callback handles ``frame is None`` on fire."""
        p, call_later, frame_box = _make_preserver(frame=None)
        p.restore_position("default")
        call_later.fire_all()  # must not raise
        assert frame_box[0] is None  # still None


# ---------------------------------------------------------------------------
# Cancellation — rapid selection changes collapse pending writes
# ---------------------------------------------------------------------------


class TestPendingCancellation:
    def test_second_restore_cancels_prior_pending(self) -> None:
        """Two back-to-back selection changes (before the first restore
        has fired) must not leave a stale write queued. The second
        :meth:`restore_position` cancels the first's pending handles."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)

        # First: will write 0 (first restore, scheme ``a``).
        p.restore_position("a")
        first_pending = list(call_later.pending)
        assert len(first_pending) == 1

        # Second: cancels first, schedules new (scheme ``b``, reset).
        p.restore_position("b")
        assert first_pending[0].cancelled is True

    def test_destroy_cancels_pending(self) -> None:
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        p.restore_position("default")
        pending = list(call_later.pending)
        p.destroy()
        assert all(h.cancelled for h in pending)

    def test_destroy_clears_state(self) -> None:
        p, _, _ = _make_preserver(_FakeScrollFrame(10.0))
        p.save_position()
        p.restore_position("default")
        p.destroy()
        assert p._saved_scroll_y is None
        assert p._prev_scheme is None

    def test_destroy_is_idempotent(self) -> None:
        p, _, _ = _make_preserver(_FakeScrollFrame())
        p.destroy()
        p.destroy()  # must not raise


# ---------------------------------------------------------------------------
# Integration — PropertyWindow._rebuild_content threads save/restore
# ---------------------------------------------------------------------------


def _make_headless_window_with_preserver_stub():
    """A bypass-``__init__`` :class:`PropertyWindow` with a stub preserver."""
    from ovui_widgets.property.window import PropertyWindow

    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._group_collapse_state = {}
    w._active_context_menu = None
    w._bus_sub = None
    w._stage_adapter = None
    w._stage_change_sub = None
    w._undo_manager_ref = None
    w._widgets = []
    w._default_attributes = None
    w._scroll_frame = None
    return w


class _RecordingPreserver:
    """Spy double — observes save/restore calls from
    :meth:`PropertyWindow._rebuild_content`."""

    def __init__(self) -> None:
        self.save_calls = 0
        self.restore_calls: List[str] = []
        self.destroy_calls = 0

    def save_position(self) -> None:
        self.save_calls += 1

    def restore_position(self, new_scheme: str) -> None:
        self.restore_calls.append(new_scheme)

    def destroy(self) -> None:
        self.destroy_calls += 1


class _FakeVStack:
    def clear(self) -> None:
        pass

    def __enter__(self) -> "_FakeVStack":
        return self

    def __exit__(self, *a: Any) -> bool:
        return False


class TestPropertyWindowIntegration:
    def test_rebuild_with_no_content_skips_preserver(self) -> None:
        """``_content is None`` → early-return before preserver runs."""
        w = _make_headless_window_with_preserver_stub()
        w._content = None
        spy = _RecordingPreserver()
        w._scroll_preserver = spy
        w._rebuild_content()
        assert spy.save_calls == 0
        assert spy.restore_calls == []

    def test_rebuild_without_selection_saves_and_resets(self) -> None:
        """Empty selection → save fires (preserver captures the current
        scroll for the transitioned-away state), then restore fires with
        a sentinel scheme that forces the reset branch so the next
        non-empty selection starts fresh."""
        w = _make_headless_window_with_preserver_stub()
        w._content = _FakeVStack()
        w._selection = []
        w._adapter = None
        spy = _RecordingPreserver()
        w._scroll_preserver = spy
        w._rebuild_content()
        assert spy.save_calls == 1
        assert len(spy.restore_calls) == 1
        # The sentinel must not collide with a real adapter scheme so
        # the next non-empty rebuild forces the reset branch.
        assert spy.restore_calls[0] == "__empty__"

    def test_rebuild_with_selection_saves_and_restores_with_payload_scheme(
        self, monkeypatch,
    ) -> None:
        """A non-empty rebuild fires save, clears, builds, then restore
        with the payload's scheme. The preserver decides preserve vs
        reset based on the scheme string."""
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget

        # Stub out AttributesWidget.build_items so the test doesn't
        # depend on real omni.ui widgets.
        monkeypatch.setattr(
            AttributesWidget, "build_items", lambda self: None,
        )

        w = _make_headless_window_with_preserver_stub()
        w._content = _FakeVStack()
        w._adapter = object()  # truthy adapter is enough
        w._selection = ["/World/A"]
        spy = _RecordingPreserver()
        w._scroll_preserver = spy
        w._rebuild_content()
        assert spy.save_calls == 1
        # PropertyPayload.get_scheme() defaults to "default" today.
        assert spy.restore_calls == ["default"]

    def test_destroy_tears_down_preserver(self, monkeypatch) -> None:
        """:meth:`PropertyWindow.destroy` calls
        :meth:`ScrollPreserver.destroy` so pending handles don't fire
        after the window is gone. Bypass :meth:`ManagedWindow.destroy`
        via a monkey-patched no-op so the test doesn't need a live
        ui.Window scope."""
        from ovui_widgets.common.managed_window import ManagedWindow
        from ovui_widgets.property.window import PropertyWindow

        monkeypatch.setattr(ManagedWindow, "destroy", lambda self: None)

        w = _make_headless_window_with_preserver_stub()
        spy = _RecordingPreserver()
        w._scroll_preserver = spy
        PropertyWindow.destroy(w)
        assert spy.destroy_calls == 1
        assert w._scroll_preserver is None

    def test_rebuild_skips_preserver_when_none(self, monkeypatch) -> None:
        """Pre-``_build_ui`` rebuilds (when ``_scroll_preserver is None``)
        must not crash — the bypass-init helpers rely on this path."""
        from ovui_widgets.property.widget.attributes_widget import AttributesWidget
        monkeypatch.setattr(
            AttributesWidget, "build_items", lambda self: None,
        )
        w = _make_headless_window_with_preserver_stub()
        w._content = _FakeVStack()
        w._adapter = object()
        w._selection = ["/World/A"]
        w._scroll_preserver = None
        w._rebuild_content()  # must not raise


# ---------------------------------------------------------------------------
# Integration — live ScrollPreserver wired into PropertyWindow rebuild
# ---------------------------------------------------------------------------


class TestEndToEndWithLivePreserver:
    def test_same_scheme_preserves_through_two_rebuilds(self) -> None:
        """Full path: real :class:`ScrollPreserver`, real fake frame,
        synchronous call_later stub. Two rebuilds on the same scheme
        and the second rebuild writes the first's saved scroll back."""
        from ovui_widgets.property.widget.scroll_preserver import ScrollPreserver

        frame = _FakeScrollFrame(scroll_y=0.0)
        call_later = _FakeCallLater()
        preserver = ScrollPreserver(
            frame_getter=lambda: frame,
            call_later=call_later,
        )
        # Rebuild #1.
        preserver.save_position()
        preserver.restore_position("default")
        call_later.fire_all()
        # User scrolls.
        frame.scroll_y = 87.0
        # Rebuild #2 (same scheme).
        preserver.save_position()
        frame.scroll_y = 0.0
        preserver.restore_position("default")
        call_later.fire_all()
        assert frame.scroll_y == 87.0

    def test_scheme_change_resets_through_two_rebuilds(self) -> None:
        from ovui_widgets.property.widget.scroll_preserver import ScrollPreserver

        frame = _FakeScrollFrame(scroll_y=0.0)
        call_later = _FakeCallLater()
        preserver = ScrollPreserver(
            frame_getter=lambda: frame,
            call_later=call_later,
        )
        preserver.save_position()
        preserver.restore_position("shape")
        call_later.fire_all()
        frame.scroll_y = 60.0
        preserver.save_position()
        frame.scroll_y = 0.0
        preserver.restore_position("light")
        call_later.fire_all()
        assert frame.scroll_y == 0.0


# ---------------------------------------------------------------------------
# Payload-scheme matching — the restore takes a scheme string directly,
# not a PropertyPayload. Confirms the decoupling the plan calls for.
# ---------------------------------------------------------------------------


class TestSchemeStringContract:
    def test_accepts_arbitrary_scheme_strings(self) -> None:
        """Any string works — the preserver does ``==`` not an enum
        check, so new schemes registered at runtime (phase 6.5+) Just
        Work without preserver updates."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        for scheme in ("default", "shape", "light", "custom_extension"):
            p.restore_position(scheme)
            call_later.fire_all()
        assert p._prev_scheme == "custom_extension"

    def test_empty_string_is_a_valid_scheme(self) -> None:
        """Empty string must compare equal to itself (preserve) but
        not to any other scheme (reset)."""
        frame = _FakeScrollFrame(scroll_y=0.0)
        p, call_later, _ = _make_preserver(frame)
        p.save_position()
        p.restore_position("")
        call_later.fire_all()
        # Same empty-scheme rebuild preserves.
        frame.scroll_y = 40.0
        p.save_position()
        frame.scroll_y = 0.0
        p.restore_position("")
        call_later.fire_all()
        assert frame.scroll_y == 40.0
