/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include "DocImage.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Image                                                                                       \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(alignment, setAlignment, Alignment)                                                        \
    OMNIUI_PYBIND_INIT_CAST(fill_policy, setFillPolicy, Image::FillPolicy)                                             \
    OMNIUI_PYBIND_INIT_CAST(pixel_aligned, setPixelAligned, bool)                                                      \
    OMNIUI_PYBIND_INIT_CALLBACK(progress_changed_fn, setProgressChangedFn, void(const float&))

#define OMNIUI_PYBIND_KWARGS_DOC_Image                                                                                 \
    "\n    `alignment : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Image_alignment                                                                                  \
    "\n    `fill_policy : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Image_fillPolicy                                                                                 \
    "\n    `pixel_aligned : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_Image_pixelAligned                                                                               \
    "\n    `progress_changed_fn : `\n        "                                                                         \
    OMNIUI_PYBIND_DOC_Image_progress                                                                                   \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
