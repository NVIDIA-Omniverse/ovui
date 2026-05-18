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

#define OMNIUI_PYBIND_DOC_Image                                                                                        \
    "The Image widget displays an image.\n"                                                                            \
    "The source of the image is specified as a URL using the source property. By default, specifying the width and height of the item causes the image to be scaled to that size. This behavior can be changed by setting the fill_mode property, allowing the image to be stretched or scaled instead. The property alignment controls where to align the scaled image.\n"


#define OMNIUI_PYBIND_DOC_Image_onStyleUpdated "Reimplemented. Called when the style or the parent style is changed.\n"


#define OMNIUI_PYBIND_DOC_Image_hasSourceUrl                                                                           \
    "Returns true if the image has non empty sourceUrl obtained through the property or the style.\n"


#define OMNIUI_PYBIND_DOC_Image_sourceUrl                                                                              \
    "This property holds the image URL. It can be an\n"                                                                \
    "omni:\n"                                                                                                          \
    "file:\n"


#define OMNIUI_PYBIND_DOC_Image_alignment                                                                              \
    "This property holds the alignment of the image when the fill policy is ePreserveAspectFit or ePreserveAspectCrop. By default, the image is centered.\n"


#define OMNIUI_PYBIND_DOC_Image_fillPolicy                                                                             \
    "Define what happens when the source image has a different size than the item.\n"


#define OMNIUI_PYBIND_DOC_Image_pixelAligned                                                                           \
    "Prevents image blurring when it's placed to fractional position (like x=0.5, y=0.5)\n"


#define OMNIUI_PYBIND_DOC_Image_progress "The progress of the image loading.\n"


#define OMNIUI_PYBIND_DOC_Image_Image                                                                                  \
    "Construct image with given url. If the url is empty, it gets the image URL from styling.\n"
