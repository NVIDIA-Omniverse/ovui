/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "DocAbstractManipulatorModel.h"

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::AbstractManipulatorModel, AbstractManipulatorModel);
OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::AbstractManipulatorModel::AbstractManipulatorItem,
                               AbstractManipulatorItem);

#define OMNIUI_PYBIND_INIT_AbstractManipulatorModel
#define OMNIUI_PYBIND_KWARGS_DOC_AbstractManipulatorModel
