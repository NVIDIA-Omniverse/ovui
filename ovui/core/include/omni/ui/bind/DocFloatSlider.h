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

#define OMNIUI_PYBIND_DOC_FloatSlider                                                                                                                                                                                     \
    "The slider is the classic widget for controlling a bounded value. It lets the user move a slider handle along a horizontal groove and translates the handle's position into a float value within the legal range.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_onModelUpdated                                                                   \
    "Reimplemented the method from ValueModelHelper that is called when the model is changed.\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_min "This property holds the slider's minimum value.\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_max "This property holds the slider's maximum value.\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_step "This property controls the steping speed on the drag.\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_format "This property overrides automatic formatting if needed.\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_precision "This property holds the slider value's float precision.\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_getFormatString                                                                  \
    "Get the format string for the given value. The number should be in the format of\n"                               \
    "0.0\n"


#define OMNIUI_PYBIND_DOC_FloatSlider_FloatSlider "Construct FloatSlider.\n"
