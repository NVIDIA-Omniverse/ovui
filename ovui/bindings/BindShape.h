/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Shape.h>
#include <omni/ui/bind/BindShape.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapShape(module& m)
{
    constexpr const char* shapeDoc = OMNIUI_PYBIND_CLASS_DOC(Shape);

    class_<Shape, Widget, std::shared_ptr<Shape>>(m, "Shape", shapeDoc);
}
