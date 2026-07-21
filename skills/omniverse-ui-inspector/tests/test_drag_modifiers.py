# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["OVUIINSPECT_ENABLED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ovuiinspect import (  # noqa: E402
    _IMGUI_KEY_LEFT_CTRL,
    _IMGUI_KEY_LEFT_SHIFT,
    _make_drag,
)


def test_drag_holds_modifiers_across_mouse_press_move_release() -> None:
    command = _make_drag(
        10,
        20,
        30,
        40,
        "left",
        5.0,
        steps_count=1,
        modifiers=["ctrl", "shift"],
    )

    ctrl_down = command.steps.index(("key", (_IMGUI_KEY_LEFT_CTRL, True)))
    shift_down = command.steps.index(("key", (_IMGUI_KEY_LEFT_SHIFT, True)))
    button_down = command.steps.index(("button", (0, True)))
    button_up = command.steps.index(("button", (0, False)))
    shift_up = command.steps.index(("key", (_IMGUI_KEY_LEFT_SHIFT, False)))
    ctrl_up = command.steps.index(("key", (_IMGUI_KEY_LEFT_CTRL, False)))

    assert ctrl_down < shift_down < button_down < button_up < shift_up < ctrl_up
