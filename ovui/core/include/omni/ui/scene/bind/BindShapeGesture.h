/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindAbstractGesture.h"
#include "DocShapeGesture.h"

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::ShapeGesture, ShapeGesture);

#define OMNIUI_PYBIND_INIT_ShapeGesture OMNIUI_PYBIND_INIT_AbstractGesture
#define OMNIUI_PYBIND_KWARGS_DOC_ShapeGesture OMNIUI_PYBIND_KWARGS_DOC_AbstractGesture
