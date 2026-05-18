# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Name-column value model for the Layers ``TreeView`` (LAYERS-PLAN Step 18).

:class:`LayerNameValueModel` is the :class:`omni.ui.AbstractValueModel`
that drives column 0 of the Layers tree. It concatenates the layer's
display name with a state-specific parenthetical suffix
("(Authoring Layer)", "(Missing)", "(Read Only)") or the Step-27
trailing ``[anon]`` tag for anonymous layers, and exposes a
``color_role`` string the delegate routes into the
``Layers.NameLabel::<role>`` style selector.

Color roles:

- ``"missing"`` — the layer could not be resolved on disk. Paints in the
  red ``cl.layers_label_missing`` tint.
- ``"disabled"`` — the layer is muted or locked (either directly or
  because an ancestor is — Step 32's mute/lock cascade); it contributes
  nothing to composition or is guarded against edits. Paints in the
  gray ``cl.layers_label_disabled`` tint.
- ``"edit_target"`` — the authoring layer. Paints in the accent tint
  defined for ``Layers.NameLabel::edit_target`` in
  :mod:`ovwidgets.layers.style`.
- ``"anonymous"`` — Step 27: in-memory / unsaved layer. Paints in the
  muted ``cl.text_secondary`` tint so the row reads as "less committed"
  than a backed-on-disk layer (the ovui style dict has no first-class
  italic toggle, so the visual differentiation rides on the suffix tag
  plus this softer hue rather than font slant).
- ``"normal"`` — default ``cl.text_primary`` color (no state override).

Precedence matches LAYERS-WINDOW-ARCHITECTURE: missing > disabled (mute
/ lock) > edit target > anonymous > normal. A missing or muted layer
can still be the edit target in the adapter model, but the Layers
window reports the more severe state because the commands blocked by
it are the ones the user most needs to see. Anonymous sits below
edit_target because the authoring-layer signal is load-bearing for
current-action feedback — a user editing the session layer still sees
the green row + green icon, with the ``[anon]`` suffix and the
italic-feel tint demoted to the "anonymous" state only when the row
is not currently being authored.

The model is **stateless read-through**: every
:meth:`get_value_as_string` / :meth:`get_color_role` call re-queries
the layer item's flags (which themselves go through the adapter via
:meth:`ovwidgets.layers.layer_item.LayerItem.refresh_flags`). Step 19+ use
the same pattern for their per-column models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import omni.ui as ui
from ovui_data_adapters.common import LayerHandle

if TYPE_CHECKING:  # pragma: no cover — type-hint guard
    from ovwidgets.layers.layer_item import LayerItem
    from ovwidgets.layers.layer_model import LayerModel


# Suffix constants mirror LAYERS-WINDOW-ARCHITECTURE verbiage exactly so
# the presentation string stays stable across adapter swaps and tests.
# Step 27 swaps the long ``(Anonymous)`` parenthetical for the terse
# ``[anon]`` tag — brackets read as metadata (matching Blender / Maya
# layer panels) and the shorter form saves horizontal space on the
# session row where the authoring-layer green row already dominates the
# visual hierarchy.
_SUFFIX_EDIT_TARGET = " (Authoring Layer)"
_SUFFIX_MISSING = " (Missing)"
_SUFFIX_ANONYMOUS = " [anon]"
_SUFFIX_READ_ONLY = " (Read Only)"

# Color role strings — passed as the ``name=...`` kwarg on the
# ``Layers.NameLabel`` ``ui.Label`` so the style pass picks the right
# ``Layers.NameLabel::<role>`` override. Kept as a frozenset so the
# delegate can validate its dispatch during tests without importing the
# palette.
COLOR_ROLE_MISSING = "missing"
COLOR_ROLE_DISABLED = "disabled"
COLOR_ROLE_EDIT_TARGET = "edit_target"
COLOR_ROLE_ANONYMOUS = "anonymous"
COLOR_ROLE_NORMAL = "normal"

