# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 7 — OS X-button polling via lazy ``_ui`` import.

Issue #35, Step 7 (Codex Round 1 F9 + F10).

The plan adds a module-level :func:`ovui_widgets.app.application._should_close`
helper that lazily imports :mod:`omni.ui._ui` and reads the private
``_standalone_should_close()`` function. The helper is layered with
three independent guards (ImportError → getattr-None → call try/except)
so any link in the chain failing degrades to ``return False`` instead
of crashing :meth:`Application.run_async`'s loop.

Round 1 F10: NO SIGTERM-based verification. Test parts:

1. Direct unit tests on the :func:`_should_close` helper, simulating
   the X-button by replacing ``sys.modules["omni.ui._ui"]`` with a
   stub whose ``_standalone_should_close`` flips True after N polls.
   Also verify the three failure paths (no module, no symbol,
   call raises) correctly return False rather than propagating.

2. AST-level structural test that ``run_async``'s loop condition
   actually calls ``_should_close()`` — so a refactor that removes
   the call gets caught at unit-test time.

3. Manual interactive validation (NOT a unit test — recorded in PR
   description) — run ``python -m ovui_widgets.app cube.usda`` interactively,
   click the OS X button, verify ``rc=0``. Not automated because
   there is no programmatic way to inject a real GLFW close event
   from outside the process.
