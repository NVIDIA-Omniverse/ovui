/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Ellipse.h>
#include <omni/ui/bind/BindEllipse.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapEllipse(module& m)
{
    constexpr const char* ellipseDoc = OMNIUI_PYBIND_CLASS_DOC(Ellipse);
    static constexpr char ellipseConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Ellipse, Ellipse);

    class_<Ellipse, Shape, std::shared_ptr<Ellipse>>(m, "Ellipse", ellipseDoc, ellipseConstructorDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Ellipse) }));
}
