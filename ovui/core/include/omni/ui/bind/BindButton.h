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
