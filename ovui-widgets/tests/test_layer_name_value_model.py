# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovui_widgets.layers.models.layer_name_model.LayerNameValueModel`
(LAYERS-PLAN Step 18, Step 27).

Covers the plan's Verify bullet — every suffix combination plus the
five color roles — and pins the precedence ordering so a later refactor
can't silently reshuffle the label text. Suffix precedence is
``missing > anonymous > read_only > edit_target > normal``; color-role
precedence is ``missing > disabled (mute|lock) > edit_target >
anonymous > normal``. Step 27 swapped the Step-18 ``(Anonymous)``
parenthetical for the terser ``[anon]`` bracket tag and added the
``anonymous`` color role so the italic-feel hue can land without a
dedicated italic font file.
"""

from __future__ import annotations

import omni.ui as ui
import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.layers import LayerModel, LayerNameValueModel
from ovui_widgets.layers.models.layer_name_model import (
    ALL_COLOR_ROLES,
    COLOR_ROLE_ANONYMOUS,
    COLOR_ROLE_DISABLED,
    COLOR_ROLE_EDIT_TARGET,
    COLOR_ROLE_MISSING,
    COLOR_ROLE_NORMAL,
)


@pytest.fixture
def model_with_root() -> "tuple[MockLayerStackAdapter, LayerModel]":
    """Fresh adapter + model pair seeded with the default root/session.

    Every test owns an independent model so flag-cache mutations don't
    leak across cases. Step 24 applies the adapter's initial edit
    target on construction (the mock defaults it to the root layer),
    so we immediately clear it here to give each test a neutral
    baseline — tests that want the authoring suffix or the
    edit-target color role opt in explicitly by flipping
    ``model.root_item.is_edit_target`` or calling
    ``adapter.set_edit_target``.
    """
    adapter = MockLayerStackAdapter(include_session=True)
    model = LayerModel(adapter)
    model._update_edit_target("")
    yield adapter, model
    model.destroy()


# ─── Construction / identity ──────────────────────────────────────────────────


class TestConstruction:
    def test_is_abstract_value_model(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        assert isinstance(vm, LayerNameValueModel)
        assert isinstance(vm, ui.AbstractValueModel)

    def test_holds_model_and_item_back_references(
        self, model_with_root
    ) -> None:
        # Delegate / future Step 21 code navigates back through these
        # references; pinning them here guards against an accidental
        # rename during the Step 19+ rollout.
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm._model is model
        assert vm._item is model.root_item

    def test_cached_on_layer_item(self, model_with_root) -> None:
        _, model = model_with_root
        first = model.get_item_value_model(model.root_item, 0)
        second = model.get_item_value_model(model.root_item, 0)
        assert first is second
        assert model.root_item._name_model is first

    def test_distinct_instances_per_item(self, model_with_root) -> None:
        _, model = model_with_root
        root_vm = model.get_item_value_model(model.root_item, 0)
        session_vm = model.get_item_value_model(model.session_item, 0)
        assert root_vm is not session_vm
        assert root_vm._item is model.root_item
        assert session_vm._item is model.session_item


# ─── get_value_as_string — suffix matrix ─────────────────────────────────────


class TestSuffix:
    def test_plain_layer_has_no_suffix(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_value_as_string() == "root"

    def test_edit_target_suffix(self, model_with_root) -> None:
        _, model = model_with_root
        model.root_item.is_edit_target = True
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_value_as_string() == "root (Authoring Layer)"

    def test_missing_suffix(self, model_with_root) -> None:
        # Flag missing directly on the mock record. The adapter's
        # public :meth:`set_missing` fires ``INFO_CHANGED`` which
        # :class:`LayerModel` treats as structural (until Step 21
        # introduces the flag-only pathway) — that would rebuild the
        # tree and orphan the ``LayerItem`` instance we're testing.
        adapter, model = model_with_root
        adapter._layers[ROOT_LAYER_IDENTIFIER].missing = True
        model.root_item.invalidate_flags()
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_value_as_string() == "root (Missing)"

    def test_anonymous_suffix(self, model_with_root) -> None:
        # Session layer is anonymous by default in the mock adapter.
        # Step 27 swapped the Step-18 "(Anonymous)" parenthetical for
        # the terser "[anon]" bracket tag — the delegate pairs the tag
        # with the anonymous color role so the italic-feel cue lands
        # without a dedicated italic font file.
        _, model = model_with_root
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_value_as_string() == "session [anon]"

    def test_read_only_suffix(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter.set_read_only(ROOT_LAYER_IDENTIFIER, True)
        model.root_item.invalidate_flags()
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_value_as_string() == "root (Read Only)"

    def test_missing_beats_anonymous(self, model_with_root) -> None:
        # Session layer is anonymous; flip it to missing too and the
        # severe suffix wins. Direct mutation for the same reason as
        # :meth:`test_missing_suffix`.
        adapter, model = model_with_root
        session_id = model.session_item.identifier
        adapter._layers[session_id].missing = True
        model.session_item.invalidate_flags()
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_value_as_string() == "session (Missing)"

    def test_missing_beats_edit_target(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter._layers[ROOT_LAYER_IDENTIFIER].missing = True
        model.root_item.invalidate_flags()
        model.root_item.is_edit_target = True
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_value_as_string() == "root (Missing)"

    def test_anonymous_beats_read_only(self, model_with_root) -> None:
        # Hypothetical edge — an anonymous layer backed by a read-only
        # file path. The plan gives anonymous higher precedence because
        # a user acting on the row needs the "no disk path yet" signal
        # before they need the permission warning. Step-27 form:
        # "[anon]" suffix.
        adapter, model = model_with_root
        session_id = model.session_item.identifier
        adapter.set_read_only(session_id, True)
        model.session_item.invalidate_flags()
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_value_as_string() == "session [anon]"

    def test_read_only_beats_edit_target(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter.set_read_only(ROOT_LAYER_IDENTIFIER, True)
        model.root_item.invalidate_flags()
        model.root_item.is_edit_target = True
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_value_as_string() == "root (Read Only)"

    def test_detached_adapter_returns_empty_string(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        # Clear the adapter reference the way Step 15 / destroy does.
        model._adapter = None
        assert vm.get_value_as_string() == ""


# ─── get_color_role — state matrix ───────────────────────────────────────────


class TestColorRole:
    def test_normal_layer_returns_normal(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_NORMAL

    def test_missing_returns_missing(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter._layers[ROOT_LAYER_IDENTIFIER].missing = True
        model.root_item.invalidate_flags()
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_MISSING

    def test_muted_returns_disabled(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        model.root_item.invalidate_flags()
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_DISABLED

    def test_locked_returns_disabled(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        model.root_item.invalidate_flags()
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_DISABLED

    def test_edit_target_returns_edit_target(self, model_with_root) -> None:
        _, model = model_with_root
        model.root_item.is_edit_target = True
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_EDIT_TARGET

    def test_missing_beats_disabled(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        adapter._layers[ROOT_LAYER_IDENTIFIER].missing = True
        model.root_item.invalidate_flags()
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_MISSING

    def test_disabled_beats_edit_target(self, model_with_root) -> None:
        # Muted edit target — the disabled signal is more load-bearing
        # than the authoring marker because edits to a muted layer
        # won't compose until it's unmuted.
        adapter, model = model_with_root
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        model.root_item.invalidate_flags()
        model.root_item.is_edit_target = True
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_DISABLED

    def test_color_role_always_in_allowed_set(self, model_with_root) -> None:
        # Every branch of ``get_color_role`` must hand back one of the
        # four whitelisted strings so the delegate's ``name=<role>``
        # style lookup always hits a declared variant. ``missing`` is
        # set via the mock record so the structural INFO_CHANGED
        # pathway doesn't rebuild the item mid-loop.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        record = adapter._layers[ROOT_LAYER_IDENTIFIER]
        for mutate in (
            lambda: None,
            lambda: adapter.set_mute(ROOT_LAYER_IDENTIFIER, True),
            lambda: adapter.set_lock(ROOT_LAYER_IDENTIFIER, True),
            lambda: setattr(record, "missing", True),
        ):
            mutate()
            model.root_item.invalidate_flags()
            assert vm.get_color_role() in ALL_COLOR_ROLES


# ─── Integration through LayerModel.get_item_value_model ─────────────────────


class TestIntegration:
    def test_value_model_picks_up_flag_invalidation(
        self, model_with_root
    ) -> None:
        # The model is read-through; flipping a flag + invalidating the
        # cache must flow through without re-constructing the value
        # model (which is cached on the item). Poke the underlying mock
        # record directly rather than going through
        # :meth:`set_missing` — the adapter event there is classified
        # as structural by :class:`LayerModel`, which would rebuild
        # ``model.root_item`` and leave the captured ``vm`` pointing at
        # the previous instance. Step 21 will add a non-structural
        # "flag only" pathway; until then this is the cleanest way to
        # exercise just the value-model read.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_NORMAL
        adapter._layers[ROOT_LAYER_IDENTIFIER].missing = True
        model.root_item.invalidate_flags()
        assert vm.get_color_role() == COLOR_ROLE_MISSING
        assert vm.get_value_as_string() == "root (Missing)"

    def test_edit_target_suffix_toggle(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_value_as_string() == "root"
        model.root_item.is_edit_target = True
        assert vm.get_value_as_string() == "root (Authoring Layer)"
        model.root_item.is_edit_target = False
        assert vm.get_value_as_string() == "root"


# ─── Step 27 — anonymous color role + bracket suffix ────────────────────────


class TestStep27Anonymous:
    """Step 27 — anonymous layers gain a bracket suffix + color role.

    The Step-18 ``(Anonymous)`` parenthetical collapses to the terse
    ``[anon]`` tag and a new ``anonymous`` color role (soft
    ``text_secondary`` tint) gives the delegate a "not yet saved"
    visual cue without needing a dedicated italic font.
    """

    def test_anonymous_role_included_in_allowed_set(self) -> None:
        # The delegate's ``name=<role>`` lookup will silently fall
        # through to the base ``Layers.NameLabel`` entry if the role
        # string is unknown — pinning the whitelist here guards
        # against a Step-27 regression that would erase the italic-feel
        # tint.
        assert COLOR_ROLE_ANONYMOUS in ALL_COLOR_ROLES
        assert COLOR_ROLE_ANONYMOUS == "anonymous"

    def test_anonymous_role_on_plain_anonymous_row(
        self, model_with_root
    ) -> None:
        # Session layer is anonymous by default; with no higher
        # precedence state active, the color role collapses to
        # anonymous.
        _, model = model_with_root
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_ANONYMOUS

    def test_edit_target_beats_anonymous(self, model_with_root) -> None:
        # Authoring session layer — green edit-target role wins so
        # the user's active-layer cue stays load-bearing. The [anon]
        # suffix + the green tint together still signal "this authoring
        # layer lives in memory only".
        _, model = model_with_root
        model.session_item.is_edit_target = True
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_EDIT_TARGET

    def test_disabled_beats_anonymous(self, model_with_root) -> None:
        # Muted anonymous layer — the "row is off" signal wins so the
        # user can't mistake a muted anonymous row for a quiet
        # secondary-text label.
        adapter, model = model_with_root
        session_id = model.session_item.identifier
        adapter.set_mute(session_id, True)
        model.session_item.invalidate_flags()
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_DISABLED

    def test_missing_beats_anonymous_role(self, model_with_root) -> None:
        # Even for an anonymous row, a missing backing reads red
        # (unresolved trumps unsaved for urgency).
        adapter, model = model_with_root
        session_id = model.session_item.identifier
        adapter._layers[session_id].missing = True
        model.session_item.invalidate_flags()
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_MISSING

    def test_non_anonymous_row_keeps_normal_role(
        self, model_with_root
    ) -> None:
        # Root layer is not anonymous in the mock adapter; color role
        # must stay ``normal`` so the anonymous tint doesn't leak onto
        # every non-authoring row.
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 0)
        assert vm.get_color_role() == COLOR_ROLE_NORMAL

    def test_anonymous_suffix_shape(self, model_with_root) -> None:
        # Exact string contract — Step 27 form is bracket-wrapped +
        # lowercase so the tag reads as metadata rather than prose.
        _, model = model_with_root
        vm = model.get_item_value_model(model.session_item, 0)
        assert vm.get_value_as_string().endswith(" [anon]")

    def test_all_color_roles_size_five(self) -> None:
        # Guards against accidental role removal on rename — Step 27
        # has exactly five roles (missing, disabled, edit_target,
        # anonymous, normal).
        assert len(ALL_COLOR_ROLES) == 5
