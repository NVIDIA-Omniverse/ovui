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

#define OMNIUI_PYBIND_DOC_Circle                                                                                       \
    "The Circle widget provides a colored circle to display.\n"                                                     \
    "\n"


#define OMNIUI_PYBIND_DOC_Circle_setComputedContentWidth                                                               \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. when the circle is in fixed mode it can't be smaller than the radius.\n"


#define OMNIUI_PYBIND_DOC_Circle_setComputedContentHeight                                                              \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. when the circle is in fixed mode it can't be smaller than the radius.\n"


#define OMNIUI_PYBIND_DOC_Circle_radius                                                                                \
    "This property holds the radius of the circle when the fill policy is eFixed or eFixedCrop. By default, the circle radius is 0.\n"

#define OMNIUI_PYBIND_DOC_Circle_segments                                                                                \
    "This property holds the number of segments the circle will be draw with, By default, the circle has 40 segments.\n"

#define OMNIUI_PYBIND_DOC_Circle_alignment                                                                             \
    "This property holds the alignment of the circle when the fill policy is ePreserveAspectFit or ePreserveAspectCrop. By default, the circle is centered.\n"


#define OMNIUI_PYBIND_DOC_Circle_arc                                                                                   \
    "This property is the way to draw a half or a quarter of the circle. When it's eLeft, only left side of the circle is rendered. When it's eLeftTop, only left top quarter is rendered.\n"


#define OMNIUI_PYBIND_DOC_Circle_sizePolicy                                                                            \
    "Define what happens when the source image has a different size than the item.\n"


#define OMNIUI_PYBIND_DOC_Circle_Circle "Constructs Circle.\n"
