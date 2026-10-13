/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_MenuItem                                                                                     \
    "A MenuItem represents the items the Menu consists of.\n"                                                          \
    "MenuItem can be inserted only once in the menu.\n"


#define OMNIUI_PYBIND_DOC_MenuItem_setComputedContentWidth                                                             \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_MenuItem_setComputedContentHeight                                                            \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_MenuItem_cascadeStyle                                                                        \
    "It's called when the style is changed. It should be propagated to children to make the style cached and available to children.\n"


#define OMNIUI_PYBIND_DOC_MenuItem_MenuItem "Construct MenuItem.\n"