ALL_COLOR_ROLES = frozenset(
    {
        COLOR_ROLE_MISSING,
        COLOR_ROLE_DISABLED,
        COLOR_ROLE_EDIT_TARGET,
        COLOR_ROLE_ANONYMOUS,
        COLOR_ROLE_NORMAL,
    }
)


class LayerNameValueModel(ui.AbstractValueModel):
    """Column-0 value model: display name + suffix + color role."""

    def __init__(
        self,
        layer_model: "LayerModel",
        layer_item: "LayerItem",
    ) -> None:
        super().__init__()
        self._model = layer_model
        self._item = layer_item

    # ── Read surface ─────────────────────────────────────────────────

    def get_value_as_string(self) -> str:
        """Return the composed label: ``"<display name><suffix>"``.

        Suffix precedence (highest wins):

        1. ``(Missing)`` — the layer file could not be resolved. Kit
           shows this in every layer-window toolkit so the operator
           knows a reload / remap is needed before saving.
        2. ``[anon]`` — in-memory only; no backing file yet. Step 27
           shortened the Step-18 ``(Anonymous)`` parenthetical to the
           bracket tag so the session row reads more tersely (the
           delegate pairs the tag with a softer label hue so the state
           is still distinct at a glance).
        3. ``(Read Only)`` — file exists but is not writable by the
           current user. Authoring the layer will fail at save time.
        4. ``(Authoring Layer)`` — this row is the current edit target.
           Only shown when no more-severe suffix applies because an
           edit target that is missing / read-only / anonymous is
           already visually flagged by the higher-precedence suffix;
           doubling up would crowd the label.
        """
        adapter = self._model.adapter
        item = self._item
        if adapter is None:
            # Late callback after the window detached the adapter.
            # Returning an empty string keeps ovui's paint pass safe;
            # the row will be removed on the next rebuild.
            return ""
        base = adapter.get_display_name(LayerHandle(item.identifier))
        if item.is_missing:
            return f"{base}{_SUFFIX_MISSING}"
        if item.is_anonymous:
            return f"{base}{_SUFFIX_ANONYMOUS}"
        if item.is_read_only:
            return f"{base}{_SUFFIX_READ_ONLY}"
        if item.is_edit_target:
            return f"{base}{_SUFFIX_EDIT_TARGET}"
        return base

    def get_color_role(self) -> str:
        """Return the style-selector role for the label's color.

        Precedence: missing > disabled (mute / lock) > edit target >
        anonymous > normal. Returned value is always one of
        :data:`ALL_COLOR_ROLES` so the delegate can feed it straight
        into ``style_type_name_override="Layers.NameLabel"`` + ``name=``.

        The Step-27 ``anonymous`` role sits below ``edit_target`` so an
        anonymous authoring layer (session layer picked as the edit
        target) still paints its label in the green authoring tint —
        the "[anon]" suffix + the italic-feel anonymous tint only take
        over for non-authoring anonymous rows, where the softer hue
        reads as "not yet committed to disk" without fighting the
        authoring-layer signal.
        """
        item = self._item
        if item.is_missing:
            return COLOR_ROLE_MISSING
        # Step 32 mute/lock cascade: a muted or locked ancestor dims
        # every descendant row too (LAYERS-WINDOW-ARCHITECTURE §17.4).
        # Reading through the ``…_or_parent_…`` properties walks the
        # parent chain, so an ancestor toggle is reflected on the very
        # next repaint without needing the descendants' flag cache to
        # be invalidated.
        if item.muted_or_parent_muted or item.locked_or_parent_locked:
            return COLOR_ROLE_DISABLED
        if item.is_edit_target:
            return COLOR_ROLE_EDIT_TARGET
        if item.is_anonymous:
            return COLOR_ROLE_ANONYMOUS
        return COLOR_ROLE_NORMAL
