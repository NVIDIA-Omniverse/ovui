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

#define OMNIUI_PYBIND_DOC_Placer                                                                                       \
    "The Placer class place a single widget to a particular position based on the offet.\n"                            \
    "\n"


#define OMNIUI_PYBIND_DOC_Placer_addChild                                                                              \
    "Reimplemented adding a widget to this Placer. The Placer class can not contain multiple widgets.\n"


#define OMNIUI_PYBIND_DOC_Placer_clear "Reimplemented to simply set the single child to null.\n"


#define OMNIUI_PYBIND_DOC_Placer_setComputedContentWidth                                                               \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widget.\n"


#define OMNIUI_PYBIND_DOC_Placer_setComputedContentHeight                                                              \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widget.\n"


#define OMNIUI_PYBIND_DOC_Placer_cascadeStyle                                                                          \
    "It's called when the style is changed. It should be propagated to children to make the style cached and available to children.\n"


#define OMNIUI_PYBIND_DOC_Placer_forceRasterDirty "Next frame the content will be forced to re-bake.\n"


#define OMNIUI_PYBIND_DOC_Placer_offsetX                                                                               \
    "offsetX defines the offset placement for the child widget relative to the Placer\n"


#define OMNIUI_PYBIND_DOC_Placer_offsetY                                                                               \
    "offsetY defines the offset placement for the child widget relative to the Placer\n"


#define OMNIUI_PYBIND_DOC_Placer_draggable "Provides a convenient way to make an item draggable.\n"


#define OMNIUI_PYBIND_DOC_Placer_dragAxis "Sets if dragging can be horizontally or vertically.\n"


#define OMNIUI_PYBIND_DOC_Placer_stableSize "The placer size depends on the position of the child when false.\n"


#define OMNIUI_PYBIND_DOC_Placer_framesToStartDrag                                                                     \
    "Set number of frames to start dragging if drag is not detected the first frame.\n"


#define OMNIUI_PYBIND_DOC_Placer_Placer "Construct Placer.\n"
