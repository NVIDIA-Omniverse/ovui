# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Idempotency and best-effort teardown tests for ``Application.shutdown()``.

Issue #35 — Step 1.

After issue #35's full fix lands, ``Application.shutdown()`` is called
from two places: explicitly by test scripts (and any future
``Application.request_exit`` API) and implicitly from
``Application.run_async``'s ``finally:`` clause. Both paths must
coexist without crashing or double-tearing-down resources, and a
failure in any single teardown block must NOT skip the rest of the
teardown — that's the bug that survived into ``Py_FinalizeEx`` and
caused the segfault.

This file tests the redesigned ``shutdown()`` body in isolation. The
``run_async`` wiring lands in a later step.

Test list (matches the plan's Step 1 verification):

1. ``test_shutdown_can_be_called_twice_in_a_row``
2. ``test_shutdown_clears_panel_references_on_first_call``
3. ``test_shutdown_resets_application_singleton``
4. ``test_second_shutdown_does_not_clobber_state``
5. ``test_shutdown_done_flag_set_after_success``
6. ``test_shutdown_then_save_layout_does_not_double_save``
7. ``test_partial_failure_continues_teardown`` — best-effort, NOT retry
8. ``test_recursion_short_circuited``
9. ``test_save_layout_failure_does_not_skip_dockspace``
"""
from __future__ import annotations

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus

_PANEL_ATTRS = (
    "_stage_window",
    "_property_window",
    "_viewport_window",
    "_content_window",
    "_layer_window",
)


class _FakePanel:
    """Mimics the shape ``Application.shutdown()`` requires of a panel
    window: a callable ``destroy()`` that we can inspect afterwards."""

    def __init__(self) -> None:
        self.destroy_calls = 0

    def destroy(self) -> None:
        self.destroy_calls += 1


def _attach_fake_panels(app: Application) -> dict:
    """Replace each panel attribute on ``app`` with a fresh ``_FakePanel``
    and return the mapping for post-shutdown assertions."""
    panels: dict = {}
    for attr in _PANEL_ATTRS:
        panel = _FakePanel()
        setattr(app, attr, panel)
        panels[attr] = panel
    return panels


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset Application/SelectionBus singletons around each test."""
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        Application._instance = None
    SelectionBus._instance = None


def test_shutdown_can_be_called_twice_in_a_row() -> None:
    """Two consecutive shutdown() calls must not raise."""
    app = Application()
    app.shutdown()
    # Second call must be a no-op, not a crash.
    app.shutdown()


def test_shutdown_clears_panel_references_on_first_call() -> None:
    """First shutdown() destroys every panel and nulls its attribute.

    A bare ``Application()`` leaves panel attributes at None (run_async
    is what builds them). To prove the teardown loop actually runs and
    reaches ``destroy()`` + ``setattr(...None)``, attach _FakePanel
    instances first and assert the loop hit each one.
    """
    app = Application()
    panels = _attach_fake_panels(app)
    app.shutdown()
    # Every panel's destroy() ran exactly once and its attribute was
    # nulled — the try/except/finally pattern from Round 5 F1.
    for attr, panel in panels.items():
        assert panel.destroy_calls == 1, (
            f"{attr}.destroy() was called {panel.destroy_calls} times"
        )
        assert getattr(app, attr) is None, (
            f"{attr} was not nulled after shutdown()"
        )
    # The other window/dockspace/adapter attributes also clear.
    for attr in (
        "_dockspace",
        "_main_win",
        "_status_win",
        "_status_bar",
        "_layer_adapter",
        "_stage_adapter",
    ):
        assert getattr(app, attr, None) is None, attr


def test_shutdown_resets_application_singleton() -> None:
    """First shutdown() clears Application._instance."""
    app = Application()
    assert Application._instance is app
    app.shutdown()
    assert Application._instance is None


def test_second_shutdown_does_not_clobber_state() -> None:
    """Second shutdown() must not raise nor mutate state.

    ``_shutdown_done`` short-circuits the body entirely on subsequent
    calls — the "did everything once" guarantee.
    """
    app = Application()
    app.shutdown()
    assert Application._instance is None
    assert app._shutdown_done is True
    # Second call goes through the ``_shutdown_done`` early-return.
    app.shutdown()
    assert Application._instance is None


def test_shutdown_done_flag_set_after_success() -> None:
    """``_shutdown_done`` is True after a successful call;
    ``_shutdown_in_progress`` is False (re-entry guard reset)."""
    app = Application()
    assert getattr(app, "_shutdown_done", False) is False
    assert getattr(app, "_shutdown_in_progress", False) is False
    app.shutdown()
    assert app._shutdown_done is True
    assert app._shutdown_in_progress is False


def test_shutdown_then_save_layout_does_not_double_save() -> None:
    """``_save_layout`` runs exactly once across two ``shutdown()`` calls.

    First call invokes it; the second call short-circuits via
    ``_shutdown_done`` and never reaches the save block.
    """
    app = Application()
    calls = {"n": 0}
    original = app._save_layout

    def _counting_save() -> None:
        calls["n"] += 1
        return original()

    app._save_layout = _counting_save  # type: ignore[method-assign]
    app.shutdown()
    app.shutdown()
    assert calls["n"] == 1


def test_partial_failure_continues_teardown() -> None:
    """Best-effort: a raise inside one teardown block does NOT skip
    later blocks. This replaces the rejected raise-and-retry semantics
    from the Round 1 draft (Round 6 F4).

    We patch ``_save_layout`` to raise and assert:

    * ``shutdown()`` does NOT propagate the exception (best-effort
      swallow per the per-block try/except).
    * ``_shutdown_done`` is True (we attempted every block).
    * Every panel ``destroy()`` ran AND every panel attribute is None,
      despite ``_save_layout`` raising upstream of the panel loop —
      this is the actual leak path the issue #35 fix is preventing.
    * Singletons were reset (``Application._instance is None``) —
      another downstream block past ``_save_layout``.
    """
    app = Application()
    panels = _attach_fake_panels(app)

    def _raising_save() -> None:
        raise RuntimeError("simulated _save_layout failure")

    app._save_layout = _raising_save  # type: ignore[method-assign]
    # Must NOT raise — best-effort swallows the per-block exception.
    app.shutdown()
    # Best-effort completion marker.
    assert app._shutdown_done is True
    # Every downstream panel block ran despite the upstream failure.
    for attr, panel in panels.items():
        assert panel.destroy_calls == 1, (
            f"{attr}.destroy() did not run after _save_layout raised"
        )
        assert getattr(app, attr) is None, (
            f"{attr} was not nulled after _save_layout raised"
        )
    # Singleton reset (the very last block before _shutdown_done = True).
    assert Application._instance is None


def test_recursion_short_circuited() -> None:
    """If a teardown callback re-enters ``shutdown()``, the inner call
    short-circuits via ``_shutdown_in_progress`` (no recursion / no
    stack overflow). The recursive call must return without re-running
    the body.
    """
    app = Application()
    re_entry_count = {"n": 0}

    def _recursive_save() -> None:
        # Inside a teardown block — reentry into shutdown() must be a
        # no-op rather than a recursive run.
        re_entry_count["n"] += 1
        # Inner call: should return immediately due to
        # _shutdown_in_progress, NOT raise, NOT recurse.
        app.shutdown()

    app._save_layout = _recursive_save  # type: ignore[method-assign]
    # Outer call drives the body; inner reentry is short-circuited.
    app.shutdown()
    assert re_entry_count["n"] == 1
    assert app._shutdown_done is True


def test_save_layout_failure_does_not_skip_dockspace() -> None:
    """Round 3 F5 / Round 5 F1 hardening: ``_dockspace = None`` lives in
    its own ``try/finally`` so it executes regardless of whether an
    earlier block raised. Patch ``_save_layout`` to raise and assert
    the dockspace attribute was nulled.

    (DockSpace's C++ destructor must fire before ``omni.ui.shutdown()``
    runs; missing this null was a real failure mode in Phase A's
    Variant B reproduction.)
    """
    app = Application()
    # Place a non-None marker so we can prove the assignment ran.
    app._dockspace = object()  # any non-None sentinel

    def _raising_save() -> None:
        raise RuntimeError("simulated _save_layout failure")

    app._save_layout = _raising_save  # type: ignore[method-assign]
    app.shutdown()
    assert app._dockspace is None
