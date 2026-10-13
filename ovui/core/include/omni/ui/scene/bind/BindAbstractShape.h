/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindAbstractItem.h"
#include "DocAbstractShape.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_AbstractShape                                                                               \
    OMNIUI_PYBIND_INIT_CALL(gesture, setGestures, pythonToGestures)                                                    \
    OMNIUI_PYBIND_INIT_CALL(gestures, setGestures, pythonToGestures)                                                   \
    OMNIUI_PYBIND_INIT_AbstractItem

#define OMNIUI_PYBIND_KWARGS_DOC_AbstractShape                                                                         \
    "\n    `gesture : `\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_AbstractShape_getGestures                                                                        \
    "\n    `gestures : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_AbstractShape_getGestures                                                                        \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractItem

// clang-format on

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

std::vector<std::shared_ptr<ShapeGesture>> pythonToGestures(pybind11::handle obj);

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
