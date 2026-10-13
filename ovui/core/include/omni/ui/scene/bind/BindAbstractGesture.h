/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "DocAbstractGesture.h"

#include <omni/ui/bind/BindUtils.h>

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::AbstractGesture, AbstractGesture);

// clang-format off

#define OMNIUI_PYBIND_INIT_AbstractGesture                                                                             \
    OMNIUI_PYBIND_INIT_CAST(name, setName, std::string)                                                                \
    OMNIUI_PYBIND_INIT_CAST(manager, setManager, std::shared_ptr<GestureManager>)

#define OMNIUI_PYBIND_KWARGS_DOC_AbstractGesture                                                                       \
    "\n    `name : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_AbstractGesture_name                                                                             \
    "\n    `manager : `\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_AbstractGesture_getManager

// clang-format on
