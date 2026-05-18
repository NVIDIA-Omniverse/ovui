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

#include "BindIntSlider.h"
#include "BindUtils.h"
#include "DocIntDrag.h"
#include "DocUIntDrag.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_IntDrag                                                                                     \
        OMNIUI_PYBIND_INIT_IntSlider                                                                                   \
        OMNIUI_PYBIND_INIT_CAST(step, setStep, float)

#define OMNIUI_PYBIND_INIT_UIntDrag                                                                                    \
        OMNIUI_PYBIND_INIT_UIntSlider                                                                                  \
        OMNIUI_PYBIND_INIT_CAST(step, setStep, float)

#define OMNIUI_PYBIND_KWARGS_DOC_IntDrag                                                                               \
    "\n    `step : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_IntDrag_step                                                                                     \
    OMNIUI_PYBIND_KWARGS_DOC_IntSlider

#define OMNIUI_PYBIND_KWARGS_DOC_UIntDrag                                                                              \
    "\n    `step : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_UIntDrag_step                                                                                    \
    OMNIUI_PYBIND_KWARGS_DOC_UIntSlider
// clang-format on
