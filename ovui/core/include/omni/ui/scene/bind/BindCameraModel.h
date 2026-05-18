/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "DocCameraModel.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_CameraModel
#define OMNIUI_PYBIND_KWARGS_DOC_CameraModel                                                                           \
    "\n    `projection : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_CameraModel_getProjection                                                                        \
    "\n    `view : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_CameraModel_getView

// clang-format on
