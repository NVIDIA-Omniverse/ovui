# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Value models for the Layers widget (LAYERS-PLAN Step 18+).

Each class is a thin :class:`omni.ui.AbstractValueModel` subclass that
translates :class:`~ovui_widgets.common.adapters.LayerStackAdapter` state into the
shape the Layers ``TreeView`` delegate expects for a single column.

Kept in its own subpackage so Step 22 can drop in ``LiveValueModel`` /
``LayerLatestModel`` alongside the existing column models without
bloating :mod:`ovui_widgets.layers.layer_model`.
"""

from ovui_widgets.layers.models.layer_name_model import LayerNameValueModel
from ovui_widgets.layers.models.lock_model import LockValueModel
from ovui_widgets.layers.models.mute_model import LocalMuteValueModel
from ovui_widgets.layers.models.save_all_model import SaveAllValueModel
from ovui_widgets.layers.models.save_model import SaveValueModel

__all__ = [
    "LayerNameValueModel",
    "LocalMuteValueModel",
    "LockValueModel",
    "SaveAllValueModel",
    "SaveValueModel",
]
