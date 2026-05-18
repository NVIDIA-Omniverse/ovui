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
#include "DocMenuHelper.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_MenuHelper                                                                                  \
    OMNIUI_PYBIND_INIT_CAST(text, setText, std::string)                                                                \
    OMNIUI_PYBIND_INIT_CAST(hotkey_text, setHotkeyText, std::string)                                                   \
    OMNIUI_PYBIND_INIT_CAST(checkable, setCheckable, bool)                                                             \
    OMNIUI_PYBIND_INIT_CAST(hide_on_click, setHideOnClick, bool)                                                       \
    OMNIUI_PYBIND_INIT_CAST(menu_compatibility, setMenuCompatibility, bool)                                            \
    OMNIUI_PYBIND_INIT_CAST(delegate, setDelegate, std::shared_ptr<MenuDelegate>)                                      \
    OMNIUI_PYBIND_INIT_CALLBACK(triggered_fn, setTriggeredFn, void())

#define OMNIUI_PYBIND_KWARGS_DOC_MenuHelper                                                                            \
    "\n    `text : str`\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_MenuHelper_text                                                                                  \
    "\n    `hotkey_text : str`\n        "                                                                              \
    OMNIUI_PYBIND_DOC_MenuHelper_hotkeyText                                                                            \
    "\n    `checkable : bool`\n        "                                                                               \
    OMNIUI_PYBIND_DOC_MenuHelper_checkable                                                                             \
    "\n    `hide_on_click : bool`\n        "                                                                           \
    OMNIUI_PYBIND_DOC_MenuHelper_hideOnClick                                                                           \
    "\n    `delegate : MenuDelegate`\n        "                                                                        \
    OMNIUI_PYBIND_DOC_MenuHelper_delegate                                                                              \
    "\n    `triggered_fn : void`\n        "                                                                            \
    OMNIUI_PYBIND_DOC_MenuHelper_Triggered

// clang-format on
