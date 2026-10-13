/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "DocCameraModel.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_CameraModel
#define OMNIUI_PYBIND_KWARGS_DOC_CameraModel                                                                           \
    "\n    `projection : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_CameraModel_getProjection                                                                        \
    "\n    `view : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_CameraModel_getView

// clang-format on