"""
from __future__ import annotations

import ast
import inspect
import sys
import types

from ovui_widgets.app.application import Application, _should_close

# ----------------------------------------------------------------------
# Direct unit tests on the _should_close helper.
# ----------------------------------------------------------------------


def test_should_close_returns_false_when_ui_module_missing(monkeypatch) -> None:
    """If :mod:`omni.ui._ui` is not importable (ImportError), the
    helper must return False, NOT propagate the import error.
    """
    # Force ImportError by injecting a sentinel that raises on access.
    # We simulate the lazy import by removing the cached module and
    # making the import path fail.
    monkeypatch.delitem(sys.modules, "omni.ui._ui", raising=False)

    # Replace the parent package's _ui attribute with something that
    # forces re-import — and have that re-import fail. A simple way:
    # monkeypatch the import system via a finder that rejects _ui.
    import importlib

    real_import_module = importlib.import_module

    def _failing_import(name: str, *args, **kwargs):
        if name == "omni.ui._ui":
            raise ImportError(f"simulated: {name} unavailable")
        return real_import_module(name, *args, **kwargs)

    # The helper does ``from omni.ui import _ui``, not
    # ``importlib.import_module("omni.ui._ui")``, so monkeypatching
    # importlib doesn't catch it. The cleanest way is to patch
    # ``omni.ui._ui`` to None via a sentinel module that lacks the
    # attribute. Use the "kind" branch instead:
    fake_ui_pkg = types.ModuleType("omni.ui")
    # Deliberately omit the ``_ui`` attribute — ``from omni.ui import _ui``
    # raises ImportError when the package lacks the submodule and it's
    # not in sys.modules.
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui_pkg)
    monkeypatch.delitem(sys.modules, "omni.ui._ui", raising=False)

    assert _should_close() is False, (
        "Round 1 F9 / Round 7 F2: ImportError on the lazy _ui import "
        "must degrade to False, not propagate"
    )


def _patch_ui_submodule(monkeypatch, fake) -> None:
    """Helper: replace ``omni.ui._ui`` so the lazy
    ``from omni.ui import _ui`` inside :func:`_should_close` sees
    ``fake`` instead of the real submodule.

    The lazy import resolves ``_ui`` via ``getattr(omni.ui, "_ui")``
    on the cached parent package (Python's ``from X import Y``
    semantics), so a ``sys.modules`` swap alone is not enough — we
    also patch the attribute on the parent package.
    """
    import omni.ui
    monkeypatch.setattr(omni.ui, "_ui", fake, raising=False)
    monkeypatch.setitem(sys.modules, "omni.ui._ui", fake)


def test_should_close_returns_false_when_function_missing(monkeypatch) -> None:
    """If :mod:`omni.ui._ui` exists but doesn't expose
    ``_standalone_should_close`` (e.g. a future ovui release that
    renames the symbol), the helper must return False.
    """
    fake_ui = types.SimpleNamespace()  # no _standalone_should_close
    _patch_ui_submodule(monkeypatch, fake_ui)
    assert _should_close() is False


def test_should_close_returns_false_when_function_raises(monkeypatch) -> None:
    """If ``_standalone_should_close()`` itself raises (e.g. backend
    partially torn down), the helper must return False rather than
    propagate to ``run_async``'s while-condition.
    """
    def _boom():
        raise RuntimeError("simulated backend mid-teardown")

    fake_ui = types.SimpleNamespace(_standalone_should_close=_boom)
    _patch_ui_submodule(monkeypatch, fake_ui)
    assert _should_close() is False


def test_should_close_returns_true_when_fake_returns_true(monkeypatch) -> None:
    """The headline contract: when ``_standalone_should_close()``
    returns truthy, :func:`_should_close` returns True. This is what
    drives :meth:`Application.run_async`'s loop to exit when the user
    clicks the OS X button.
    """
    fake_ui = types.SimpleNamespace(_standalone_should_close=lambda: True)
    _patch_ui_submodule(monkeypatch, fake_ui)
    assert _should_close() is True


def test_should_close_returns_false_when_fake_returns_false(monkeypatch) -> None:
    """In the steady state (window is open, X not clicked),
    ``_standalone_should_close()`` returns False — :func:`_should_close`
    must agree so the loop keeps running.
    """
    fake_ui = types.SimpleNamespace(_standalone_should_close=lambda: False)
    _patch_ui_submodule(monkeypatch, fake_ui)
    assert _should_close() is False


def test_should_close_coerces_truthy_non_bool(monkeypatch) -> None:
    """The helper wraps the call in ``bool(...)``, so any truthy
    value returned by ``_standalone_should_close`` is normalised to
    True (and any falsy to False).

    Catches a regression that would let, e.g., an int leak into
    the loop condition.
    """
    fake_ui = types.SimpleNamespace(_standalone_should_close=lambda: 1)
    _patch_ui_submodule(monkeypatch, fake_ui)
    assert _should_close() is True

    fake_ui = types.SimpleNamespace(_standalone_should_close=lambda: 0)
    _patch_ui_submodule(monkeypatch, fake_ui)
    assert _should_close() is False


def test_should_close_simulates_x_button_after_n_polls(monkeypatch) -> None:
    """Plan's literal X-button simulation: a fake that flips True after
    N polls models a user clicking the X button mid-frame. Asserts the
    helper observes the flip on call N.
    """
    state = {"calls": 0}

    def fake() -> bool:
        state["calls"] += 1
        return state["calls"] >= 5

    fake_ui = types.SimpleNamespace(_standalone_should_close=fake)
    _patch_ui_submodule(monkeypatch, fake_ui)

    # First four polls: window is open.
    for _ in range(4):
        assert _should_close() is False
    # Fifth poll: simulated X-button click — helper observes the flip.
    assert _should_close() is True


# ----------------------------------------------------------------------
# AST-level structural test: run_async's while-condition uses _should_close.
# ----------------------------------------------------------------------


def test_run_async_loop_condition_includes_should_close() -> None:
    """The Step-5 / Step-7 ``run_async`` loop condition MUST be
    exactly:

        while self._running and not _should_close():

    Codex Round 1 F9 + post-Step-7 review: substring matching on
    ``ast.unparse(...)`` is too permissive — it would pass for
    e.g. ``while _should_close() and self._running:`` (swapped order)
    or ``while self._running or _should_close():`` (wrong operator).
    Pin the EXACT AST shape so a refactor that perturbs operands /
    operator / order regresses this test.

    Expected ``ast.While.test`` shape:

      BoolOp(op=And, values=[
          Attribute(value=Name("self"), attr="_running"),
          UnaryOp(op=Not, operand=Call(func=Name("_should_close"), args=[])),
      ])

    The structural AST checks below pin operand types, operand IDs,
    operand attribute names, the boolean operator, the unary
    operator, and that ``_should_close`` is called with no arguments.
    No textual equality check on ``ast.unparse(...)`` because that
    string varies by CPython version (e.g. parenthesisation of the
    ``not`` operand) — the AST shape is the precise contract.
    """
    import textwrap

    source = inspect.getsource(Application.run_async)
    fn = ast.parse(textwrap.dedent(source)).body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)

    while_nodes = [
        n for n in ast.walk(fn) if isinstance(n, ast.While)
    ]
    assert len(while_nodes) == 1, (
        f"Expected exactly one While loop in run_async, found "
        f"{len(while_nodes)}"
    )

    test = while_nodes[0].test
    # Top of the expression: BoolOp(And, [left, right])
    assert isinstance(test, ast.BoolOp), (
        f"loop condition must be a BoolOp; got {type(test).__name__}"
    )
    assert isinstance(test.op, ast.And), (
        f"loop condition operator must be 'and'; got "
        f"{type(test.op).__name__}"
    )
    assert len(test.values) == 2, (
        f"loop condition must have exactly two operands; got "
        f"{len(test.values)}: {[ast.unparse(v) for v in test.values]}"
    )

    left, right = test.values

    # Left operand: self._running  (Attribute(Name('self'), '_running'))
    assert isinstance(left, ast.Attribute), (
        f"loop condition left operand must be an Attribute; got "
        f"{type(left).__name__} ({ast.unparse(left)!r})"
    )
    assert (
        isinstance(left.value, ast.Name)
        and left.value.id == "self"
        and left.attr == "_running"
    ), (
        f"loop condition left operand must be ``self._running``; got "
        f"{ast.unparse(left)!r}"
    )

    # Right operand: not _should_close()
    #   UnaryOp(Not, Call(Name('_should_close'), [], []))
    assert isinstance(right, ast.UnaryOp), (
        f"loop condition right operand must be a UnaryOp; got "
        f"{type(right).__name__} ({ast.unparse(right)!r})"
    )
    assert isinstance(right.op, ast.Not), (
        f"loop condition right operand must use 'not'; got "
        f"{type(right.op).__name__}"
    )
    inner = right.operand
    assert isinstance(inner, ast.Call), (
        f"loop condition right operand must wrap a Call; got "
        f"{type(inner).__name__} ({ast.unparse(inner)!r})"
    )
    assert (
        isinstance(inner.func, ast.Name)
        and inner.func.id == "_should_close"
    ), (
        f"loop condition right operand must call ``_should_close``; "
        f"got call to {ast.unparse(inner.func)!r}"
    )
    assert inner.args == [] and inner.keywords == [], (
        f"_should_close() must be called with no arguments; got "
        f"{ast.unparse(inner)!r}"
    )
