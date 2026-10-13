/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
