# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Standalone port of Kit's test_label.py"""

from test_base import OmniUiTest
import omni.ui as ui


class TestLabel(OmniUiTest):
    """Testing ui.Label"""

    async def test_general(self):
        """Testing general properties of ui.Label"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack(height=0):
                # Simple text
                ui.Label("Hello world")

                # Word wrap
                ui.Label(
                    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut "
                    "labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco "
                    "laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in "
                    "voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat "
                    "non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
                    word_wrap=True,
                )

                # Computing text size
                with ui.HStack(width=0):
                    ui.Label("A")
                    ui.Label("BC")
                    ui.Label("DEF")
                    ui.Label("GHIjk")
                    ui.Label("lmnopq")
                    ui.Label("rstuvwxyz")

                # Styling
                ui.Label("Red", style={"color": 0xFF0000FF})
                ui.Label("Green", style={"Label": {"color": 0xFF00FF00}})
                ui.Label("Blue", style_type_name_override="TreeView", style={"TreeView": {"color": 0xFFFF0000}})

        await self.finalize_test()

    async def test_alignment(self):
        """Testing alignment of ui.Label"""
        window = await self.create_test_window()

        with window.frame:
            with ui.ZStack():
                ui.Label("Left Top", alignment=ui.Alignment.LEFT_TOP)
                ui.Label("Center Top", alignment=ui.Alignment.CENTER_TOP)
                ui.Label("Right Top", alignment=ui.Alignment.RIGHT_TOP)

                ui.Label("Left Center", alignment=ui.Alignment.LEFT_CENTER)
                ui.Label("Center", alignment=ui.Alignment.CENTER)
                ui.Label("Right Center", alignment=ui.Alignment.RIGHT_CENTER)

                ui.Label("Left Bottom", alignment=ui.Alignment.LEFT_BOTTOM)
                ui.Label("Center Bottom", alignment=ui.Alignment.CENTER_BOTTOM)
                ui.Label("Right Bottom", alignment=ui.Alignment.RIGHT_BOTTOM)

        await self.finalize_test()

    async def test_wrap_alignment(self):
        """Testing alignment of ui.Label with word_wrap"""
        window = await self.create_test_window()

        with window.frame:
            ui.Label(
                "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut "
                "labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco "
                "laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in "
                "voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat "
                "non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
                word_wrap=True,
                style={"Label": {"alignment": ui.Alignment.CENTER}},
            )

        await self.finalize_test()

    async def test_elide(self):
        """Testing ui.Label with elided_text"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack():
                ui.Label(
                    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut "
                    "labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco "
                    "laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in "
                    "voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat "
                    "non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
                    elided_text=True,
                    height=0,
                )
                ui.Label(
                    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut "
                    "labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco "
                    "laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in "
                    "voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat "
                    "non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
                    word_wrap=True,
                    elided_text=True,
                )
                ui.Label(
                    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut "
                    "labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco "
                    "laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in "
                    "voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat "
                    "non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
                    alignment=ui.Alignment.CENTER,
                    word_wrap=True,
                    elided_text=True,
                )

        await self.next_frame()
        await self.finalize_test()

    async def test_change_size(self):
        """Testing how ui.Label dynamically changes size"""
        window = await self.create_test_window()

        with window.frame:
            with ui.VStack(style={"Rectangle": {"background_color": 0xFFFFFFFF}}):
                with ui.HStack(height=0):
                    with ui.Frame(width=0):
                        line1 = ui.Label("Test")
                    ui.Rectangle()
                with ui.HStack(height=0):
                    with ui.Frame(width=0):
                        line2 = ui.Label("Test")
                    ui.Rectangle()

                with ui.Frame(height=0):
                    line3 = ui.Label("Test", word_wrap=True)
                ui.Rectangle()

        for i in range(2):
            await self.next_frame()

        # Change the text
        line1.text = "Bigger than before"
        line2.text = "a"
        line3.text = (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut "
            "labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco "
            "laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in "
            "voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat "
            "non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."
        )

        await self.next_frame()
        await self.finalize_test()

    async def test_font(self):
        window = await self.create_test_window()

        with window.frame:
            ui.Label(
                "The quick brown fox jumps over the lazy dog",
                style={"font_size": 55, "font": "${fonts}/OpenSans-SemiBold.ttf", "alignment": ui.Alignment.CENTER},
                word_wrap=True,
            )

        await self.finalize_test()

    async def test_invalid_font(self):
        window = await self.create_test_window()

        with window.frame:
            ui.Label(
                "The quick brown fox jumps over the lazy dog",
                style={"font_size": 55, "font": "${fonts}/IDoNotExist.ttf", "alignment": ui.Alignment.CENTER},
                word_wrap=True,
            )

        await self.finalize_test()

    # SKIPPED: test_mouse_released_fn -- requires omni.kit.ui_test (mouse emulation)
    # SKIPPED: test_exact_content_size -- relies on exact pixel metrics that may differ in standalone
