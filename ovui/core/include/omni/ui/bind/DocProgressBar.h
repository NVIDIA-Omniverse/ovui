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

#define OMNIUI_PYBIND_DOC_ProgressBar                                                                                  \
    "A progressbar is a classic widget for showing the progress of an operation.\n"                                    \
    "\n"


#define OMNIUI_PYBIND_DOC_ProgressBar_setComputedContentHeight                                                         \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_ProgressBar_onStyleUpdated                                                                   \
    "Reimplemented. Something happened with the style or with the parent style. We need to gerenerate the cache.\n"


#define OMNIUI_PYBIND_DOC_ProgressBar_onModelUpdated                                                                   \
    "Reimplemented the method from ValueModelHelper that is called when the model is changed.\n"


#define OMNIUI_PYBIND_DOC_ProgressBar_ProgressBar                                                                      \
    "Construct ProgressBar.\n"                                                                                         \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `model :`\n"                                                                                                  \
    "        The model that determines if the button is checked.\n"
