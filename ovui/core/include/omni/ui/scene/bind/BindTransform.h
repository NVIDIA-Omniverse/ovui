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

#include "BindAbstractContainer.h"
#include "DocTransform.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Transform                                                                                   \
    OMNIUI_PYBIND_INIT_AbstractContainer                                                                               \
    OMNIUI_PYBIND_INIT_CALL(transform, setTransform, pythonToMatrix4)                                                  \
    OMNIUI_PYBIND_INIT_CAST(scale_to, setScaleTo, Space)                                                               \
    OMNIUI_PYBIND_INIT_CAST(look_at, setLookAt,  Transform::LookAt)                                                    \
    OMNIUI_PYBIND_INIT_CAST(basis, setBasis,  std::shared_ptr<TransformBasis>)

#define OMNIUI_PYBIND_KWARGS_DOC_Transform                                                                             \
    "\n    `transform : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Transform_transform                                                                              \
    "\n    `scale_to : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_Transform_scaleTo                                                                                \
    "\n    `look_at : `\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_Transform_lookAt                                                                                 \
    "\n    `basis : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Transform_basis                                                                                  \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractContainer

// clang-format on
