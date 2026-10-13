/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindInvisibleButton.h"
#include "DocButton.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Button                                                                                      \
    OMNIUI_PYBIND_INIT_InvisibleButton                                                                                 \
    OMNIUI_PYBIND_INIT_CAST(text, setText, std::string)                                                                \
    OMNIUI_PYBIND_INIT_CAST(image_url, setImageUrl, std::string)                                                       \
    OMNIUI_PYBIND_INIT_CALL(image_width, setImageWidth, toLength)                                                      \
    OMNIUI_PYBIND_INIT_CALL(image_height, setImageHeight, toLength)                                                    \
    OMNIUI_PYBIND_INIT_CAST(spacing, setSpacing, float)

#define OMNIUI_PYBIND_KWARGS_DOC_Button                                                                                \
    "\n    `text : str`\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_Button_text                                                                                      \
    "\n    `image_url : str`\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Button_imageUrl                                                                                  \
    "\n    `image_width : float`\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Button_imageWidth                                                                                \
    "\n    `image_height : float`\n        "                                                                           \
    OMNIUI_PYBIND_DOC_Button_imageHeight                                                                               \
    "\n    `spacing : float`\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Button_spacing                                                                                   \
    OMNIUI_PYBIND_KWARGS_DOC_InvisibleButton
// clang-format on
