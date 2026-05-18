/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "BindContainer.h"
#include "BindUtils.h"
#include "DocFrame.h"
#include "DocRasterHelper.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Frame                                                                                       \
    OMNIUI_PYBIND_INIT_Container                                                                                       \
    OMNIUI_PYBIND_INIT_CAST(horizontal_clipping, setHorizontalClipping, bool)                                          \
    OMNIUI_PYBIND_INIT_CAST(vertical_clipping, setVerticalClipping, bool)                                              \
    OMNIUI_PYBIND_INIT_CAST(separate_window, setSeparateWindow, bool)                                                  \
    OMNIUI_PYBIND_INIT_CAST(raster_policy, setRasterPolicy, RasterPolicy)                                              \
    OMNIUI_PYBIND_INIT_CALLBACK(build_fn, setBuildFn, void())

#define OMNIUI_PYBIND_KWARGS_DOC_Frame                                                                                 \
    "\n    `horizontal_clipping : `\n        "                                                                         \
    OMNIUI_PYBIND_DOC_Frame_horizontalClipping                                                                         \
    "\n    `vertical_clipping : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_Frame_verticalClipping                                                                           \
    "\n    `separate_window : `\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Frame_separateWindow                                                                             \
    "\n    `raster_policy : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_RasterHelper_rasterPolicy                                                                        \
    "\n    `build_fn : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_Frame_Build                                                                                      \
    OMNIUI_PYBIND_KWARGS_DOC_Container
// clang-format on
