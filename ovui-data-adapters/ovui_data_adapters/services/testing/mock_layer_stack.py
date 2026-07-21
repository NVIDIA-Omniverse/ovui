# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""In-memory :class:`LayerStackAdapter` for headless tests.

LAYERS-PLAN Step 2 landed the read-only surface; Step 6 added the
mutation surface the adapter shares with the USD-backed adapter.

Every later step (models, commands, UI) depends on this mock to run without
``pxr``. The mock mirrors the shape of the USD adapter closely enough that
tests written against it will keep passing once the real adapter lands.

Constraint G2 — Kit-free: imports only stdlib plus
``ovui_data_adapters.services.settings.Subscription`` and the layer-adapter ABC
family from :mod:`ovui_data_adapters.common`.

Subscription semantics match :class:`ovui_data_adapters.services.selection.SelectionBus`
exactly — a plain subscriber list plus ``_remove_subscriber`` to satisfy the
shared :class:`ovui_data_adapters.services.settings.Subscription` cancel contract.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from ovui_data_adapters.common import (
    LayerEvent,
    LayerEventType,
    LayerHandle,
    LayerSnapshot,
    LayerStackAdapter,
    PrimSpecDescriptor,
    PrimSpecifier,
)

from ovui_data_adapters.services.settings import Subscription

# Stable identifiers for the two layers every mock stack is born with. Using
# ``@…@`` brackets matches the sentinel convention used by anonymous layers
# in USD (``anon:…``) — distinctive enough that tests cannot accidentally
# collide with a file path.
ROOT_LAYER_IDENTIFIER = "@root@"
SESSION_LAYER_IDENTIFIER = "@session@"


@dataclass
class MockLayer:
    """Plain-data record backing one layer in :class:`MockLayerStackAdapter`.

    Field layout mirrors the read-only surface on :class:`LayerStackAdapter`
    so the adapter methods are one-line dict lookups.
    """

    identifier: str
    display_name: str = ""
    sublayer_identifiers: List[str] = field(default_factory=list)
    dirty: bool = False
    muted: bool = False
    locked: bool = False
    read_only: bool = False
    anonymous: bool = False
    missing: bool = False
    owner: str = ""
    info: Dict[str, str] = field(default_factory=dict)
    # In-memory prim-spec store: path → opaque USDA-style token. The mock
    # does not speak real USD, so ``export_prim_spec`` / ``import_prim_spec``
    # just round-trip the token that ``set_prim_spec`` (or tests) placed
    # here. Step 31a's :class:`RemovePrimSpecsCommand` undo relies on the
    # round-trip producing the same bytes back.
    prim_specs: Dict[str, str] = field(default_factory=dict)
    # Parallel descriptor store used by Step 47's ``get_prim_specs`` /
    # ``has_prim_spec``. Separate from :attr:`prim_specs` so the pre-Step-47
    # export/import round-trip keeps working unchanged. Populated by tests
    # via :meth:`MockLayerStackAdapter.set_prim_spec_descriptor` (or
    # indirectly via the Step 48 model once it lands).
    prim_spec_descriptors: Dict[str, PrimSpecDescriptor] = field(default_factory=dict)


