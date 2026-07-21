# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""USD-specific undo Commands for UsdStageAdapter mutations.

SetVisibilityCommand and NamespaceEditCommand implement the Command ABC so
UsdStageAdapter can push all mutations through UndoManager.
"""

from __future__ import annotations

import contextlib
from typing import Any

try:
    from pxr import Sdf, UsdGeom
    _HAS_USD = True
except ImportError:
    _HAS_USD = False

from ovui_data_adapters.common import Command, CommandCancelled


_CAMERA_POSE_PROPERTY_NAMES = frozenset(
    {
        "focusDistance",
        "omni:kit:centerOfInterest",
        "xformOpOrder",
    }
)


def _camera_pose_property_names(layer: Any, prim_path: Any) -> set[str]:
    names = set(_CAMERA_POSE_PROPERTY_NAMES)
    prim_spec = layer.GetPrimAtPath(prim_path)
    if prim_spec is None:
        return names
    names.update(
        str(name)
        for name in prim_spec.properties.keys()
        if str(name).startswith("xformOp:")
    )
    return names


class _CameraPoseSnapshot:
    """Snapshot the authored camera pose fields in one edit-target layer."""

    def __init__(self, layer: Any, prim_path: Any) -> None:
        self._prim_path = prim_path
        self._holder = Sdf.Layer.CreateAnonymous()
        Sdf.CreatePrimInLayer(self._holder, self._prim_path)
        self._property_names = tuple(sorted(_camera_pose_property_names(layer, prim_path)))
        for name in self._property_names:
            prop_path = self._prim_path.AppendProperty(name)
            if layer.GetPropertyAtPath(prop_path) is not None:
                Sdf.CopySpec(layer, prop_path, self._holder, prop_path)

    def restore(self, layer: Any) -> None:
        Sdf.CreatePrimInLayer(layer, self._prim_path)
        prim_spec = layer.GetPrimAtPath(self._prim_path)
        if prim_spec is None:
            return

        names_to_remove = _camera_pose_property_names(layer, self._prim_path)
        names_to_remove.update(self._property_names)
        for name in sorted(names_to_remove):
            prop = layer.GetPropertyAtPath(self._prim_path.AppendProperty(name))
            if prop is not None:
                prim_spec.RemoveProperty(prop)

        for name in self._property_names:
            prop_path = self._prim_path.AppendProperty(name)
            if self._holder.GetPropertyAtPath(prop_path) is not None:
                Sdf.CopySpec(self._holder, prop_path, layer, prop_path)


# The write-set prediction mirrors the UsdGeomImageable algorithm of this
# exact pinned OpenUSD version (verified against its source and probes).
# Any other runtime — Kit or custom builds may supply their own USD — is not
# a verified prediction target and must take the safe whole-layer mode. The
# decision is frozen at import time so it cannot drift mid-attempt.
_PINNED_USD_VERSION = (0, 25, 11)


def prediction_runtime_supported() -> bool:
    """Frozen support decision for the targeted (Mode A) prediction."""
    if not _HAS_USD:
        return False
    try:
        from pxr import Usd
        return tuple(Usd.GetVersion()) == _PINNED_USD_VERSION
    except Exception:
        return False


_PREDICTION_SUPPORTED = prediction_runtime_supported()


def _edit_target_globally_identity(edit_target: Any) -> bool:
    """True only for a globally identity edit-target mapping with no offset.

    A per-path identity check is insufficient: a direct-variant edit target
    maps paths outside the variant domain identically while being globally
    non-identity, and its authoring creates variant-set state a targeted
    snapshot cannot enumerate. Anything non-identity (or uncertain) must use
    the whole-layer transaction mode.
    """
    try:
        map_function = edit_target.GetMapFunction()
        return bool(map_function.isIdentity) and (
            map_function.timeOffset == Sdf.LayerOffset()
        )
    except Exception:
        return False


def predict_visibility_write_prims(stage: Any, prim: Any, visible: bool) -> set:
    """Scene prim paths a MakeVisible/MakeInvisible call may author.

    Mirrors UsdGeomImageable (usdGeom/imageable.cpp): MakeInvisible eagerly
    creates the target's visibility attribute before its value check, so the
    target is always captured. MakeVisible flips the target when its resolved
    value reads 'invisible', flips authored-invisible imageable ancestors
    root-down, and authors 'invisible' on imageable non-chain children of
    each imageable ancestor at or below the first invisible one;
    non-imageable ancestors contribute nothing. Used only to scope exact
    transaction capture and semantic pre-reads — never to build event paths.
    """
    writes = {str(prim.GetPath())}
    if not visible:
        return writes
    chain = []
    parent = prim.GetParent()
    while parent and parent.GetPath() != Sdf.Path.absoluteRootPath:
        chain.append(parent)
        parent = parent.GetParent()
    chain.reverse()
    chain_child = {}
    for index, ancestor in enumerate(chain):
        child = chain[index + 1] if index + 1 < len(chain) else prim
        chain_child[ancestor.GetPath()] = child
    has_invisible_ancestor = False
    for ancestor in chain:
        imageable = UsdGeom.Imageable(ancestor)
        if not imageable:
            continue
        is_invisible = (
            imageable.GetVisibilityAttr().Get() == UsdGeom.Tokens.invisible
        )
        if is_invisible:
            writes.add(str(ancestor.GetPath()))
        if is_invisible or has_invisible_ancestor:
            has_invisible_ancestor = True
            keep = chain_child[ancestor.GetPath()]
            for child in ancestor.GetAllChildren():
                if child != keep and UsdGeom.Imageable(child):
                    writes.add(str(child.GetPath()))
    return writes


def _ensure_prim_spec_chain(layer: Any, prim_path: Any) -> Any:
    """Create (or fetch) the prim-spec chain for ``prim_path`` in ``layer``.

    Unlike plain ``Sdf.CreatePrimInLayer``, this handles paths carrying
    VARIANT SELECTION components (a non-identity edit target maps
    composed properties into variant spec paths): the variant set and
    variant specs are created explicitly where absent.
    """
    for prefix in prim_path.GetPrefixes():
        if layer.GetPrimAtPath(prefix) is not None:
            continue
        if prefix.IsPrimVariantSelectionPath():
            parent = layer.GetPrimAtPath(prefix.GetParentPath())
            vset_name, variant_name = prefix.GetVariantSelection()
            vset = parent.variantSets.get(vset_name)
            if vset is None:
                vset = Sdf.VariantSetSpec(parent, vset_name)
            if variant_name not in {v.name for v in vset.variants}:
                Sdf.VariantSpec(vset, variant_name)
        else:
            Sdf.CreatePrimInLayer(layer, prefix)
    return layer.GetPrimAtPath(prim_path)


def _prop_spec_fingerprint(spec: Any) -> tuple:
    return tuple(
        sorted((str(key), repr(spec.GetInfo(key))) for key in spec.ListInfoKeys())
    )


def _prim_spec_strict_state(spec: Any) -> tuple:
    """Strict namespace-state fingerprint of one prim spec.

    Covers every prim-level field (info keys with values — customData,
    kind, active, type name, composition list-ops, variant selections…),
    the NON-visibility property name set, child prim names, and variant
    set names. The command's own authoring only ever touches the
    ``visibility`` property (fingerprinted exactly and separately), so any
    difference here is a foreign namespace-state change and strict
    exactness must fail — for PRE-EXISTING specs just as for created ones.
    Property VALUES of sibling properties are deliberately not embedded
    (they can be arbitrarily large); the owning adapter's net-zero
    verification against the attempt's whole-layer baseline covers those.
    """
    return (
        tuple(sorted(
            (str(key), repr(spec.GetInfo(key)))
            for key in spec.ListInfoKeys()
        )),
        tuple(sorted(
            p.name for p in spec.properties if p.name != "visibility"
        )),
        tuple(sorted(c.name for c in spec.nameChildren)),
        tuple(sorted(v.name for v in spec.variantSets)),
    )


class _TargetedVisibilitySnapshot:
    """Mode A: exact visibility spec state for an identity edit target.

    Captures, per predicted scene prim path, the full `.visibility` property
    spec (via ``Sdf.CopySpec`` into a holder) or its absence, plus per-prefix
    prim-spec presence so replay can distinguish created ancestors from
    pre-existing ones. Replay recreates parents root-first before copying and
    prunes only prim specs recorded absent pre-edge and inert after cleanup.

    ``prop_name`` generalizes the same exact capture/replay contract to any
    single property; the Property Inspector's attribute edit transaction
    uses it so undo/redo restores the exact target-layer opinion (including
    the ABSENCE of one) instead of authoring the previously resolved value.

    ``prop_spec_paths`` targets explicit LAYER spec paths instead of
    composed prim paths: a non-identity edit target (direct variant,
    reference, offset) maps composed properties to spec paths a composed
    snapshot cannot see, so the PI transaction captures exactly the
    mapped specs — never the whole layer, so foreign concurrent content
    in the same layer is never owned by the edit's undo/redo.
    """

    _LIST_OP_FIELDS = (
        "explicitItems", "addedItems", "prependedItems", "appendedItems",
        "deletedItems",
    )

    def __init__(
        self, layer: Any, prim_paths: Any, prop_name: str = "visibility",
        prop_spec_paths: Any = None,
    ) -> None:
        self._layer = layer
        self._props: dict = {}
        self._prims: dict = {}
        self._prim_state: dict = {}
        # Variant NAMESPACE CLOSURE per variant-selection prefix: authoring
        # into a mapped variant spec also creates the owner's variant-set
        # spec and its ``variantSets`` list-op membership — exact undo of
        # an edit into an initially EMPTY target must restore those too.
        # Keyed "owner|set|variant" → (set_present, variant_present,
        # membership-per-list-op-field for OUR set name only, so foreign
        # variant sets and entries are never owned).
        self._variant_closures: dict = {}
        if prop_spec_paths is not None:
            spec_paths = [Sdf.Path(str(p)) for p in prop_spec_paths]
        else:
            spec_paths = [
                Sdf.Path(path_str).AppendProperty(prop_name)
                for path_str in prim_paths
            ]
        for prop_path in sorted(spec_paths, key=str):
            # NB: GetPrimPath() STRIPS variant selections; the owner prim
            # of a mapped variant property spec is the variant prim spec.
            prim_path = prop_path.GetPrimOrPrimVariantSelectionPath()
            spec = layer.GetPropertyAtPath(prop_path)
            if spec is None:
                self._props[str(prop_path)] = None
            else:
                holder = Sdf.Layer.CreateAnonymous("ovui-vis-undo")
                _ensure_prim_spec_chain(holder, prim_path)
                Sdf.CopySpec(layer, prop_path, holder, prop_path)
                self._props[str(prop_path)] = holder
            for prefix in prim_path.GetPrefixes():
                key = str(prefix)
                if prefix.IsPrimVariantSelectionPath():
                    closure_key = self._closure_key(prefix)
                    if closure_key not in self._variant_closures:
                        self._variant_closures[closure_key] = (
                            self._closure_state(layer, prefix))
                if key not in self._prims:
                    prefix_spec = layer.GetPrimAtPath(prefix)
                    self._prims[key] = prefix_spec is not None
                    # STRICT namespace state per prefix — pre-existing specs
                    # included, so a foreign field added to an ALREADY
                    # PRESENT spec also fails exactness (round 9).
                    self._prim_state[key] = (
                        None if prefix_spec is None
                        else _prim_spec_strict_state(prefix_spec)
                    )
        if not self.matches(layer):
            raise RuntimeError("visibility snapshot capture verification failed")

    @staticmethod
    def _closure_key(variant_prefix: Any) -> str:
        owner = variant_prefix.GetParentPath()
        set_name, variant_name = variant_prefix.GetVariantSelection()
        return f"{owner}|{set_name}|{variant_name}"

    def _closure_state(self, layer: Any, variant_prefix: Any) -> tuple:
        """(set_present, variant_present, our-set list-op membership)."""
        owner_path = variant_prefix.GetParentPath()
        set_name, variant_name = variant_prefix.GetVariantSelection()
        owner = layer.GetPrimAtPath(owner_path)
        if owner is None:
            membership = tuple(
                (field, False) for field in self._LIST_OP_FIELDS)
            return (False, False, membership)
        vset = owner.variantSets.get(set_name)
        set_present = vset is not None
        variant_present = bool(
            set_present and any(v.name == variant_name for v in vset.variants)
        )
        proxy = owner.variantSetNameList
        membership = tuple(
            (field, set_name in list(getattr(proxy, field)))
            for field in self._LIST_OP_FIELDS
        )
        return (set_present, variant_present, membership)

    def _restore_closure(self, layer: Any, closure_key: str) -> None:
        owner_str, set_name, variant_name = closure_key.split("|")
        owner_path = Sdf.Path(owner_str)
        set_present, variant_present, membership = (
            self._variant_closures[closure_key])
        owner = layer.GetPrimAtPath(owner_path)
        if owner is None:
            if not (set_present or variant_present
                    or any(flag for _f, flag in membership)):
                return  # target state is fully absent: nothing to do
            owner = _ensure_prim_spec_chain(layer, owner_path)
        vset = owner.variantSets.get(set_name)
        if variant_present:
            if vset is None:
                vset = Sdf.VariantSetSpec(owner, set_name)
            if not any(v.name == variant_name for v in vset.variants):
                Sdf.VariantSpec(vset, variant_name)
        elif vset is not None:
            ours = [v for v in vset.variants if v.name == variant_name]
            for variant in ours:
                # NEVER destroy foreign work: the owned visibility
                # property was already removed by the property replay,
                # so an INERT variant prim spec holds nothing but our
                # scaffolding. Anything else — a foreign attribute,
                # child prim, relationship, or metadata authored inside
                # the command-created variant — makes the spec non-inert
                # and the whole closure survives untouched (variant, set,
                # AND list-op membership, so the foreign content stays
                # composable). The fingerprint tolerates the survivor
                # exactly like a surviving foreign prim spec.
                if not variant.primSpec.isInert:
                    return
                vset.RemoveVariant(variant)
            if not set_present and not list(vset.variants):
                # OUR closure created the set and no foreign variant keeps
                # it alive: remove it. A foreign variant leaves the set in
                # place (verification then reports the entanglement).
                del owner.variantSets[set_name]
        proxy = owner.variantSetNameList
        for field, should_have in membership:
            items = getattr(proxy, field)
            has = set_name in list(items)
            if should_have and not has:
                items.append(set_name)
            elif not should_have and has:
                items.remove(set_name)

    def _expected_fingerprint(self, strict_prims: bool = False) -> dict:
        expected: dict = {}
        for prop_path, holder in self._props.items():
            if holder is None:
                expected[prop_path] = None
            else:
                expected[prop_path] = _prop_spec_fingerprint(
                    holder.GetPropertyAtPath(prop_path)
                )
        for prim_path, present in self._prims.items():
            if strict_prims:
                expected["P:" + prim_path] = self._prim_state[prim_path]
            else:
                expected["P:" + prim_path] = present
        for closure_key, state in self._variant_closures.items():
            expected["V:" + closure_key] = state
        return expected

    def _current_fingerprint(
        self, layer: Any, tolerate_survivors: bool = True,
        strict_prims: bool = False,
    ) -> dict:
        current: dict = {}
        for prop_path in self._props:
            spec = layer.GetPropertyAtPath(prop_path)
            current[prop_path] = None if spec is None else _prop_spec_fingerprint(spec)
        for prim_path in self._prims:
            spec = layer.GetPrimAtPath(prim_path)
            if spec is None:
                current["P:" + prim_path] = None if strict_prims else False
            elif not self._prims[prim_path] and not spec.isInert:
                # Recorded absent pre-edge but now carrying unrelated
                # non-inert opinions (someone else authored onto the created
                # spec). Deleting it would destroy foreign data, so it
                # survives cleanup. The REPLAY verification tolerates the
                # survivor (the visibility property contract itself is
                # restored and foreign opinions are preserved), but EXACT
                # equality never does: a surviving spec is a real layer
                # difference, so net-zero/no-op claims must fail and the
                # attempt's retained genuine segments flush conservatively.
                if strict_prims:
                    current["P:" + prim_path] = "surviving-foreign-spec"
                else:
                    current["P:" + prim_path] = (
                        False if tolerate_survivors else "surviving-foreign-spec"
                    )
            else:
                # STRICT mode compares the full namespace state of every
                # recorded prefix — a foreign opinion on a PRE-EXISTING
                # spec (metadata, new sibling property, new child, variant
                # set) therefore fails exactness while the tolerant replay
                # contract still passes.
                current["P:" + prim_path] = (
                    _prim_spec_strict_state(spec) if strict_prims else True
                )
        for closure_key, expected in self._variant_closures.items():
            owner_str, set_name, variant_name = closure_key.split("|")
            prefix = Sdf.Path(owner_str).AppendVariantSelection(
                set_name, variant_name)
            state = self._closure_state(layer, prefix)
            expected_absent = not (
                expected[0] or expected[1]
                or any(flag for _f, flag in expected[2])
            )
            if state != expected and expected_absent:
                # The closure should be gone but survives because FOREIGN
                # content was authored inside the command-created variant:
                # exactly like a surviving foreign prim spec, the replay
                # contract tolerates it (the owned visibility property is
                # fingerprinted separately and IS restored), while strict
                # exactness — net-zero/no-op claims — always fails.
                variant_spec = layer.GetPrimAtPath(prefix)
                if variant_spec is not None and not variant_spec.isInert:
                    if strict_prims or not tolerate_survivors:
                        state = "surviving-foreign-variant"
                    else:
                        state = expected
            current["V:" + closure_key] = state
        return current

    def matches(self, layer: Any) -> bool:
        """Replay-contract check: visibility specs exact, survivors tolerated."""
        return self._current_fingerprint(layer) == self._expected_fingerprint()

    def matches_exactly(self, layer: Any) -> bool:
        """STRICT namespace identity for net-zero/no-op claims.

        Compares full prim-spec namespace state (pre-existing AND created
        prefixes); any foreign survivor or field difference fails.
        """
        return (
            self._current_fingerprint(
                layer, tolerate_survivors=False, strict_prims=True
            )
            == self._expected_fingerprint(strict_prims=True)
        )

    def replay(self, layer: Any) -> None:
        for prop_path_str, holder in self._props.items():
            prop_path = Sdf.Path(prop_path_str)
            prim_path = prop_path.GetPrimOrPrimVariantSelectionPath()
            if holder is None:
                spec = layer.GetPropertyAtPath(prop_path)
                if spec is not None:
                    layer.GetPrimAtPath(prim_path).RemoveProperty(spec)
            else:
                # Root-first: CopySpec fails when parent specs are absent.
                _ensure_prim_spec_chain(layer, prim_path)
                Sdf.CopySpec(holder, prop_path, layer, prop_path)
        # Variant namespace closure: restore each recorded owner's variant
        # set, our variant spec, and OUR set's list-op membership to the
        # captured state. Creation targets shallow-first (outer variants
        # exist before nested ones), removal targets deep-first (nested
        # variants release before their owners), so that afterwards a
        # fully-released owner is inert and prunable below.
        def _closure_depth(key: str) -> int:
            return key.split("|", 1)[0].count("/") + key.count("{")

        present_targets = [
            key for key, state in self._variant_closures.items()
            if state[0] or state[1] or any(flag for _f, flag in state[2])
        ]
        absent_targets = [
            key for key in self._variant_closures
            if key not in present_targets
        ]
        for key in sorted(present_targets, key=_closure_depth):
            self._restore_closure(layer, key)
        for key in sorted(absent_targets, key=_closure_depth, reverse=True):
            self._restore_closure(layer, key)
        # Post-order prune of prim specs we recorded absent pre-edge, gated
        # on OpenUSD's authoritative inertness predicate (``SdfSpec::IsInert``
        # via ``spec.isInert``): a spec that acquired any unrelated authored
        # state — metadata, list-ops, composition arcs, children — is never
        # deleted. Pre-existing specs are never deleted either.
        for prim_path_str in sorted(self._prims, key=len, reverse=True):
            if self._prims[prim_path_str]:
                continue
            spec = layer.GetPrimAtPath(prim_path_str)
            if spec is None:
                continue
            if spec.isInert:
                batch = Sdf.BatchNamespaceEdit()
                batch.Add(Sdf.Path(prim_path_str), Sdf.Path.emptyPath)
                layer.Apply(batch)
        if not self.matches(layer):
            raise RuntimeError("visibility snapshot replay verification failed")


class _WholeLayerVisibilitySnapshot:
    """Mode B: exact whole-target-layer state for non-identity edit targets.

    ``TransferContent`` is incremental and unverified inside OpenUSD, so both
    capture and replay are explicitly content-verified via ExportToString
    equality; failures surface instead of being assumed atomic.
    """

    def __init__(self, layer: Any) -> None:
        self._holder = Sdf.Layer.CreateAnonymous("ovui-vis-undo-layer")
        self._holder.TransferContent(layer)
        self._text = self._holder.ExportToString()
        if self._text != layer.ExportToString():
            raise RuntimeError("whole-layer snapshot capture verification failed")

    def matches(self, layer: Any) -> bool:
        return layer.ExportToString() == self._text

    # Whole-layer text equality is already strict field identity: there is
    # no tolerated-survivor distinction in Mode B.
    matches_exactly = matches

    def replay(self, layer: Any) -> None:
        layer.TransferContent(self._holder)
        if not self.matches(layer):
            raise RuntimeError("whole-layer snapshot replay verification failed")


class SetVisibilityCommand(Command):
    """Transactional visibility toggle with exact edit-target restore.

    do() authors via MakeVisible/MakeInvisible and keeps two immutable
    restoration targets (pre_do / post_do); undo/redo replay them exactly.
    Every edge takes a fresh compensation snapshot first and rolls back to it
    if replay fails partway. Undo/redo edges bracket themselves through the
    owning adapter (when provided) so their genuine notices become one
    truthful adapter event; the adapter brackets do() itself.
    """

    def __init__(self, prim: Any, visible: bool, adapter: Any = None) -> None:
        self._stage = prim.GetStage()
        self._path = prim.GetPath()
        self._visible = bool(visible)
        self._adapter = adapter
        self._mode: Any = None
        self._layer: Any = None
        self._predicted: Any = None
        self._pre_do: Any = None
        self._post_do: Any = None

    # -- prediction / capture -------------------------------------------------

    def predicted_write_prims(self) -> set:
        prim = self._stage.GetPrimAtPath(self._path)
        return predict_visibility_write_prims(self._stage, prim, self._visible)

    def edge_hint_prims(self) -> set:
        """Semantic pre-read hint for undo/redo edges.

        Frozen at do() time: an undo/redo edge restores the do-time touched
        set, so recomputing the prediction against the current composed state
        would under-cover the boundaries (the notices still own the roots).
        """
        if self._predicted is not None:
            return set(self._predicted)
        return self.predicted_write_prims()

    def operation_layers(self) -> list:
        """The layer(s) this command's authoring/replay writes.

        Frozen once do() selects the mode; before that (the do-time attempt
        begins before mode selection, on the same call stack) the stage's
        current edit-target layer is the authoring destination. The owning
        adapter baselines these layers so a bare resync captured inside the
        operation window can be PROVEN visibility-only against them — a
        proof over the operation's full actual consequence, not a partial
        composed-state fingerprint.
        """
        if self._layer is not None:
            return [self._layer]
        try:
            return [self._stage.GetEditTarget().GetLayer()]
        except Exception:
            return []

    def _capture(self) -> Any:
        if self._mode == "A":
            return _TargetedVisibilitySnapshot(self._layer, self._predicted)
        return _WholeLayerVisibilitySnapshot(self._layer)

    def _select_mode(self) -> None:
        edit_target = self._stage.GetEditTarget()
        self._layer = edit_target.GetLayer()
        self._predicted = sorted(self.predicted_write_prims())
        if not _PREDICTION_SUPPORTED:
            # Unverified/unsupported USD runtime: the targeted prediction
            # cannot be trusted, so the exact whole-layer mode applies.
            self._mode = "B"
            return
        if _edit_target_globally_identity(edit_target):
            mapped_ok = all(
                edit_target.MapToSpecPath(Sdf.Path(p)) == Sdf.Path(p)
                for p in self._predicted
            )
            self._mode = "A" if mapped_ok else "B"
        else:
            self._mode = "B"

    def _compensate(self, snapshot: Any, cause: BaseException) -> None:
        # BaseException included: a KeyboardInterrupt/SystemExit raised
        # DURING compensation is a secondary cleanup failure — it must
        # never displace the primary operation error `cause`. It is
        # attached as a note and the (unproved) surviving state flows to
        # the adapter's conservative reporting via the cleared marker.
        try:
            with self._operation_window():
                snapshot.replay(self._layer)
            # Replay restored the visibility property contract, but only
            # STRICT field identity proves net zero: a preserved foreign
            # survivor (a created spec that re-entrant content made
            # non-inert) is a real surviving layer difference, so the
            # attempt stays uncertain and its retained genuine segments
            # flush conservatively instead of being suppressed.
            exact_probe = getattr(
                snapshot, "matches_exactly", snapshot.matches
            )
            exact = bool(exact_probe(self._layer))
            setattr(cause, "_ovui_visibility_net_zero", exact)
            if not exact:
                add_note = getattr(cause, "add_note", None)
                if callable(add_note):
                    add_note(
                        "visibility compensation restored the visibility "
                        "contract but a foreign non-inert spec survived: "
                        "NOT field-exact; retained genuine segments flush "
                        "conservatively"
                    )
        except BaseException as compensation_error:  # noqa: BLE001
            setattr(cause, "_ovui_visibility_net_zero", False)
            add_note = getattr(cause, "add_note", None)
            if callable(add_note):
                add_note(
                    "visibility compensation also failed: "
                    f"{type(compensation_error).__name__}: {compensation_error}"
                )

    # -- edges -----------------------------------------------------------------

    def do(self) -> None:
        if self._post_do is not None:
            # Re-execution through UndoGroup.redo → Command.redo → do():
            # redo restores the exact post-do snapshot; it never re-runs
            # MakeVisible against a possibly different composed context.
            self._bracketed(lambda: self._replay_edge(self._post_do))
            return
        if self._mode is None:
            self._select_mode()
        self._pre_do = self._capture()
        prim = self._stage.GetPrimAtPath(self._path)
        imageable = UsdGeom.Imageable(prim)
        try:
            with self._operation_window():
                if self._visible:
                    imageable.MakeVisible()
                else:
                    imageable.MakeInvisible()
        except BaseException as exc:  # incl. KeyboardInterrupt/SystemExit
            self._compensate(self._pre_do, exc)
            raise
        try:
            self._post_do = self._capture()
        except BaseException as exc:
            # Without a verified post-action restoration target the attempt
            # cannot commit (redo state unavailable): compensate to pre_do.
            # BaseException included — the ORIGINAL capture error stays
            # primary; a compensation failure only attaches to it.
            self._compensate(self._pre_do, exc)
            raise
        if self._outcome_is_noop():
            # Genuine outcome no-op: the attempt's notice ledger is empty and
            # the target layer is field-identical to its pre-do capture, so
            # nothing happened. CommandCancelled makes the push leave undo
            # AND redo history untouched; the adapter emits no event.
            self._post_do = None
            raise CommandCancelled(
                "visibility no-op: empty genuine notice ledger and "
                "unchanged target layer"
            )

    def _outcome_is_noop(self) -> bool:
        """Outcome-defined no-op test (empty ledger + unchanged layer).

        Both legs are required: the owning adapter's attempt ledger (genuine
        ``Usd.Notice.ObjectsChanged`` payloads) must name nothing, and the
        pre-do restoration target must still match the live target layer.
        Without an owning adapter no ledger authority exists, so the command
        conservatively stays undoable.
        """
        probe = getattr(
            self._adapter, "visibility_attempt_ledger_is_empty", None
        )
        if not callable(probe) or not probe():
            return False
        try:
            # STRICT: a surviving foreign spec means the layer is not
            # field-identical, so the outcome is not a no-op.
            exact_probe = getattr(
                self._pre_do, "matches_exactly", self._pre_do.matches
            )
            return bool(exact_probe(self._layer))
        except Exception:
            return False

    @contextlib.contextmanager
    def _operation_window(self) -> Any:
        """Genuine operation provenance: mark OUR authoring and replays."""
        window = getattr(self._adapter, "visibility_operation_window", None)
        if callable(window):
            with window():
                yield
        else:
            yield

    def _replay_edge(self, target: Any) -> None:
        compensation = self._capture()
        try:
            with self._operation_window():
                target.replay(self._layer)
        except BaseException as exc:  # incl. KeyboardInterrupt/SystemExit
            self._compensate(compensation, exc)
            raise

    def _bracketed(self, edge_fn: Any) -> None:
        adapter = self._adapter
        run_edge = getattr(adapter, "run_visibility_command_edge", None)
        if callable(run_edge):
            run_edge(self, edge_fn)
        else:
            edge_fn()

    def undo(self) -> None:
        if self._pre_do is None:
            return
        self._bracketed(lambda: self._replay_edge(self._pre_do))

    def redo(self) -> None:
        if self._post_do is None:
            return
        self._bracketed(lambda: self._replay_edge(self._post_do))


class DeletePrimCommand(Command):
    """Delete a prim at path via BatchNamespaceEdit. Undo restores it.

    ``affects_namespace`` lets the UndoManager settle active property
    edit transactions BEFORE this command's push executes, so an
    in-flight Property Inspector edit can never be silently discarded or
    entangled with the deletion.

    Captures the prim's full spec before deletion so it can be recreated on
    undo via ``Sdf.CopySpec`` into a temporary anonymous layer, then copied
    back on undo.
    """

    affects_namespace = True

    def __init__(self, stage: Any, prim_path: "Sdf.Path") -> None:
        self._stage = stage
        self._path = prim_path
        self._captured_layer = None

    def do(self) -> None:
        # Capture current spec into an in-memory layer for undo.
        #
        # ``Sdf.CopySpec(src_layer, src_path, dst_layer, dst_path)`` requires
        # the destination layer to already have a parent prim spec along
        # ``dst_path``. For a freshly-anonymous ``tmp`` layer the parent
        # specs do not exist yet, so we have to call
        # ``Sdf.CreatePrimInLayer`` on the parent path first — without this,
        # USD's ``SdfData`` raises ``No spec at <…> when trying to set field
        # 'primChildren'`` and the deletion silently aborts. Reproduced
        # against ``tests/data/simple_scene.usda``: deleting
        # ``/World/Cube`` failed because ``/World`` was missing on ``tmp``.
        # The previous mock-only test in
        # ``tests/test_delete_prim_command.py`` did not exercise this
        # precondition because it patched ``Sdf`` entirely.
        layer = self._stage.GetEditTarget().GetLayer()
        tmp = Sdf.Layer.CreateAnonymous()
        parent_path = self._path.GetParentPath()
        if parent_path != Sdf.Path.absoluteRootPath:
            Sdf.CreatePrimInLayer(tmp, parent_path)
        Sdf.CopySpec(layer, self._path, tmp, self._path)
        self._captured_layer = tmp
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(self._path, Sdf.Path.emptyPath)
        layer.Apply(batch)

    def undo(self) -> None:
        if self._captured_layer is None:
            return
        layer = self._stage.GetEditTarget().GetLayer()
        # Restoring the prim back into ``layer`` does not need ancestor
        # pre-creation because ``layer`` already authored the original
        # parent specs (we deleted only ``self._path``, not its parents).
        # If a future caller deletes the parent too, the parent's
        # ``DeletePrimCommand`` undoes first under ``UndoGroup`` ordering.
        Sdf.CopySpec(self._captured_layer, self._path, layer, self._path)


class NamespaceEditCommand(Command):
    """Move a prim path (rename or reparent) via Sdf.BatchNamespaceEdit.

    Undo swaps src and dst, restoring the original path. As with
    deletion, ``affects_namespace`` settles active property edit
    transactions before the namespace mutates.
    """

    affects_namespace = True

    def __init__(self, layer: Any, old_path: "Sdf.Path", new_path: "Sdf.Path") -> None:
        self._layer = layer
        self._old_path = old_path
        self._new_path = new_path

    def do(self) -> None:
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(self._old_path, self._new_path)
        self._layer.Apply(batch)

    def undo(self) -> None:
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(self._new_path, self._old_path)
        self._layer.Apply(batch)


class CameraPoseCommand(Command):
    """Undo/redo command for a selected USD camera pose write."""

    def __init__(
        self,
        stage: Any,
        camera_path: str,
        view_matrix: Any,
        target_world: Any,
    ) -> None:
        self._stage = stage
        self._camera_path = str(camera_path)
        self._view_matrix = tuple(
            tuple(float(value) for value in row)
            for row in view_matrix
        )
        self._target_world = (
            float(target_world[0]),
            float(target_world[1]),
            float(target_world[2]),
        )
        self._layer = stage.GetEditTarget().GetLayer()
        self._prim_path = Sdf.Path(self._camera_path)
        self._before = _CameraPoseSnapshot(self._layer, self._prim_path)
        self._after: _CameraPoseSnapshot | None = None

    def do(self) -> None:
        from ovui_data_adapters.openusd._camera_writer import (
            write_scene_camera_pose_from_matrices,
        )

        write_scene_camera_pose_from_matrices(
            self._stage,
            self._camera_path,
            self._view_matrix,
            self._target_world,
        )
        self._after = _CameraPoseSnapshot(self._layer, self._prim_path)

    def undo(self) -> None:
        self._before.restore(self._layer)

    def redo(self) -> None:
        if self._after is None:
            self.do()
            return
        self._after.restore(self._layer)
