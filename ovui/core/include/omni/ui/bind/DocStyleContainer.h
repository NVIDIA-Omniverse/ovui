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

#define OMNIUI_PYBIND_DOC_StyleContainer                                                                               \
    "The StyleContainer class encapsulates the look and feel of a GUI.\n"                                              \
    "It's a place holder for the future work to support CSS style description. StyleContainer supports various properties, pseudo-states, and subcontrols that make it possible to customize the look of widgets. It can only be edited by merging with another style.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_valid "Check if the style contains anything.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_merge "Merges another style to this style. The given style is strongest.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_getStyleStateGroupIndex                                                       \
    "Find the style state group by type and name. It's pretty slow, so it shouldn't be used in the draw cycle.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_getCachedTypes "Get all the types in this StyleContainer.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_getCachedNames                                                                \
    "Get all the names related to the type in this StyleContainer.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_getCachedStates                                                               \
    "Get all the available states in the given index in this StyleContainer.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_resolveStyleProperty                                                                                                                                                                                         \
    "Find the given property in the data structure using the style state group index. If the property is not found, it continues finding in cascading and parent blocks. The style state group index can be obtained with getStyleStateGroupIndex.\n" \
    "\n"                                                                                                                                                                                                                                              \
    "\n"                                                                                                                                                                                                                                              \
    "### Arguments:\n"                                                                                                                                                                                                                                \
    "\n"                                                                                                                                                                                                                                              \
    "    `T :`\n"                                                                                                                                                                                                                                     \
    "        StyleFloatProperty or StyleColorProperty\n"                                                                                                                                                                                              \
    "\n"                                                                                                                                                                                                                                              \
    "    `U :`\n"                                                                                                                                                                                                                                     \
    "        float or uint32_t\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_defaultStyle "Preset with a default style.\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_getNameToPropertyMapping                                                      \
    "Get the the mapping between property and its string.\n"                                                           \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `T :`\n"                                                                                                      \
    "        StyleFloatProperty, StyleEnumProperty, StyleColorProperty, StyleStringProperty or State\n"


#define OMNIUI_PYBIND_DOC_StyleContainer_getPropertyEnumeration                                                        \
    "Get the Property from the string.\n"                                                                              \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `T :`\n"                                                                                                      \
    "        StyleFloatProperty, StyleEnumProperty, StyleColorProperty or StyleStringProperty\n"


#define OMNIUI_PYBIND_DOC_StyleContainer__parseScopeString                                                             \
    "Perses a string that looks like \"Widget::name:state\", split it to the parts and return the parts.\n"
