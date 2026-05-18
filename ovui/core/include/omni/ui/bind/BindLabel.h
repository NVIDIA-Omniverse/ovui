/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "BindUtils.h"
#include "BindWidget.h"
#include "DocLabel.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Label                                                                                       \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(alignment, setAlignment, Alignment)                                                        \
    OMNIUI_PYBIND_INIT_CAST(word_wrap, setWordWrap, bool)                                                              \
    OMNIUI_PYBIND_INIT_CAST(elided_text, setElidedText, bool)                                                          \
    OMNIUI_PYBIND_INIT_CAST(elided_text_str, setElidedTextStr, std::string)                                            \
    OMNIUI_PYBIND_INIT_CAST(hide_text_after_hash, setHideTextAfterHash, bool)

// clang-format off
#define OMNIUI_PYBIND_KWARGS_DOC_Label                                                                                 \
    "\n    `alignment : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Label_alignment                                                                                  \
    "\n    `word_wrap : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Label_wordWrap                                                                                   \
    "\n    `elided_text : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Label_elidedText                                                                                 \
    "\n    `elided_text_str : `\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Label_elidedTextStr                                                                              \
    "\n    `hide_text_after_hash : `\n        "                                                                        \
    OMNIUI_PYBIND_DOC_Label_hideTextAfterHash                                                                          \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
