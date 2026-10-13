/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "DocGestureManager.h"

#include <omni/ui/bind/BindUtils.h>

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::GestureManager, GestureManager);

#define OMNIUI_PYBIND_INIT_PyGestureManager
#define OMNIUI_PYBIND_KWARGS_DOC_GestureManager
