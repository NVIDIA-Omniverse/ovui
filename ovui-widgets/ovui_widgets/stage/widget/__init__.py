# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stage Browser widget subpackage.

Houses the embeddable Stage Browser widget and its supporting modules:
tree model, column delegate, filter pipeline, and rename / drop-visual
controllers. See the stage implementation step 6 for the split; the stage hierarchy behavior
for the widget/window separation this carve-out prepares for.
"""

from ovui_widgets.stage.widget.drop_visual_controller import DropVisualController
from ovui_widgets.stage.widget.filter_pipeline import FilterPipeline, make_name_filter
from ovui_widgets.stage.widget.hierarchy_model import DRAG_MIME, HierarchyItem, HierarchyModel
from ovui_widgets.stage.widget.rename_controller import RenameController
from ovui_widgets.stage.widget.stage_delegate import StageDelegate
from ovui_widgets.stage.widget.stage_widget import StageWidget

__all__ = [
    "DRAG_MIME",
    "DropVisualController",
    "FilterPipeline",
    "HierarchyItem",
    "HierarchyModel",
    "RenameController",
    "StageDelegate",
    "StageWidget",
    "make_name_filter",
]
