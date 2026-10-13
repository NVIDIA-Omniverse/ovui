/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindFloatSlider.h"
#include "BindUtils.h"
#include "DocFloatDrag.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_FloatDrag                                                                                   \
        OMNIUI_PYBIND_INIT_FloatSlider
#define OMNIUI_PYBIND_KWARGS_DOC_FloatDrag                                                                             \
        OMNIUI_PYBIND_KWARGS_DOC_FloatSlider
// clang-format on
