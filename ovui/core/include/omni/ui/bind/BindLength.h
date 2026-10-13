/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindUtils.h"
#include "DocFraction.h"
#include "DocLength.h"
#include "DocPercent.h"
#include "DocPixel.h"

#define OMNIUI_PYBIND_INIT_Length
#define OMNIUI_PYBIND_KWARGS_DOC_Length

#define OMNIUI_PYBIND_INIT_Percent OMNIUI_PYBIND_INIT_Length
#define OMNIUI_PYBIND_KWARGS_DOC_Percent OMNIUI_PYBIND_KWARGS_DOC_Length

#define OMNIUI_PYBIND_INIT_Pixel OMNIUI_PYBIND_INIT_Length
#define OMNIUI_PYBIND_KWARGS_DOC_Pixel OMNIUI_PYBIND_KWARGS_DOC_Length

#define OMNIUI_PYBIND_INIT_Fraction OMNIUI_PYBIND_INIT_Length
#define OMNIUI_PYBIND_KWARGS_DOC_Fraction OMNIUI_PYBIND_KWARGS_DOC_Length
