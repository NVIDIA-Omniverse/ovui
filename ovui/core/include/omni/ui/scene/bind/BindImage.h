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

#include "BindRectangle.h"
#include "DocImage.h"
#include "DocImageHelper.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Image                                                                                       \
    OMNIUI_PYBIND_INIT_Rectangle                                                                                       \
    OMNIUI_PYBIND_INIT_CAST(source_url, setSourceUrl, std::string)                                                     \
    OMNIUI_PYBIND_INIT_CAST(image_provider, setImageProvider, std::shared_ptr<ImageProvider>)                          \
    OMNIUI_PYBIND_INIT_CAST(fill_policy, setFillPolicy, Image::FillPolicy)                                             \
    OMNIUI_PYBIND_INIT_CAST(image_width, setImageWidth, uint32_t)                                                      \
    OMNIUI_PYBIND_INIT_CAST(image_height, setImageHeight, uint32_t)                                                    \

#define OMNIUI_PYBIND_KWARGS_DOC_Image                                                                                 \
    "\n    `source_url : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_Image_sourceUrl                                                                                  \
    "\n    `image_provider : `\n        "                                                                              \
    OMNIUI_PYBIND_DOC_Image_imageProvider                                                                              \
    "\n    `fill_policy : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Image_fillPolicy                                                                                 \
    "\n    `image_width : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_ImageHelper_imageWidth                                                                      \
    "\n    `image_height : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_ImageHelper_imageHeight                                                                     \
    OMNIUI_PYBIND_KWARGS_DOC_Rectangle

// clang-format on
