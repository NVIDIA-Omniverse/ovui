/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "BindAbstractGesture.h"
#include "DocShapeGesture.h"

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::ShapeGesture, ShapeGesture);

#define OMNIUI_PYBIND_INIT_ShapeGesture OMNIUI_PYBIND_INIT_AbstractGesture
#define OMNIUI_PYBIND_KWARGS_DOC_ShapeGesture OMNIUI_PYBIND_KWARGS_DOC_AbstractGesture
