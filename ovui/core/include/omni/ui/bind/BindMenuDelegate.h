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

#include "BindUtils.h"
#include "DocMenuDelegate.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_PyMenuDelegate                                                                              \
    OMNIUI_PYBIND_INIT_CAST(propagate, setPropagate, bool)                                                             \
    OMNIUI_PYBIND_INIT_CALLBACK(on_build_item, setOnBuildItemFn, void(MenuHelper const*))                              \
    OMNIUI_PYBIND_INIT_CALLBACK(on_build_title, setOnBuildTitleFn, void(MenuHelper const*))                            \
    OMNIUI_PYBIND_INIT_CALLBACK(on_build_status, setOnBuildStatusFn, void(MenuHelper const*))

#define OMNIUI_PYBIND_KWARGS_DOC_MenuDelegate                                                                          \
    "\n    `on_build_item : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_MenuDelegate_OnBuildItem                                                                         \
    "\n    `on_build_title : `\n        "                                                                              \
    OMNIUI_PYBIND_DOC_MenuDelegate_OnBuildTitle                                                                        \
    "\n    `on_build_status : `\n        "                                                                             \
    OMNIUI_PYBIND_DOC_MenuDelegate_OnBuildStatus                                                                       \
    "\n    `propagate : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_MenuDelegate_propagate

// clang-format on

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_NS::MenuDelegate, MenuDelegate);
