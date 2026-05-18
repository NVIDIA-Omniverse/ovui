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

#define OMNIUI_PYBIND_DOC_Frame                                                                                        \
    "The Frame is a widget that can hold one child widget.\n"                                                          \
    "Frame is used to crop the contents of a child widget or to draw small widget in a big view. The child widget must be specified with addChild().\n"


#define OMNIUI_PYBIND_DOC_Frame_addChild                                                                               \
    "Reimplemented adding a widget to this Frame. The Frame class can not contain multiple widgets. The widget overrides.\n"


#define OMNIUI_PYBIND_DOC_Frame_clear "Reimplemented removing all the child widgets from this Stack.\n"


#define OMNIUI_PYBIND_DOC_Frame_setComputedContentWidth                                                                \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_Frame_setComputedContentHeight                                                               \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_Frame_cascadeStyle                                                                           \
    "It's called when the style is changed. It should be propagated to children to make the style cached and available to children.\n"


#define OMNIUI_PYBIND_DOC_Frame_forceRasterDirty "Next frame the content will be forced to re-bake.\n"


#define OMNIUI_PYBIND_DOC_Frame_Build                                                                                  \
    "Set the callback that will be called once the frame is visible and the content of the callback will override the frame child. It's useful for lazy load.\n"


#define OMNIUI_PYBIND_DOC_Frame_rebuild                                                                                \
    "After this method is called, the next drawing cycle build_fn will be called again to rebuild everything.\n"


#define OMNIUI_PYBIND_DOC_Frame_setVisiblePreviousFrame "Change dirty bits when the visibility is changed.\n"


#define OMNIUI_PYBIND_DOC_Frame_horizontalClipping                                                                     \
    "When the content of the frame is bigger than the frame the exceeding part is not drawn if the clipping is on. It only works for horizontal direction.\n"


#define OMNIUI_PYBIND_DOC_Frame_verticalClipping                                                                       \
    "When the content of the frame is bigger than the frame the exceeding part is not drawn if the clipping is on. It only works for vertial direction.\n"


#define OMNIUI_PYBIND_DOC_Frame_separateWindow                                                                         \
    "A special mode where the child is placed to the transparent borderless window. We need it to be able to place the UI to the exact stacking order between other windows.\n"


#define OMNIUI_PYBIND_DOC_Frame_Frame "Constructs Frame.\n"
