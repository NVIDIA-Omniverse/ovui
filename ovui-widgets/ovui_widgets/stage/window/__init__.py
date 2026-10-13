# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stage Browser dockable window shell (widget-window split).

Houses :class:`StageWindow` — the :class:`ManagedWindow` that hosts the
embeddable :class:`StageWidget`. See the stage hierarchy behavior for the
widget/window split this realises.
"""

from ovui_widgets.stage.window.stage_window import StageWindow

__all__ = ["StageWindow"]
