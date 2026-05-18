/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
