# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Whether the application shows a layer as modified.

OpenUSD marks a layer dirty at its first change and clears the mark only when
the layer is saved or read again from its file. An edit that the user cancels
(Escape in a number field) puts back the exact specs that it changed, but
OpenUSD keeps the layer dirty. A reload would clear the mark, but it reads the
whole file and rebuilds the whole stage, which stops the window for as long as
the layer is large.

So the property adapter records here that a layer that had no unsaved change
when an edit began has that content again after the edit was undone. The
application then shows the layer as not modified (Save All and the modified
dot of the Layers window). The record ends at the next change of the layer.

The modified state that the application shows uses this record. So does the
OpenUSD renderer adapter when it chooses to open a root layer by its path or
through a snapshot: a snapshot gets a new path at each load, so the renderer
would read the same file again at each open. Other code that reads
``layer.dirty`` itself still treats the layer as possibly changed; that costs
at most extra work, for example one more copy of the layer, and never loses
data.
"""

from __future__ import annotations

import contextlib
import threading
import weakref
from typing import Any, Callable, Iterable, Iterator, List, Set

from pxr import Sdf, Tf, Usd

_LOCK = threading.Lock()
# Identifiers of the layers that have again their clean content. Only the
# identifier is kept, so a closed layer is not held in memory. A layer that
# opens later with the same identifier is clean, and its first change ends
# the record.
_CLEAN_AGAIN: Set[str] = set()
# Open watches of edits; weak, so a dropped edit stops its watch.
_WATCHES: "weakref.WeakSet[LayerChangeWatch]" = weakref.WeakSet()
# Methods told the identifier of a layer whose shown modified state changed
# with no dirtiness notice of OpenUSD; weak, so a dropped listener stops by
# itself.
_LISTENERS: List["weakref.WeakMethod"] = []
_NOTICE_KEY = None


def is_layer_modified(layer: Any) -> bool:
    """True when ``layer`` has a change that is not saved."""
    if not layer.dirty:
        return False
    with _LOCK:
        return layer.identifier not in _CLEAN_AGAIN


def mark_clean_again(layer: Any) -> None:
    """Record that ``layer`` has again the content it had when it was clean.

    The caller must know this: the layer had no unsaved change when the edit
    began, the edit put back the exact specs it changed, and nothing else
    changed the layer in between (see :class:`LayerChangeWatch`).
    """
    _listen()
    with _LOCK:
        _CLEAN_AGAIN.add(layer.identifier)
    _tell_listeners([layer.identifier])


def add_modified_state_listener(method: Callable[[str], None]) -> None:
    """Call the bound ``method`` with the identifier of a layer whose shown
    modified state changed: it is clean again, or the record of that ended at
    a change. OpenUSD sends no dirtiness notice for either, and a listener of
    the change notice can run before this module, so a view of the modified
    state must read it again when it is told."""
    with _LOCK:
        _LISTENERS.append(weakref.WeakMethod(method))


def remove_modified_state_listener(method: Callable[[str], None]) -> None:
    with _LOCK:
        _LISTENERS[:] = [
            ref for ref in _LISTENERS if ref() is not None and ref() != method
        ]


class LayerChangeWatch:
    """Finds a change of one layer that its owner did not make.

    The owner makes each of its writes inside :meth:`own_change`. A change
    notice for the layer outside an own write sets :attr:`changed_by_others`.

    A listener of the stage can write before an own write returns, so inside
    an own write the change notices of ``stage`` are read path by path. Only
    ``own_properties`` and ``own_prims`` count as the owner's change. Any
    other changed path sets :attr:`changed_by_others`, also when it is in
    another layer, because a notice of the stage does not tell the layer.
    ``own_prims`` are the prims of the owner's properties and their parents:
    a write creates their prim specs when the layer has none. A listener can
    change those prim specs too, so the owner must still compare them with
    their state before the edit.
    """

    def __init__(
        self,
        layer: Any,
        stage: Any,
        own_properties: Iterable[Any],
        own_prims: Iterable[Any] = (),
    ) -> None:
        self.identifier = layer.identifier
        self.changed_by_others = False
        self._own_writes = 0
        self._own_paths = {str(path) for path in own_properties}
        self._own_paths.update(str(path) for path in own_prims)
        _listen()
        with _LOCK:
            _WATCHES.add(self)
        this = weakref.ref(self)

        def on_stage_change(notice: Any, _sender: Any) -> None:
            watch = this()
            if watch is not None:
                watch._on_stage_change(notice)

        # OpenUSD keeps only a weak reference to a Python callback, so the
        # watch keeps it. A watch that is dropped without close() still ends
        # its registration.
        self._stage_callback = on_stage_change
        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, on_stage_change, stage)
        self._end_registration = weakref.finalize(self, key.Revoke)

    @contextlib.contextmanager
    def own_change(self) -> Iterator[None]:
        self._own_writes += 1
        try:
            yield
        finally:
            self._own_writes -= 1

    def close(self) -> None:
        with _LOCK:
            _WATCHES.discard(self)
        self._end_registration()

    def _on_change(self) -> None:
        if self._own_writes == 0:
            self.changed_by_others = True

    def _on_stage_change(self, notice: Any) -> None:
        if self._own_writes == 0 or self.changed_by_others:
            return
        for path in (*notice.GetResyncedPaths(), *notice.GetChangedInfoOnlyPaths()):
            if str(path) not in self._own_paths:
                self.changed_by_others = True
                return


def _listen() -> None:
    global _NOTICE_KEY
    with _LOCK:
        if _NOTICE_KEY is None:
            _NOTICE_KEY = Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayersDidChangeSentPerLayer, _on_layers_did_change
            )


def _tell_listeners(identifiers: List[str]) -> None:
    with _LOCK:
        _LISTENERS[:] = [ref for ref in _LISTENERS if ref() is not None]
        listeners = [ref() for ref in _LISTENERS]
    for listener in listeners:
        if listener is not None:
            for identifier in identifiers:
                listener(identifier)


def _on_layers_did_change(notice: Any, _sender: Any) -> None:
    changed = {layer.identifier for layer in notice.GetLayers()}
    with _LOCK:
        ended = [i for i in changed if i in _CLEAN_AGAIN]
        _CLEAN_AGAIN.difference_update(ended)
        watches = [watch for watch in _WATCHES if watch.identifier in changed]
    for watch in watches:
        watch._on_change()
    if ended:
        _tell_listeners(ended)
