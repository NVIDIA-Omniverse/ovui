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

#define OMNIUI_PYBIND_DOC_Inspector                                                                                           \
    "Inspector is the helper to check the internal state of the widget. It's not recommended to use it for the routine UI.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_Inspector_getChildren "Get the children of the given Widget.\n"


#define OMNIUI_PYBIND_DOC_Inspector_getResolvedStyle "Get the resolved style of the given Widget.\n"


#define OMNIUI_PYBIND_DOC_Inspector_beginComputedWidthMetric                                                           \
    "Start counting how many times Widget::setComputedWidth is called\n"


#define OMNIUI_PYBIND_DOC_Inspector_bumpComputedWidthMetric "Increases the number Widget::setComputedWidth is called\n"


#define OMNIUI_PYBIND_DOC_Inspector_endComputedWidthMetric                                                             \
    "Start counting how many times Widget::setComputedWidth is called and return the number\n"


#define OMNIUI_PYBIND_DOC_Inspector_beginComputedHeightMetric                                                          \
    "Start counting how many times Widget::setComputedHeight is called\n"


#define OMNIUI_PYBIND_DOC_Inspector_bumpComputedHeightMetric                                                           \
    "Increases the number Widget::setComputedHeight is called\n"


#define OMNIUI_PYBIND_DOC_Inspector_endComputedHeightMetric                                                            \
    "Start counting how many times Widget::setComputedHeight is called and return the number\n"


#define OMNIUI_PYBIND_DOC_Inspector_getStoredFontAtlases                                                               \
    "Provides the information about font atlases\n"
