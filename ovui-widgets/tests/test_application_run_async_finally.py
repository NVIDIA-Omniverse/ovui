# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Application.run_async()'s ``finally:`` block.

Issue #35, Step 5 originally widened ``run_async``'s ``try`` around
``ui.DockSpace`` construction. The application now uses ``ui.MainWindow``
for the menu bar, root docker, and status bar frame, so this test pins the
same structural guarantee around ``self._main_win = ui.MainWindow()``.
Without this, an exception in MainWindow / panel / menu / status-bar
construction would bypass cleanup and leak ovui resources into
``Py_FinalizeEx``.

Why source-inspection, not full execution
-----------------------------------------
Driving ``run_async`` from a unit test would require either ``ui.init()``
plus a real standalone backend, or mocking every ovui constructor on
the body. Both are heavyweight; one segfaults the test process when
``ui.MainWindow()`` runs without an initialised backend, the other
duplicates 100+ lines of ovui surface in patches.

The end-to-end "shutdown actually runs and cleans dialogs" coverage
already lives in :mod:`tests.test_application_shutdown_integration`
which uses a real ``Application``, calls real ``shutdown()``, and
asserts dialog teardown. THIS file's job is to pin the *structural*
contract on ``run_async``'s body so a refactor that narrows the try
or removes the shutdown call gets caught at unit-test time.

The structural contract:

1. ``run_async`` is wrapped in ``try:`` ... ``finally:``
2. ``self._main_win = ui.MainWindow`` lives INSIDE the try
3. ``self._restore_layout()`` lives INSIDE the try (Round 1 F2)
4. The frame loop ``while self._running:`` lives INSIDE the try
5. ``self.shutdown()`` is called from the finally clause
6. ``ErrorReporter._clear_status_bar()`` is also in the finally
7. The shutdown call is wrapped in its own try/except so a raise from
   ``_clear_status_bar`` does NOT skip ``shutdown``, and vice versa
