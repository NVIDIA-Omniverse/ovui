# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 5b — ViewportWidget.destroy() try/finally guarantee.

Issue #35, Step 5b. The plan (Round 3 F4) restructures
``ViewportWidget.destroy()`` so ``super().destroy()`` ALWAYS runs in
the ``finally`` clause, even if ``self._renderer.shutdown()`` raises.
Without this, a renderer-shutdown failure would skip
``super().destroy()`` (which destroys the underlying :class:`ui.Window`
and nulls ``self._window``), leaving the window alive in
:data:`omni.ui.Workspace` until ``Py_FinalizeEx`` — exactly the UAF
window-leak mode this whole fix prevents.

Each test simulates a per-step failure and asserts the UI-window post-condition.
Renderer refusal is the deliberate exception to best-effort swallowing: its
exact throwable propagates after the window closes so the parent keeps the
viewport as the native retry owner.
"""
from __future__ import annotations

import pytest

from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport.viewport_widget import ViewportWidget


def _make_vp() -> ViewportWidget:
    """Build a fresh ``ViewportWidget`` with a stub renderer.

    Mirrors the construction pattern used throughout
    :mod:`tests.test_viewport_widget`.
    """
    return ViewportWidget(services=None, renderer=MockRendererAdapter())


def test_destroy_calls_super_even_if_renderer_shutdown_raises() -> None:
    """Round 3 F4 (the headline case): if ``self._renderer.shutdown()``
    raises, ``super().destroy()`` MUST still run.

    The exact shutdown refusal propagates so the parent can retain ``vp`` as
    retry owner, while ``ManagedWindow.destroy`` still runs in ``finally``.
    """
    vp = _make_vp()
    assert vp._window is not None, "fixture invariant: _window present pre-destroy"

    refusal = RuntimeError("simulated renderer shutdown failure")

    def _raising_shutdown() -> None:
        raise refusal

    vp._renderer.shutdown = _raising_shutdown  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as caught:
        vp.destroy()
    assert caught.value is refusal
    assert vp.unresolved_predecessor is not None

    assert vp._window is None, (
        "Round 3 F4: super().destroy() did not run after "
        "_renderer.shutdown() raised — _window is still alive"
    )


def test_destroy_calls_super_even_if_bus_sub_cancel_raises() -> None:
    """Defence-in-depth: a raise in the very first cleanup block
    (``self._bus_sub.cancel()``) must not block ``super().destroy()``
    either. The per-step try/except + outer try/finally pattern means
    any of the body's blocks can fail without skipping the window
    teardown.
    """
    vp = _make_vp()

    class _RaisingSub:
        def cancel(self) -> None:
            raise RuntimeError("simulated bus_sub cancel failure")

    vp._bus_sub = _RaisingSub()  # type: ignore[assignment]
    vp.destroy()
    assert vp._window is None


def test_destroy_calls_super_even_if_tool_registry_destroy_raises() -> None:
    """Defence-in-depth: a raise in the tool-registry destroy block
    must not block ``super().destroy()``.
    """
    vp = _make_vp()

    class _RaisingToolRegistry:
        def destroy(self) -> None:
            raise RuntimeError("simulated tool_registry destroy failure")

    vp._tool_registry = _RaisingToolRegistry()  # type: ignore[assignment]
    vp.destroy()
    assert vp._window is None


def test_destroy_runs_renderer_shutdown_in_happy_path() -> None:
    """Sanity check that the new try/except wrapping doesn't swallow
    the renderer's shutdown invocation in the normal path. The
    existing :class:`MockRendererAdapter` flips ``_shutdown_called``
    when its ``shutdown()`` is invoked.
    """
    vp = _make_vp()
    renderer = vp._renderer
    assert renderer._shutdown_called is False, (
        "fixture invariant: shutdown not yet called"
    )
    vp.destroy()
    assert renderer._shutdown_called is True, (
        "happy path: renderer.shutdown() must still run"
    )
    # terminal object retains no renderer reference
    assert vp._renderer is None
    assert vp._window is None


def test_destroy_refusal_is_retryable_and_clears_only_after_recovery() -> None:
    """The surface retains the renderer until a later destroy proves exit."""
    vp = _make_vp()
    renderer = vp._renderer
    refusal = RuntimeError("BOOM — exact refusal must surface")

    def _raising_shutdown() -> None:
        raise refusal

    vp._renderer.shutdown = _raising_shutdown  # type: ignore[method-assign]
    with pytest.raises(RuntimeError) as caught:
        vp.destroy()
    assert caught.value is refusal
    assert vp._window is None
    assert vp.unresolved_predecessor is renderer

    renderer.shutdown = lambda: None  # type: ignore[method-assign]
    vp.destroy()
    assert vp.unresolved_predecessor is None
