# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovui_widgets.layers: USD layer-stack window package.

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
  commands (Steps 29+) live in :mod:`ovui_widgets.layers.commands` and are
  imported from there.

The USD-backed adapter (:class:`UsdLayerStackAdapter`) is not
re-exported here — import it from
:mod:`ovui_data_adapters.openusd` directly when ``pxr`` is available
(Step 15 of the data-adapters refactor relocated it out of widgets).
The :class:`LayerStackAdapter` ABC lives in
:mod:`ovui_data_adapters.common` (issue #38).
"""

from ovui_widgets.layers.commands import AbstractLayerCommand
from ovui_widgets.layers.context_menu import (
    ContextMenuBuilder,
    ContextMenuEntry,
    MenuContext,
)
from ovui_widgets.layers.drop_visual_controller import DropVisualController
from ovui_widgets.layers.layer_delegate import LayerDelegate
from ovui_widgets.layers.layer_item import LayerItem
from ovui_widgets.layers.layer_model import DefaultLayerSettings, LayerModel
from ovui_widgets.layers.layer_settings import LAYER_SETTINGS_KEYS, LayerSettings
from ovui_widgets.layers.models import (
    LayerNameValueModel,
    LocalMuteValueModel,
    LockValueModel,
    SaveAllValueModel,
    SaveValueModel,
)
from ovui_widgets.layers.options_button import MENU_ITEMS as OPTIONS_MENU_ITEMS
from ovui_widgets.layers.options_button import OptionsButton
from ovui_widgets.layers.prim_spec_item import PrimSpecItem
from ovui_widgets.layers.selection_watch import (
    LAYERS_SELECT_SOURCE,
    LayerSelectionWatch,
)
from ovui_widgets.layers.window import LayerWindow

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
