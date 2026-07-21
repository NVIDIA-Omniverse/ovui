# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stage Browser dockable window shell (widget-window split).

Houses :class:`StageWindow` — the :class:`ManagedWindow` that hosts the
embeddable :class:`StageWidget`. See the stage hierarchy behavior for the
widget/window split this realises.
"""

from ovui_widgets.stage.window.stage_window import StageWindow

__all__ = ["StageWindow"]
