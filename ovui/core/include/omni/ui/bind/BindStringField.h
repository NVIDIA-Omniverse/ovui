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

#include "BindAbstractField.h"
#include "DocStringField.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_StringField                                                                                 \
    OMNIUI_PYBIND_INIT_AbstractField                                                                                   \
    OMNIUI_PYBIND_INIT_CAST(password_mode, setPasswordMode, bool)                                                      \
    OMNIUI_PYBIND_INIT_CAST(read_only, setReadOnly, bool)                                                              \
    OMNIUI_PYBIND_INIT_CAST(multiline, setMultiline, bool)                                                             \
    OMNIUI_PYBIND_INIT_CAST(allow_tab_input, setTabInputAllowed, bool)

#define OMNIUI_PYBIND_KWARGS_DOC_StringField                                                                           \
    "\n    `password_mode : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_StringField_passwordMode                                                                         \
    "\n    `read_only : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_StringField_readOnly                                                                             \
    "\n    `multiline : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_StringField_multiline                                                                            \
    "\n    `allow_tab_input : `\n        "                                                                             \
    OMNIUI_PYBIND_DOC_StringField_allowTabInput                                                                        \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractField
// clang-format on
