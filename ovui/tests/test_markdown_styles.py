# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Smoke tests for reusable MarkdownWidget Python styles."""

import unittest

import omni.ui as ui


class TestMarkdownStyles(unittest.TestCase):
    def test_named_markdown_styles(self):
        for name in ("white", "dark-blue", "black"):
            theme = ui.markdown_theme(name, table_policy="content-fit")
            self.assertIsInstance(theme["background"], int)
            self.assertIn("MarkdownWidget", theme["style"])
            self.assertIn("MarkdownWidget.Table", theme["style"])
            self.assertEqual(theme["style"]["MarkdownWidget.Table"]["layout_policy"], "content-fit")
            self.assertIn("MarkdownWidget.CodeBlock.Keyword", theme["style"])
            self.assertIn("MarkdownWidget.Alert.Note", theme["style"])

    def test_styles_are_fresh_copyable_dicts(self):
        first = ui.markdown_style("black")
        second = ui.markdown_style("black")
        first["MarkdownWidget"]["color"] = 0
        self.assertNotEqual(first["MarkdownWidget"]["color"], second["MarkdownWidget"]["color"])

    def test_aliases(self):
        self.assertEqual(ui.markdown_background("light"), ui.markdown_background("white"))
        self.assertEqual(ui.markdown_background("blue"), ui.markdown_background("dark-blue"))
        self.assertEqual(ui.markdown_background("default"), ui.markdown_background("black"))


if __name__ == "__main__":
    unittest.main()
