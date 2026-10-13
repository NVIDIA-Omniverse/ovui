/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindClickGesture.h"
#include "DocDoubleClickGesture.h"

#include <omni/ui/scene/DoubleClickGesture.h>

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::DoubleClickGesture, DoubleClickGesture);

// clang-format off

#define OMNIUI_PYBIND_INIT_PyDoubleClickGesture                                                                        \
    OMNIUI_PYBIND_INIT_PyClickGesture

#define OMNIUI_PYBIND_KWARGS_DOC_DoubleClickGesture                                                                    \
    OMNIUI_PYBIND_KWARGS_DOC_ClickGesture

#define OMNIUI_PYBIND_DOC_DoubleClickGesture_OnEnded OMNIUI_PYBIND_DOC_ClickGesture_OnEnded

// clang-format on
