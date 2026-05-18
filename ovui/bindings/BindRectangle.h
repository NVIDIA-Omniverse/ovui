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
