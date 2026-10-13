/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_RasterPolicy                                                                                 \
    "Used to set the rasterization behaviour.\n"


#define OMNIUI_PYBIND_DOC_RasterPolicy_eNever                                                                          \
    "Do not rasterize the widget at any time.\n"


#define OMNIUI_PYBIND_DOC_RasterPolicy_eOnDemand                                                                       \
    "Rasterize the widget as soon as possible and always use the rasterized version. This means that the widget will only be updated when the user called invalidateRaster.\n"


#define OMNIUI_PYBIND_DOC_RasterPolicy_eAuto                                                                           \
    "Automatically determine whether to rasterize the widget based on performance considerations. If necessary, the widget will be rasterized and updated when its content changes.\n"
