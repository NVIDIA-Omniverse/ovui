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

#include "BindMenuHelper.h"
#include "BindStack.h"
#include "BindUtils.h"
#include "DocMenu.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Menu                                                                                        \
    OMNIUI_PYBIND_INIT_CALLBACK(shown_changed_fn, setShownChangedFn, void(const bool&))                                \
    OMNIUI_PYBIND_INIT_CAST(tearable, setTearable, bool)                                                               \
    OMNIUI_PYBIND_INIT_CALLBACK(teared_changed_fn, setTearedChangedFn, void(const bool&))                              \
    OMNIUI_PYBIND_INIT_CALLBACK(on_build_fn, setOnBuildFn, void())                                                     \
    OMNIUI_PYBIND_INIT_MenuHelper                                                                                      \
    OMNIUI_PYBIND_INIT_Stack

#define OMNIUI_PYBIND_KWARGS_DOC_Menu                                                                                  \
    "\n    `tearable : bool`\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Menu_tearable                                                                                    \
    "\n    `shown_changed_fn : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Menu_shown                                                                                       \
    "\n    `teared_changed_fn : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_Menu_teared                                                                                      \
    "\n    `on_build_fn : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Menu_OnBuild                                                                                     \
    OMNIUI_PYBIND_KWARGS_DOC_MenuHelper                                                                                \
    OMNIUI_PYBIND_KWARGS_DOC_Stack

// clang-format off
