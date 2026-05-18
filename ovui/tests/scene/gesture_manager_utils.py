# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""The utilities for ui.scene test"""
from omni.ui_scene import scene as sc


class Manager(sc.GestureManager):
    def __init__(self, mouse_action_sequence, mouse_position_sequence, scene_view):
        """
        The gesture manager takes inputs to mimic the mouse operations for tests

        Args:
            mouse_action_sequence: a List which contains a sequence of (input.clicked, input.down, input.released)
            mouse_position_sequence: a List which contains a sequence of (input.mouse[0], input.mouse[1])
        """
        super().__init__()
        # The sequence of actions. In the future we need a way to record it.
        # mimic the mouse click, hold and move
        self.mouse_action_sequence = mouse_action_sequence
        self.mouse_position_sequence = mouse_position_sequence
        if len(self.mouse_action_sequence) != len(self.mouse_position_sequence):
            raise Exception(f"the mouse action sequence length doesn't match the mouse position sequence")
        self.scene_view = scene_view
        self.counter = 0

    def amend_input(self, input):
        if self.counter >= len(self.mouse_action_sequence):
            # Don't amentd anything.
            return input

        # Move mouse
        input.mouse[0], input.mouse[1] = self.mouse_position_sequence[self.counter]

        # Get 3D cords of the mouse
        origin, direction = self.scene_view.get_ray_from_ndc(input.mouse)
        input.mouse_origin = origin
        input.mouse_direction = direction

        # Click, move and release
        input.clicked, input.down, input.released = self.mouse_action_sequence[self.counter]
        self.counter += 1

        return input
