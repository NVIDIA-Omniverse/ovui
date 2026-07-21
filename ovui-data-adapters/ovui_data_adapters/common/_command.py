# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Abstract command contract shared by command-capable services/adapters.

Part of ``ovui-data-adapters-common``; this module is stdlib-only at runtime.

This module hosts the canonical ``Command`` ABC because adapter protocols and
OpenUSD command implementations need the type without depending on the
higher-level services distribution. ``ovui_data_adapters.services.undo`` and
``ovui_widgets.common.undo`` re-export the same class object so all of these
import paths resolve to the identical class:

``from ovui_data_adapters.services.undo import Command``,
``from ovui_widgets.common.undo import Command`` and
``from ovui_data_adapters.common import Command`` resolve to the identical
class.
"""

from abc import ABC, abstractmethod
import contextlib
import contextvars
from typing import Any


class Command(ABC):
    """Base class for undoable commands."""

    # Subclasses that represent one-way operations (save, reload, etc.)
    # flip this to ``True`` so :meth:`UndoManager.push` executes the
    # command but does not enqueue it on the undo stack — instead the
    # redo stack is cleared. This keeps file-I/O commands in the
    # command pipeline (uniform error reporting, selection snapshot,
    # dialog guards) without producing a user-confusing "Undo Save"
    # entry. See LAYERS-PLAN Step 33.
    non_undoable: bool = False

    @abstractmethod
    def do(self) -> None:
        """Execute the command."""

    @abstractmethod
    def undo(self) -> None:
        """Reverse the command."""

    def redo(self) -> None:
        """Re-execute. Default delegates to do()."""
        self.do()


class _CommandEdge:
    """Identity token for one executing command edge, with liveness."""

    __slots__ = ("active",)

    def __init__(self) -> None:
        self.active = True


_COMMAND_EDGE_STACK: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "ovui_command_edge_stack", default=()
)


@contextlib.contextmanager
def command_edge() -> Any:
    """Scope one command-service execution edge (do/undo/redo).

    The undo manager enters this scope around every command edge it
    executes. Provider streams consult :func:`in_command_edge` to decide
    whether a deferred interrupt needs the history-consistent mark at
    all: outside an executing edge there is no pending history entry to
    protect, so the interrupt delivered to the caller stays unmarked —
    a public direct adapter write (caller-managed undo) can never leak
    internal per-edge state.

    Edge membership is OWNED, not inherited: the context variable holds
    edge tokens that are deactivated when their edge finishes. An
    asynchronous child (task/callback) created inside an edge inherits a
    context SNAPSHOT holding the token object — and because command
    edges execute synchronously, that child can only run after the edge
    deactivated its token (or on another thread, whose fresh context has
    no token at all). Work scheduled from inside an edge therefore never
    counts as inside it once the edge has ended, while the synchronous
    call chain (including re-entrant observers) always sees the live
    stack of the same context.
    """
    edge = _CommandEdge()
    token = _COMMAND_EDGE_STACK.set(_COMMAND_EDGE_STACK.get() + (edge,))
    try:
        yield
    finally:
        edge.active = False
        _COMMAND_EDGE_STACK.reset(token)


def in_command_edge() -> bool:
    """True only while the innermost owning command edge is still pending."""
    stack = _COMMAND_EDGE_STACK.get()
    return bool(stack) and stack[-1].active


def mark_history_consistent(exc: BaseException) -> None:
    """Tag one interrupt as raised AFTER its command edge fully applied."""
    exc._ovui_history_consistent = True  # type: ignore[attr-defined]


def is_history_consistent(exc: BaseException) -> bool:
    """True for a marked interrupt-class failure (never ordinary Exceptions)."""
    return not isinstance(exc, Exception) and bool(
        getattr(exc, "_ovui_history_consistent", False)
    )


def clear_history_consistent(exc: BaseException) -> None:
    """Consume the mark before an exception escapes the command machinery.

    The mark is an internal protocol between the provider stream and the
    command service. It must never linger on an exception object handed
    to application code: application code may legitimately re-raise the
    same object later from a command that failed before applying
    anything, and a stale mark would then record false history.
    """
    try:
        del exc._ovui_history_consistent  # type: ignore[attr-defined]
    except AttributeError:
        pass


def interrupt_copy(original: BaseException) -> BaseException:
    """Return a FRESH same-type interrupt equivalent to ``original``.

    Internal state is never written onto the caller's (possibly shared
    and reusable) exception instance — a fresh instance is delivered
    instead, with the original attached as ``__cause__`` by the raising
    ``raise ... from original`` site. If the type cannot be re-created,
    the original is used as a last resort.
    """
    try:
        fresh = type(original)(*getattr(original, "args", ()))
    except Exception:
        fresh = original
    if fresh is not original:
        add_note = getattr(fresh, "add_note", None)
        if callable(add_note):
            for note in getattr(original, "__notes__", ()) or ():
                add_note(note)
    return fresh


def history_consistent_interrupt(original: BaseException) -> BaseException:
    """Return a fresh interrupt copy carrying the history-consistent mark.

    The mark is scoped to the single command edge being finalized; see
    :func:`interrupt_copy` for why the caller's instance is never tagged.
    """
    fresh = interrupt_copy(original)
    mark_history_consistent(fresh)
    return fresh


class CommandCancelled(Exception):
    """Raised from :meth:`Command.do` to abort a push without mutating stacks.

    Part of the adapter-common command contract (like :class:`Command`
    itself) so adapter packages can raise/catch it without depending on the
    higher-level services distribution: commands use it to short-circuit a
    push when a pre-do guard decides the operation should not proceed
    (e.g. a genuine outcome no-op). ``UndoManager.push`` catches it,
    returns silently, and does not clear the redo stack — a cancelled
    command leaves history untouched, matching the "nothing happened"
    model. ``ovui_data_adapters.services.undo`` re-exports this exact
    class object.
    """
