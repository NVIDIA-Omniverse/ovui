/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include "DocManipulator.h"
#include "DocManipulatorModelHelper.h"

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::Manipulator, Manipulator);

// clang-format off

#define OMNIUI_PYBIND_INIT_PyManipulator                                                                               \
    OMNIUI_PYBIND_INIT_AbstractContainer                                                                               \
    OMNIUI_PYBIND_INIT_CAST(model, setModel, std::shared_ptr<AbstractManipulatorModel>)                                \
    OMNIUI_PYBIND_INIT_CAST(gesture, addGesture, std::shared_ptr<ManipulatorGesture>)                                  \
    OMNIUI_PYBIND_INIT_CAST(gestures, setGestures, std::vector<std::shared_ptr<ManipulatorGesture>>)                   \
    OMNIUI_PYBIND_INIT_CALLBACK(on_build_fn, setOnBuildFn, void(Manipulator const*))

#define OMNIUI_PYBIND_KWARGS_DOC_Manipulator                                                                           \
    "\n    `model : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_ManipulatorModelHelper_getModel                                                                  \
    "\n    `gesture : `\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_Manipulator_getGestures                                                                          \
    "\n    `gestures : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_Manipulator_getGestures                                                                          \
    "\n    `on_build_fn : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Manipulator_onBuild                                                                              \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractContainer

// clang-format on
