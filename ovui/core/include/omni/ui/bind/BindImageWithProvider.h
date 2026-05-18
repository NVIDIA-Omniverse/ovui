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
#include "DocImageWithProvider.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_ImageWithProvider                                                                           \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(alignment, setAlignment, Alignment)                                                        \
    OMNIUI_PYBIND_INIT_CAST(pixel_aligned, setPixelAligned, bool)                                                      \
    OMNIUI_PYBIND_INIT_CAST(fill_policy, setFillPolicy, ImageWithProvider::FillPolicy)

#define OMNIUI_PYBIND_KWARGS_DOC_ImageWithProvider                                                                     \
    "\n    `alignment : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_ImageWithProvider_alignment                                                                      \
    "\n    `fill_policy : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_ImageWithProvider_fillPolicy                                                                     \
    "\n    `pixel_aligned : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_ImageWithProvider_pixelAligned                                                                   \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
