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

#define OMNIUI_PYBIND_DOC_MenuDelegate                                                                                 \
    "MenuDelegate is used to generate widgets that represent the menu item.\n"                                         \
    "\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_MenuDelegate "Constructor.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_buildItem "This method must be reimplemented to generate custom item.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_buildTitle "This method must be reimplemented to generate custom title.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_buildStatus                                                                     \
    "This method must be reimplemented to generate custom widgets on the bottom of the window.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_OnBuildItem "Called to create a new item.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_OnBuildTitle "Called to create a new title.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_OnBuildStatus "Called to create a new widget on the bottom of the window.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_propagate                                                                       \
    "Determine if Menu children should use this delegate when they don't have the own one.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_getDefaultDelegate                                                              \
    "Get the default delegate that is used when the menu doesn't have anything.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate_setDefaultDelegate                                                              \
    "Set the default delegate to use it when the item doesn't have a delegate.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate__siblingsHaveHotkeyText                                                         \
    "Return true if at least one of the siblings have the hotkey text.\n"


#define OMNIUI_PYBIND_DOC_MenuDelegate__siblingsHaveCheckable                                                          \
    "Return true if at least one of the siblings is checkable.\n"