"""
from __future__ import annotations

import ast
import inspect

import pytest

from ovui_widgets.app.application import Application


@pytest.fixture(scope="module")
def _run_async_ast() -> ast.AsyncFunctionDef:
    """Parse :meth:`Application.run_async` once and return its AST node."""
    source = inspect.getsource(Application.run_async)
    # Dedent so ``ast.parse`` accepts the method body in isolation.
    source = inspect.cleandoc("\n" + source) if False else _dedent(source)
    module = ast.parse(source)
    fn = module.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef), (
        f"Expected AsyncFunctionDef, got {type(fn).__name__}"
    )
    assert fn.name == "run_async"
    return fn


def _dedent(source: str) -> str:
    """Strip the leading 4-space indent from a method source dump."""
    import textwrap
    return textwrap.dedent(source)


def _is_prelude_stmt(stmt: ast.stmt) -> bool:
    """True iff ``stmt`` is part of run_async's allowed pre-try
    "prelude" — the docstring and the import statements at the top of
    the body. Any other statement (assignment, expression, call, etc.)
    is considered "executable" and would, if placed before the outer
    try, bypass the shutdown finally.
    """
    # Module/method docstring shape: a bare Expr containing a string
    # constant. Only the first such Expr is a docstring; later string
    # expressions (e.g., a "..." line) wouldn't be prelude.
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return isinstance(stmt.value.value, str)
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return True
    return False


_OVUI_CONSTRUCTOR_NAMES = frozenset({
    "DockSpace",
    "MainWindow",
    "Window",
    "MenuBar",
    "Frame",
    "VStack",
    "StageWindow",
    "PropertyWidget",
    "ViewportWidget",
    "ContentBrowserWindow",
    "LayerWindow",
    "StatusBar",
})


def _ovui_call_in_node(node: ast.AST) -> str | None:
    """Return a short description if ``node`` contains a real
    :class:`ast.Call` whose callee resembles an ovui constructor
    (e.g. ``ui.MainWindow(...)``, ``ui.Window(...)``, ``StageWindow(...)``);
    otherwise None.

    Walks the AST and inspects only :class:`ast.Call` nodes — substring
    scanning would false-positive on docstrings or comments mentioning
    these symbols (e.g., the run_async docstring itself talks about
    ``ui.MainWindow``). Used by post-Step-5 Codex F1 to catch a stray
    ovui resource construction placed BEFORE run_async's outer try.
    """
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        called = child.func
        # Attribute call: ``ui.MainWindow(...)``  → check ``.attr``.
        if isinstance(called, ast.Attribute):
            if called.attr in _OVUI_CONSTRUCTOR_NAMES:
                return f"{ast.unparse(called)}(...)"
        # Bare name call: ``StageWindow(...)``  → check ``.id``.
        if isinstance(called, ast.Name):
            if called.id in _OVUI_CONSTRUCTOR_NAMES:
                return f"{called.id}(...)"
    return None


def _find_outer_try(fn: ast.AsyncFunctionDef) -> ast.Try:
    """Find run_async's outer ``try:`` block AND assert it is the
    first executable statement after the prelude (docstring + imports).

    Codex Round (post-Step-5) F1: a stray ``ui.Window(...)`` placed
    BEFORE the outer try would bypass shutdown, even with a perfectly
    well-formed try below it. The original implementation only
    asserted "exactly one top-level Try"; this stricter version
    asserts:

    1. There is exactly one top-level Try.
    2. Every statement before it is a prelude statement (docstring
       or import).
    3. As a defence-in-depth, no prelude statement contains an ovui
       constructor call shape (a doubly-paranoid check — imports
       and the docstring shouldn't anyway).
    """
    outer_tries: list[tuple[int, ast.Try]] = [
        (i, stmt) for i, stmt in enumerate(fn.body) if isinstance(stmt, ast.Try)
    ]
    assert len(outer_tries) == 1, (
        f"Expected exactly one outer try in run_async, found "
        f"{len(outer_tries)}"
    )
    try_index, outer = outer_tries[0]

    # Every statement before the outer try must be prelude only.
    pre_try = fn.body[:try_index]
    non_prelude = [s for s in pre_try if not _is_prelude_stmt(s)]
    assert not non_prelude, (
        "Codex Round (post-Step-5) F1: outer try must be the FIRST "
        "executable statement after the prelude (docstring + imports). "
        "Found these non-prelude statements before the try:\n"
        + "\n".join(
            f"  line {getattr(s, 'lineno', '?')}: {ast.unparse(s)[:100]}"
            for s in non_prelude
        )
    )

    # Defence-in-depth: even if a future refactor relocates a
    # docstring/import into a shape we mis-classify as prelude,
    # surface any ovui call that lives before the try.
    for s in pre_try:
        suspicious = _ovui_call_in_node(s)
        if suspicious is not None:
            pytest.fail(
                "Codex Round (post-Step-5) F1: an ovui-call shape "
                f"({suspicious!r}) appears BEFORE run_async's outer "
                "try. That construction would bypass the shutdown "
                "finally if it raised. Move it inside the try."
            )

    return outer


def _node_text_contains(node: ast.AST, needle: str) -> bool:
    """True iff ``needle`` (an exact substring) appears in the source
    fragment for ``node``.
    """
    return needle in ast.unparse(node)


# ---------------------------------------------------------------------------
# Structural contract tests.
# ---------------------------------------------------------------------------


def test_run_async_has_outer_try_finally(_run_async_ast: ast.AsyncFunctionDef) -> None:
    """``run_async``'s body has exactly one outer try, with a non-empty
    ``finally`` clause."""
    outer = _find_outer_try(_run_async_ast)
    assert outer.finalbody, (
        "run_async's outer try must have a finally clause that runs "
        "the shutdown teardown"
    )


def test_mainwindow_construction_inside_try(_run_async_ast: ast.AsyncFunctionDef) -> None:
    """``self._main_win = ui.MainWindow`` MUST be inside
    the outer try block, otherwise a raise from MainWindow construction
    bypasses ``shutdown()``.
    """
    outer = _find_outer_try(_run_async_ast)
    assert _node_text_contains(outer, "self._main_win = ui.MainWindow"), (
        "MainWindow construction must live inside run_async's "
        "outer try block"
    )


def test_restore_layout_inside_try(_run_async_ast: ast.AsyncFunctionDef) -> None:
    """Round 1 F2: ``self._restore_layout()`` MUST be inside the outer
    try block, otherwise a raise from layout restore bypasses
    ``shutdown()``.
    """
    outer = _find_outer_try(_run_async_ast)
    assert _node_text_contains(outer, "self._restore_layout()"), (
        "Round 1 F2: _restore_layout() must live inside run_async's "
        "outer try block"
    )


def test_frame_loop_inside_try(_run_async_ast: ast.AsyncFunctionDef) -> None:
    """The ``while self._running:`` frame loop lives INSIDE the outer
    try, so a normal exit (loop ending naturally) drives the finally."""
    outer = _find_outer_try(_run_async_ast)
    src = ast.unparse(outer)
    assert "while self._running" in src, (
        "Frame loop must be inside run_async's outer try block"
    )


def test_finally_calls_shutdown(_run_async_ast: ast.AsyncFunctionDef) -> None:
    """The outer ``finally`` MUST call ``self.shutdown()``. Without
    this, ``Application.shutdown()`` never runs on the normal exit
    path — the headline bug of issue #35.
    """
    outer = _find_outer_try(_run_async_ast)
    finally_src = "\n".join(ast.unparse(stmt) for stmt in outer.finalbody)
    assert "self.shutdown()" in finally_src, (
        "issue #35 headline: finally MUST call self.shutdown(); current "
        f"finally body:\n{finally_src}"
    )


def test_finally_calls_clear_status_bar(_run_async_ast: ast.AsyncFunctionDef) -> None:
    """The finally also clears ErrorReporter's status-bar reference
    (preserved from the original narrow try) so ErrorReporter doesn't
    keep dangling references through the next test/run."""
    outer = _find_outer_try(_run_async_ast)
    finally_src = "\n".join(ast.unparse(stmt) for stmt in outer.finalbody)
    assert "_clear_status_bar()" in finally_src, (
        "finally must also call ErrorReporter._clear_status_bar()"
    )


def test_finally_isolates_clear_and_shutdown(
    _run_async_ast: ast.AsyncFunctionDef,
) -> None:
    """The finally has TWO **distinct** inner try/excepts — one for
    ``_clear_status_bar()`` and one for ``self.shutdown()`` — so a
    raise in either does NOT skip the other.

    Codex Round (post-Step-5) F2: the original test asserted
    ``len(inner_tries) >= 2`` and ``"_clear_status_bar()" in body OR
    "self.shutdown()" in body``, which would pass if BOTH calls were
    in a single inner try (with a sibling unrelated try satisfying the
    count). That would let a ``_clear_status_bar()`` failure skip
    ``shutdown()``. The fix: find the inner try whose **body** mentions
    ``_clear_status_bar()`` and the inner try whose **body** mentions
    ``self.shutdown()``, and assert they are NOT the same AST node.
    """
    outer = _find_outer_try(_run_async_ast)
    inner_tries = [stmt for stmt in outer.finalbody if isinstance(stmt, ast.Try)]
    assert len(inner_tries) >= 2, (
        f"finally must have at least 2 inner try blocks (one each for "
        f"_clear_status_bar() and self.shutdown()); found {len(inner_tries)}"
    )

    def _try_body_contains(t: ast.Try, needle: str) -> bool:
        """True iff ``needle`` appears in the Try's body (NOT its
        handlers / finalbody — a shared try with both calls in the
        body is what we're guarding against)."""
        body_src = "\n".join(ast.unparse(s) for s in t.body)
        return needle in body_src

    clear_try = next(
        (t for t in inner_tries if _try_body_contains(t, "_clear_status_bar()")),
        None,
    )
    shutdown_try = next(
        (t for t in inner_tries if _try_body_contains(t, "self.shutdown()")),
        None,
    )

    assert clear_try is not None, (
        "no inner try wraps _clear_status_bar() in its body"
    )
    assert shutdown_try is not None, (
        "no inner try wraps self.shutdown() in its body"
    )
    assert clear_try is not shutdown_try, (
        "Codex Round (post-Step-5) F2: _clear_status_bar() and "
        "self.shutdown() are in the SAME inner try block — a raise "
        "in _clear_status_bar() would skip shutdown(). They must "
        "live in two distinct try/except blocks."
    )


def test_shutdown_failure_is_recorded_for_public_run_to_raise(
    _run_async_ast: ast.AsyncFunctionDef,
) -> None:
    """A BORROW detach failure must not be reduced to a log-only success."""

    outer = _find_outer_try(_run_async_ast)
    finally_src = "\n".join(ast.unparse(stmt) for stmt in outer.finalbody)
    assert "self._run_exception = shutdown_exc" in finally_src
    assert "if self._run_exception is None" in finally_src


def test_public_run_requires_completed_shutdown_before_native_fast_exit() -> None:
    """The process-fast-exit path is legal only after owner teardown succeeds."""

    source = _dedent(inspect.getsource(Application.run))
    assert "if not getattr(self, \"_shutdown_done\", False)" in source
    assert source.index("_shutdown_done") < source.index(
        "_fast_exit_after_successful_native_shutdown()"
    )


def test_shutdown_runs_through_full_call_chain() -> None:
    """End-to-end smoke test using the public Application surface
    (no run_async loop driven): construct an Application, manually
    call ``shutdown()``, assert ``_shutdown_done`` is True.

    This is a sanity check that the Step 1 idempotent shutdown still
    works after the Step 5 source restructure — i.e. the AST-level
    structural changes above didn't accidentally break the actual
    shutdown call.
    """
    from ovui_widgets.common.selection import SelectionBus
    Application._instance = None
    SelectionBus._instance = None
    try:
        app = Application()
        app.shutdown()
        assert app._shutdown_done is True
        assert Application._instance is None
    finally:
        Application._instance = None
        SelectionBus._instance = None
