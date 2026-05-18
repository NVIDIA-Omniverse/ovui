# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovwidgets.layers: USD layer-stack window package.

Public surface:

- :class:`LayerWindow` — dockable panel shell (LAYERS-PLAN Step 8).
- :class:`LayerItem` — per-row data object for the Layers tree
  (LAYERS-PLAN Step 12).
- :class:`LayerModel` — :class:`ui.AbstractItemModel` for the tree
  (LAYERS-PLAN Step 13).
- :class:`LayerDelegate` — per-cell renderer for the seven-column
  tree (LAYERS-PLAN Step 17).
- :class:`PrimSpecItem` — per-row data object for a single prim spec
  rendered under its layer (LAYERS-PLAN Step 48).
- :class:`LayerSelectionWatch` — observes tree-view selection and fires
  listeners on focused-layer changes (LAYERS-PLAN Step 55).
- :class:`LayerNameValueModel` — name-column value model with suffix
  and color-role state (LAYERS-PLAN Step 18).
- :class:`SaveValueModel` — column-2 dirty-and-saveable value model
  with click-to-save write surface (LAYERS-PLAN Step 19).
- :class:`LocalMuteValueModel` — column-3 local-mute value model
  with click-toggle write surface (LAYERS-PLAN Step 20).
- :class:`LockValueModel` — column-6 lock value model with
  click-toggle write surface (LAYERS-PLAN Step 21).
- :class:`AbstractLayerCommand` — common base class for every
  undoable layer mutation (LAYERS-PLAN Step 28). Individual concrete
  commands (Steps 29+) live in :mod:`ovwidgets.layers.commands` and are
  imported from there.

The USD-backed adapter (:class:`UsdLayerStackAdapter`) is not
re-exported here — import it from
:mod:`ovui_data_adapters.openusd` directly when ``pxr`` is available
(Step 15 of the data-adapters refactor relocated it out of widgets).
The :class:`LayerStackAdapter` ABC lives in
:mod:`ovui_data_adapters.common` (issue #38).
"""

from ovwidgets.layers.commands import AbstractLayerCommand
from ovwidgets.layers.context_menu import (
    ContextMenuBuilder,
    ContextMenuEntry,
    MenuContext,
)
from ovwidgets.layers.drop_visual_controller import DropVisualController
from ovwidgets.layers.layer_delegate import LayerDelegate
from ovwidgets.layers.layer_item import LayerItem
from ovwidgets.layers.layer_model import DefaultLayerSettings, LayerModel
from ovwidgets.layers.layer_settings import LAYER_SETTINGS_KEYS, LayerSettings
from ovwidgets.layers.models import (
    LayerNameValueModel,
    LocalMuteValueModel,
    LockValueModel,
    SaveAllValueModel,
    SaveValueModel,
)
from ovwidgets.layers.options_button import MENU_ITEMS as OPTIONS_MENU_ITEMS
from ovwidgets.layers.options_button import OptionsButton
from ovwidgets.layers.prim_spec_item import PrimSpecItem
from ovwidgets.layers.selection_watch import (
    LAYERS_SELECT_SOURCE,
    LayerSelectionWatch,
)
from ovwidgets.layers.window import LayerWindow

__all__ = [
    "AbstractLayerCommand",
    "ContextMenuBuilder",
    "ContextMenuEntry",
    "DefaultLayerSettings",
    "DropVisualController",
    "LAYERS_SELECT_SOURCE",
    "LAYER_SETTINGS_KEYS",
    "LayerDelegate",
    "LayerItem",
    "LayerModel",
    "LayerNameValueModel",
    "LayerSelectionWatch",
    "LayerSettings",
    "LayerWindow",
    "LocalMuteValueModel",
    "LockValueModel",
    "MenuContext",
    "OPTIONS_MENU_ITEMS",
    "OptionsButton",
    "PrimSpecItem",
    "SaveAllValueModel",
    "SaveValueModel",
]
