/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
