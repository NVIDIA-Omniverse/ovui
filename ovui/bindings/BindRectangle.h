/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Rectangle.h>
#include <omni/ui/bind/BindRectangle.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapRectangle(module& m)
{
    constexpr const char* rectangleDoc = OMNIUI_PYBIND_CLASS_DOC(Rectangle);
    static constexpr char rectangleConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Rectangle, Rectangle);

    class_<Rectangle, Shape, std::shared_ptr<Rectangle>>(m, "Rectangle", rectangleDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Rectangle) }), rectangleConstructorDoc);
}
