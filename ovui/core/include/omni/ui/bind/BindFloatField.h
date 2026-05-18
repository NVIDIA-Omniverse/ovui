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

#include "BindAbstractField.h"
#include "BindUtils.h"
#include "DocFloatField.h"

#define OMNIUI_PYBIND_INIT_FloatField                                                                                  \
    OMNIUI_PYBIND_INIT_AbstractField                                                                                   \
    OMNIUI_PYBIND_INIT_CAST(precision, setPrecision, uint32_t)
#define OMNIUI_PYBIND_KWARGS_DOC_FloatField                                                                            \
    "\n    `precision : uint32_t`\n        "                                                                           \
    OMNIUI_PYBIND_DOC_FloatField_precision                                                                             \
OMNIUI_PYBIND_KWARGS_DOC_AbstractField
