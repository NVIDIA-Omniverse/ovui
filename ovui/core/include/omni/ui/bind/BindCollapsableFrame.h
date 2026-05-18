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

#include "BindFrame.h"
#include "BindUtils.h"
#include "DocCollapsableFrame.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_CollapsableFrame                                                                            \
    OMNIUI_PYBIND_INIT_Frame                                                                                           \
    OMNIUI_PYBIND_INIT_CAST(collapsed, setCollapsed, bool)                                                             \
    OMNIUI_PYBIND_INIT_CAST(title, setTitle, std::string)                                                              \
    OMNIUI_PYBIND_INIT_CAST(alignment, setAlignment, Alignment)                                                        \
    OMNIUI_PYBIND_INIT_CALLBACK(build_header_fn, setBuildHeaderFn, void(bool, std::string))                            \
    OMNIUI_PYBIND_INIT_CALLBACK(collapsed_changed_fn, setCollapsedChangedFn, void(bool))

#define OMNIUI_PYBIND_KWARGS_DOC_CollapsableFrame                                                                      \
    "\n    `collapsed : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_CollapsableFrame_collapsed                                                                       \
    "\n    `title : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_CollapsableFrame_title                                                                           \
    "\n    `alignment : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_CollapsableFrame_alignment                                                                       \
    "\n    `build_header_fn : `\n        "                                                                             \
    OMNIUI_PYBIND_DOC_CollapsableFrame_BuildHeader                                                                     \
    "\n    `collapsed_changed_fn : `\n        "                                                                        \
    OMNIUI_PYBIND_DOC_CollapsableFrame_collapsed                                                                       \
    OMNIUI_PYBIND_KWARGS_DOC_Frame
// clang-format on
