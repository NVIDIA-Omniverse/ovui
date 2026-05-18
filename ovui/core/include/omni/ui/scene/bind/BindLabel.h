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

#include "BindAbstractShape.h"
#include "DocLabel.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Label                                                                                       \
    OMNIUI_PYBIND_INIT_AbstractShape                                                                                   \
    OMNIUI_PYBIND_INIT_CALL(color, setColor, pythonToColor4)                                                           \
    OMNIUI_PYBIND_INIT_CAST(size, setSize, float)                                                                      \
    OMNIUI_PYBIND_INIT_CAST(alignment, setAlignment, Alignment)                                                        \
    OMNIUI_PYBIND_INIT_CAST(text, setText, std::string)

#define OMNIUI_PYBIND_KWARGS_DOC_Label                                                                                 \
    "\n    `color : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Label_color                                                                                      \
    "\n    `size : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_Label_size                                                                                       \
    "\n    `alignment : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Label_alignment                                                                                  \
    "\n    `text : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_Label_text                                                                                       \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractShape
// clang-format on