class MockLayerStackAdapter(LayerStackAdapter):
    """In-memory :class:`LayerStackAdapter` for headless unit tests.

    Constructed with a root layer and (by default) a session layer; use the
    ``add_sublayer`` / ``remove_sublayer`` / ``set_*`` mutators to drive the
    stack into whatever shape a test needs. Every mutator fires the relevant
    :class:`LayerEvent` synchronously so subscribed code can assert against
    the callback stream.
    """

    def __init__(self, *, include_session: bool = True) -> None:
        self._layers: Dict[str, MockLayer] = {}
        self._layers[ROOT_LAYER_IDENTIFIER] = MockLayer(
            identifier=ROOT_LAYER_IDENTIFIER,
            display_name="root",
        )
        if include_session:
            self._layers[SESSION_LAYER_IDENTIFIER] = MockLayer(
                identifier=SESSION_LAYER_IDENTIFIER,
                display_name="session",
                anonymous=True,
            )
            self._session_id: Optional[str] = SESSION_LAYER_IDENTIFIER
        else:
            self._session_id = None
        self._edit_target_id: str = ROOT_LAYER_IDENTIFIER
        self._subscribers: List[Callable[[LayerEvent], None]] = []

    # ── Internal helpers ─────────────────────────────────────────────

    def _require(self, identifier: str) -> MockLayer:
        try:
            return self._layers[identifier]
        except KeyError as exc:
            raise KeyError(f"Unknown layer identifier: {identifier!r}") from exc

    def _fire(self, event: LayerEvent) -> None:
        # Snapshot so callbacks that unsubscribe or add subscribers during
        # dispatch don't mutate the iteration (matches SelectionBus).
        for callback in list(self._subscribers):
            callback(event)

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        # Invoked by ``Subscription.cancel``; ``key`` is part of that contract
        # but unused here because this adapter has a single channel.
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _walk_sublayers(
        self,
        identifier: str,
        include_anonymous: bool,
        result: List[str],
        visited: Set[str],
    ) -> None:
        if identifier in visited:
            return
        visited.add(identifier)
        layer = self._layers.get(identifier)
        if layer is None:
            return
        if include_anonymous or not layer.anonymous:
            result.append(identifier)
        for child_id in layer.sublayer_identifiers:
            self._walk_sublayers(child_id, include_anonymous, result, visited)

    # ── Stack discovery ──────────────────────────────────────────────

    def get_root_layer(self) -> LayerHandle:
        return LayerHandle(ROOT_LAYER_IDENTIFIER)

    def get_session_layer(self) -> Optional[LayerHandle]:
        if self._session_id is None:
            return None
        return LayerHandle(self._session_id)

    def get_sublayer_identifiers(self, parent: LayerHandle) -> List[str]:
        # Return a copy so callers can't accidentally mutate internal state.
        return list(self._require(parent.identifier).sublayer_identifiers)

    def find_layer(self, identifier: str) -> Optional[LayerHandle]:
        if identifier in self._layers:
            return LayerHandle(identifier)
        return None

    def get_layer_stack_identifiers(
        self,
        include_session: bool = False,
        include_anonymous: bool = True,
    ) -> List[str]:
        result: List[str] = []
        visited: Set[str] = set()

        if include_session and self._session_id is not None:
            session = self._layers[self._session_id]
            if include_anonymous or not session.anonymous:
                result.append(self._session_id)
            visited.add(self._session_id)

        self._walk_sublayers(
            ROOT_LAYER_IDENTIFIER, include_anonymous, result, visited
        )
        return result

    # ── Display ──────────────────────────────────────────────────────

    def get_display_name(self, layer: LayerHandle) -> str:
        return self._require(layer.identifier).display_name

    def get_layer_owner(self, layer: LayerHandle) -> str:
        return self._require(layer.identifier).owner

    # ── State flags ──────────────────────────────────────────────────

    def is_anonymous(self, layer: LayerHandle) -> bool:
        return self._require(layer.identifier).anonymous

    def is_dirty(self, layer: LayerHandle) -> bool:
        return self._require(layer.identifier).dirty

    def is_muted(self, layer: LayerHandle) -> bool:
        return self._require(layer.identifier).muted

    def is_locked(self, layer: LayerHandle) -> bool:
        return self._require(layer.identifier).locked

    def is_read_only_on_disk(self, layer: LayerHandle) -> bool:
        return self._require(layer.identifier).read_only

    def is_missing(self, layer: LayerHandle) -> bool:
        return self._require(layer.identifier).missing

    # ── Edit target ──────────────────────────────────────────────────

    def get_edit_target_identifier(self) -> str:
        return self._edit_target_id

    # ── Change subscription ──────────────────────────────────────────

    def subscribe_events(
        self,
        callback: Callable[[LayerEvent], None],
    ) -> Subscription:
        self._subscribers.append(callback)
        return Subscription(weakref.ref(self), "events", callback)

    # ── Mutations (ABC Step 6) ───────────────────────────────────────

    def set_edit_target(self, identifier: str) -> None:
        self._require(identifier)
        if self._edit_target_id == identifier:
            return
        self._edit_target_id = identifier
        self._fire(
            LayerEvent(
                event_type=LayerEventType.EDIT_TARGET_CHANGED,
                identifiers=(identifier,),
            )
        )

    def set_mute(self, identifier: str, muted: bool) -> None:
        layer = self._require(identifier)
        if layer.muted == muted:
            return
        layer.muted = muted
        self._fire(
            LayerEvent(
                event_type=LayerEventType.MUTE_STATE_CHANGED,
                identifiers=(identifier,),
            )
        )

    def set_lock(self, identifier: str, locked: bool) -> None:
        layer = self._require(identifier)
        if layer.locked == locked:
            return
        layer.locked = locked
        self._fire(
            LayerEvent(
                event_type=LayerEventType.LOCK_STATE_CHANGED,
                identifiers=(identifier,),
            )
        )

    def create_sublayer(
        self,
        parent_id: str,
        position: int,
        new_layer_path: str,
        transfer_root_content: bool = False,
    ) -> str:
        parent = self._require(parent_id)
        # Mint a stable identifier. Empty path → anonymous (``anon:<seq>``
        # mirrors USD's ``Sdf.Layer.CreateAnonymous`` format so downstream
        # tests can check ``is_anonymous`` without special-casing the mock).
        if new_layer_path == "":
            anon_index = sum(
                1 for lid in self._layers if lid.startswith("anon:")
            )
            identifier = f"anon:{anon_index}"
            is_anonymous = True
        else:
            identifier = new_layer_path
            is_anonymous = False
        if identifier in self._layers:
            # Match USD's ``Sdf.Layer.CreateNew`` behaviour — fail rather
            # than clobber an existing layer.
            raise ValueError(
                f"Layer already exists with identifier: {identifier!r}"
            )
        self._layers[identifier] = MockLayer(
            identifier=identifier,
            display_name=identifier,
            anonymous=is_anonymous,
        )
        if position < 0:
            parent.sublayer_identifiers.append(identifier)
        else:
            parent.sublayer_identifiers.insert(position, identifier)

        if transfer_root_content:
            # The mock does not model prim specs — the flag is honoured
            # symbolically by tagging the new layer's info dict so tests
            # can verify the call site requested transfer. Real content
            # transfer is exercised by the USD adapter.
            self._layers[identifier].info["transferred_from_root"] = "1"

        self._fire(
            LayerEvent(
                event_type=LayerEventType.SUBLAYERS_CHANGED,
                identifiers=(parent_id,),
            )
        )
        return identifier

    def insert_sublayer(
        self,
        parent_id: str,
        position: int,
        sublayer_path: str,
    ) -> None:
        parent = self._require(parent_id)
        # Mirror USD — referencing an unknown layer is valid (it becomes
        # a "missing" sublayer in the composed stack). Create a stub
        # record so subsequent queries don't KeyError.
        if sublayer_path not in self._layers:
            self._layers[sublayer_path] = MockLayer(
                identifier=sublayer_path,
                display_name=sublayer_path,
                missing=True,
            )
        if position < 0:
            parent.sublayer_identifiers.append(sublayer_path)
        else:
            parent.sublayer_identifiers.insert(position, sublayer_path)
        self._fire(
            LayerEvent(
                event_type=LayerEventType.SUBLAYERS_CHANGED,
                identifiers=(parent_id,),
            )
        )

    def remove_sublayer(self, parent_id: str, position: int) -> str:
        parent = self._require(parent_id)
        if position < 0 or position >= len(parent.sublayer_identifiers):
            raise IndexError(
                f"sublayer position {position} out of range for {parent_id!r}"
            )
        removed = parent.sublayer_identifiers.pop(position)
        self._fire(
            LayerEvent(
                event_type=LayerEventType.SUBLAYERS_CHANGED,
                identifiers=(parent_id,),
            )
        )
        return removed

    def move_sublayer(
        self,
        from_parent_id: str,
        from_position: int,
        to_parent_id: str,
        to_position: int,
        remove_source: bool = True,
    ) -> None:
        source = self._require(from_parent_id)
        destination = self._require(to_parent_id)
        if from_position < 0 or from_position >= len(source.sublayer_identifiers):
            raise IndexError(
                f"sublayer position {from_position} out of range for "
                f"{from_parent_id!r}"
            )
        identifier = source.sublayer_identifiers[from_position]

        if remove_source:
            source.sublayer_identifiers.pop(from_position)
            # Same-parent reorder with an earlier-than-source destination:
            # the pop shifted everything; adjust ``to_position`` accordingly.
            if from_parent_id == to_parent_id and to_position > from_position:
                to_position -= 1

        if to_position < 0 or to_position > len(destination.sublayer_identifiers):
            destination.sublayer_identifiers.append(identifier)
        else:
            destination.sublayer_identifiers.insert(to_position, identifier)

        # One event per parent touched — subscribers that cache by parent
        # identifier invalidate cleanly.
        parents = {from_parent_id, to_parent_id} if remove_source else {to_parent_id}
        for parent_id in sorted(parents):
            self._fire(
                LayerEvent(
                    event_type=LayerEventType.SUBLAYERS_CHANGED,
                    identifiers=(parent_id,),
                )
            )

    def replace_sublayer(
        self,
        parent_id: str,
        position: int,
        new_identifier: str,
    ) -> str:
        parent = self._require(parent_id)
        if position < 0 or position >= len(parent.sublayer_identifiers):
            raise IndexError(
                f"sublayer position {position} out of range for {parent_id!r}"
            )
        old_identifier = parent.sublayer_identifiers[position]
        # Mirror ``insert_sublayer`` for unknown targets — USD accepts a
        # sublayer reference to a not-yet-resolved path. Create a missing
        # stub so queries against the new identifier do not KeyError.
        if new_identifier not in self._layers:
            self._layers[new_identifier] = MockLayer(
                identifier=new_identifier,
                display_name=new_identifier,
                missing=True,
            )
        parent.sublayer_identifiers[position] = new_identifier
        self._fire(
            LayerEvent(
                event_type=LayerEventType.SUBLAYERS_CHANGED,
                identifiers=(parent_id,),
            )
        )
        return old_identifier

    # ── Prim-spec mutation (Step 31a) ────────────────────────────────

    def export_prim_spec(self, layer_id: str, path: str) -> str:
        layer = self._require(layer_id)
        if path not in layer.prim_specs:
            raise KeyError(
                f"layer {layer_id!r} has no prim spec at {path!r}"
            )
        return layer.prim_specs[path]

    def remove_prim_spec(self, layer_id: str, path: str) -> None:
        layer = self._require(layer_id)
        if path not in layer.prim_specs:
            raise KeyError(
                f"layer {layer_id!r} has no prim spec at {path!r}"
            )
        del layer.prim_specs[path]
        # Removing a spec dirties the layer; surface the bit flip so
        # subscribers that listen for DIRTY_STATE_CHANGED re-render.
        if not layer.dirty:
            layer.dirty = True
            self._fire(
                LayerEvent(
                    event_type=LayerEventType.DIRTY_STATE_CHANGED,
                    identifiers=(layer_id,),
                )
            )

    def import_prim_spec(self, layer_id: str, path: str, usda: str) -> None:
        layer = self._require(layer_id)
        layer.prim_specs[path] = usda
        if not layer.dirty:
            layer.dirty = True
            self._fire(
                LayerEvent(
                    event_type=LayerEventType.DIRTY_STATE_CHANGED,
                    identifiers=(layer_id,),
                )
            )

    # ── Prim-spec discovery (Step 47) ────────────────────────────────

    @staticmethod
    def _parent_of(path: str) -> str:
        """Return the parent path of an Sdf-style prim path.

        ``/World/Cube`` → ``/World``; ``/World`` → ``/``; ``/`` → ``/``.
        The mock does not link to ``pxr``, so path arithmetic is done by
        string slicing rather than ``Sdf.Path.GetParentPath``.
        """
        if path in ("", "/"):
            return "/"
        head, _, _ = path.rpartition("/")
        return head or "/"

    def get_prim_specs(
        self, layer_identifier: str, parent_path: str = "/"
    ) -> List[PrimSpecDescriptor]:
        layer = self._require(layer_identifier)
        if parent_path != "/" and parent_path not in layer.prim_spec_descriptors:
            raise KeyError(
                f"layer {layer_identifier!r} has no prim spec at "
                f"{parent_path!r}"
            )
        return [
            descriptor
            for path, descriptor in layer.prim_spec_descriptors.items()
            if self._parent_of(path) == parent_path
        ]

    def has_prim_spec(self, layer_identifier: str, spec_path: str) -> bool:
        layer = self._require(layer_identifier)
        return spec_path in layer.prim_spec_descriptors

    # ── Merge / Flatten support (Step 42) ────────────────────────────

    def _find_parent_of(self, identifier: str) -> Optional[str]:
        """Return the identifier of the parent that references ``identifier``.

        Walks every layer and returns the first one whose
        :attr:`MockLayer.sublayer_identifiers` contains ``identifier``.
        Returns ``None`` when the layer is not referenced from any
        parent (top-level, session, or detached).
        """
        for parent_id, parent in self._layers.items():
            if identifier in parent.sublayer_identifiers:
                return parent_id
        return None

    def snapshot_layer(self, identifier: str) -> LayerSnapshot:
        layer = self._require(identifier)
        parent_id = self._find_parent_of(identifier)
        if parent_id is not None:
            parent = self._layers[parent_id]
            position = parent.sublayer_identifiers.index(identifier)
        else:
            position = -1
        # Deterministic serialisation: sorted prim-spec keys keep the
        # encoded string stable across runs so tests can assert on it
        # by equality. The encoding is private to the mock — the real
        # contract is that :meth:`restore_layer_from_snapshot` accepts
        # whatever shape :meth:`snapshot_layer` produced.
        content_lines: List[str] = []
        for path in sorted(layer.prim_specs):
            content_lines.append(f"{path}={layer.prim_specs[path]}")
        content = "\n".join(content_lines)
        return LayerSnapshot(
            identifier=identifier,
            parent_identifier=parent_id,
            position_in_parent=position,
            was_edit_target=(identifier == self._edit_target_id),
            anonymous=layer.anonymous,
            content=content,
            custom_layer_data=dict(layer.info),
            mute_state=layer.muted,
            lock_state=layer.locked,
            sublayer_identifiers=tuple(layer.sublayer_identifiers),
        )

    def restore_layer_from_snapshot(
        self, snapshot: LayerSnapshot
    ) -> str:
        # Anonymous layers mint a fresh identifier on restore — matches
        # the USD adapter where ``Sdf.Layer.CreateAnonymous`` always
        # produces a new ``anon:N``. The caller updates its internal
        # reference to the returned identifier.
        if snapshot.anonymous:
            anon_index = sum(
                1 for lid in self._layers if lid.startswith("anon:")
            )
            identifier = f"anon:{anon_index}"
        else:
            identifier = snapshot.identifier

        # Rebuild the layer record. If the identifier already exists
        # (undo after a merge that didn't actually remove the layer
        # from the adapter's dict — mock keeps records alive) we
        # refresh it in place rather than allocating a new one.
        prim_specs: Dict[str, str] = {}
        if snapshot.content:
            for line in snapshot.content.split("\n"):
                if "=" not in line:
                    continue
                path, _, blob = line.partition("=")
                prim_specs[path] = blob
        layer = MockLayer(
            identifier=identifier,
            display_name=identifier,
            sublayer_identifiers=list(snapshot.sublayer_identifiers),
            muted=snapshot.mute_state,
            locked=snapshot.lock_state,
            anonymous=snapshot.anonymous,
            info=dict(snapshot.custom_layer_data),
            prim_specs=prim_specs,
        )
        self._layers[identifier] = layer

        # Re-insert into parent at the original position. An out-of-
        # range position is clamped to an append — a peer command may
        # have shortened the parent's sublayer list between snapshot
        # and restore. ``None`` parent means the layer had no parent;
        # the record is still registered so future ``find_layer`` calls
        # succeed.
        #
        # Skip re-insert when the layer is *already* referenced by its
        # parent: this is the "destination half" of a merge-down undo
        # — the destination was never unlinked, so its content has
        # just been rewritten by the ``ImportFromString`` equivalent
        # above; re-inserting would double-link the layer into the
        # parent.
        if snapshot.parent_identifier is not None:
            parent = self._require(snapshot.parent_identifier)
            if identifier not in parent.sublayer_identifiers:
                position = snapshot.position_in_parent
                if (
                    position < 0
                    or position > len(parent.sublayer_identifiers)
                ):
                    parent.sublayer_identifiers.append(identifier)
                else:
                    parent.sublayer_identifiers.insert(position, identifier)
                self._fire(
                    LayerEvent(
                        event_type=LayerEventType.SUBLAYERS_CHANGED,
                        identifiers=(snapshot.parent_identifier,),
                    )
                )

        if snapshot.was_edit_target:
            self._edit_target_id = identifier
            self._fire(
                LayerEvent(
                    event_type=LayerEventType.EDIT_TARGET_CHANGED,
                    identifiers=(identifier,),
                )
            )

        return identifier

    def transfer_layer_content(
        self, src_identifier: str, dst_identifier: str
    ) -> None:
        src = self._require(src_identifier)
        dst = self._require(dst_identifier)
        if not src.prim_specs:
            return
        # Source wins on overlap — mirrors the USD adapter where the
        # source layer in a "merge down" is stronger than the
        # destination. The destination layer is marked dirty so
        # subscribers repaint.
        for path, blob in src.prim_specs.items():
            dst.prim_specs[path] = blob
        if not dst.dirty:
            dst.dirty = True
            self._fire(
                LayerEvent(
                    event_type=LayerEventType.DIRTY_STATE_CHANGED,
                    identifiers=(dst_identifier,),
                )
            )

    # ── File I/O ─────────────────────────────────────────────────────

    def save_layer(self, identifier: str) -> bool:
        layer = self._require(identifier)
        if layer.anonymous or layer.missing:
            return False
        if not layer.dirty:
            return True
        layer.dirty = False
        self._fire(
            LayerEvent(
                event_type=LayerEventType.DIRTY_STATE_CHANGED,
                identifiers=(identifier,),
            )
        )
        return True

    def save_layer_as(
        self,
        identifier: str,
        new_path: str,
        replace_in_parent: bool,
    ) -> Optional[str]:
        source = self._require(identifier)
        if new_path == "":
            return None
        if new_path in self._layers:
            return None
        # Export: clone the record at the new path with a clean dirty bit.
        self._layers[new_path] = MockLayer(
            identifier=new_path,
            display_name=new_path,
            anonymous=False,
            dirty=False,
            muted=source.muted,
            locked=source.locked,
            read_only=source.read_only,
        )
        if not replace_in_parent:
            return new_path
        # Walk every parent and swap the source identifier for the new one.
        swapped_parents: List[str] = []
        for parent_id, parent in self._layers.items():
            replaced = False
            for idx, child_id in enumerate(parent.sublayer_identifiers):
                if child_id == identifier:
                    parent.sublayer_identifiers[idx] = new_path
                    replaced = True
            if replaced:
                swapped_parents.append(parent_id)
        for parent_id in swapped_parents:
            self._fire(
                LayerEvent(
                    event_type=LayerEventType.SUBLAYERS_CHANGED,
                    identifiers=(parent_id,),
                )
            )
        return new_path

    def reload_layer(self, identifier: str) -> bool:
        layer = self._require(identifier)
        if layer.anonymous or layer.missing:
            return False
        if not layer.dirty:
            return False
        layer.dirty = False
        self._fire(
            LayerEvent(
                event_type=LayerEventType.DIRTY_STATE_CHANGED,
                identifiers=(identifier,),
            )
        )
        return True

    # ── Mock-only test helpers ───────────────────────────────────────

    def add_sublayer(
        self,
        parent_id: str,
        new_id: str,
        display_name: Optional[str] = None,
        position: int = -1,
    ) -> LayerHandle:
        """Test helper: insert ``new_id`` into ``parent_id`` and emit
        ``SUBLAYERS_CHANGED``.

        Complementary to :meth:`create_sublayer` (which mints its own
        identifier); this helper lets tests pick the identifier directly
        and optionally override the display name. Duplicate inserts are
        permitted — USD allows a sublayer reference to appear twice in a
        parent — and a pre-existing layer is re-used rather than recreated.
        """
        parent = self._require(parent_id)
        if new_id not in self._layers:
            self._layers[new_id] = MockLayer(
                identifier=new_id,
                display_name=display_name if display_name is not None else new_id,
            )
        elif display_name is not None:
            self._layers[new_id].display_name = display_name

        if position < 0:
            parent.sublayer_identifiers.append(new_id)
        else:
            parent.sublayer_identifiers.insert(position, new_id)

        self._fire(
            LayerEvent(
                event_type=LayerEventType.SUBLAYERS_CHANGED,
                identifiers=(parent_id,),
            )
        )
        return LayerHandle(new_id)

    def set_dirty(self, identifier: str, dirty: bool) -> None:
        """Test helper: flip the dirty flag and emit
        ``DIRTY_STATE_CHANGED``. Idempotent."""
        layer = self._require(identifier)
        if layer.dirty == dirty:
            return
        layer.dirty = dirty
        self._fire(
            LayerEvent(
                event_type=LayerEventType.DIRTY_STATE_CHANGED,
                identifiers=(identifier,),
            )
        )

    def set_read_only(self, identifier: str, read_only: bool) -> None:
        """Test helper: flip the on-disk read-only flag and emit
        ``FILE_PERMISSION_CHANGED``. Idempotent."""
        layer = self._require(identifier)
        if layer.read_only == read_only:
            return
        layer.read_only = read_only
        self._fire(
            LayerEvent(
                event_type=LayerEventType.FILE_PERMISSION_CHANGED,
                identifiers=(identifier,),
            )
        )

    def set_prim_spec(
        self,
        layer_id: str,
        path: str,
        usda: Optional[str] = None,
    ) -> None:
        """Test helper: drop a fake prim-spec blob onto ``layer_id``.

        Complements :meth:`import_prim_spec` — tests that need a layer
        to start with prim specs present can seed the adapter directly
        without routing through an undoable command. When ``usda`` is
        ``None``, a synthetic token derived from ``path`` is stored so
        round-trip assertions can compare by equality.
        """
        layer = self._require(layer_id)
        layer.prim_specs[path] = (
            usda if usda is not None else f"<mock-prim-spec {path}>"
        )

    def set_prim_spec_descriptor(
        self,
        layer_id: str,
        path: str,
        type_name: str = "",
        specifier: PrimSpecifier = PrimSpecifier.DEF,
        has_reference: bool = False,
        has_payload: bool = False,
        is_instanceable: bool = False,
    ) -> PrimSpecDescriptor:
        """Test helper: seed a :class:`PrimSpecDescriptor` at ``path``.

        Used by Step 47+ tests to populate a layer's prim-spec tree so
        :meth:`get_prim_specs` / :meth:`has_prim_spec` have something to
        return. Overwrites any existing descriptor at ``path`` so tests
        can re-seed without clearing first. Returns the stored descriptor
        for convenience.
        """
        layer = self._require(layer_id)
        descriptor = PrimSpecDescriptor(
            path=path,
            type_name=type_name,
            specifier=specifier,
            has_reference=has_reference,
            has_payload=has_payload,
            is_instanceable=is_instanceable,
        )
        layer.prim_spec_descriptors[path] = descriptor
        return descriptor

    def set_missing(self, identifier: str, missing: bool) -> None:
        """Test helper: flip the missing flag and emit ``INFO_CHANGED``
        with the ``"missing"`` field name — v1 has no dedicated
        missing-state event and missing-ness is semantically file
        metadata.
        """
        layer = self._require(identifier)
        if layer.missing == missing:
            return
        layer.missing = missing
        self._fire(
            LayerEvent(
                event_type=LayerEventType.INFO_CHANGED,
                identifiers=(identifier,),
                info_fields={identifier: ("missing",)},
            )
        )
