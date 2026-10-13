/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindAbstractSlider.h"
#include "BindUtils.h"
#include "DocCommonIntSlider.h"
#include "DocIntSlider.h"
#include "DocUIntSlider.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_IntSlider                                                                                   \
    OMNIUI_PYBIND_INIT_AbstractSlider                                                                                  \
    OMNIUI_PYBIND_INIT_CAST(min, setMin, int64_t)                                                                      \
    OMNIUI_PYBIND_INIT_CAST(max, setMax, int64_t)

#define OMNIUI_PYBIND_INIT_UIntSlider                                                                                  \
    OMNIUI_PYBIND_INIT_AbstractSlider                                                                                  \
    OMNIUI_PYBIND_INIT_CAST(min, setMin, uint64_t)                                                                     \
    OMNIUI_PYBIND_INIT_CAST(max, setMax, uint64_t)

#define OMNIUI_PYBIND_KWARGS_DOC_IntSlider                                                                             \
    "\n    `min : `\n        "                                                                                         \
    OMNIUI_PYBIND_DOC_CommonIntSlider_min                                                                              \
    "\n    `max : `\n        "                                                                                         \
    OMNIUI_PYBIND_DOC_CommonIntSlider_max                                                                              \
    OMNIUI_PYBIND_KWARGS_DOC_Widget

#define OMNIUI_PYBIND_KWARGS_DOC_UIntSlider                                                                            \
    OMNIUI_PYBIND_KWARGS_DOC_IntSlider
// clang-format on
