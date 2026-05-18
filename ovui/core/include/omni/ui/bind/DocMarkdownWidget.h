/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#define OMNIUI_PYBIND_DOC_MarkdownWidget                                                                               \
    "Native ImGui markdown renderer.\n"                                                                                \
    "\n"                                                                                                               \
    "Parses CommonMark + GitHub flavored markdown via md4c on assignment\n"                                            \
    "to ``text``.  All rendering happens via direct ImGui draw calls --\n"                                             \
    "no child widgets are created.  Wrap inside a ScrollingFrame for\n"                                                \
    "long documents.\n"

#define OMNIUI_PYBIND_DOC_MarkdownWidget_text "Raw markdown source for the widget.\n"

#define OMNIUI_PYBIND_DOC_MarkdownWidget_MarkdownWidget                                                                \
    "Create a markdown widget rendering ``text``.\n"                                                                   \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `text :`\n"                                                                                                   \
    "        The markdown source string.\n"

#define OMNIUI_PYBIND_DOC_MarkdownWidget_LinkClicked                                                                   \
    "Fired with a single ``url`` argument when the user clicks an inline link.\n"

#define OMNIUI_PYBIND_DOC_MarkdownWidget_ImageUrlProvider                                                              \
    "Optional callback for custom image URL resolution.\n"                                                             \
    "\n"                                                                                                               \
    "Receives the image ``src`` string from markdown and should return a\n"                                            \
    "resolved file path, or empty string to fall back to the default resolver.\n"
