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

#include <omni/ui/Triangle.h>
#include <omni/ui/bind/BindTriangle.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapTriangle(module& m)
{
    constexpr const char* triangleDoc = OMNIUI_PYBIND_CLASS_DOC(Triangle);
    static constexpr char triangleConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Triangle, Triangle);

    class_<Triangle, Shape, std::shared_ptr<Triangle>>(m, "Triangle", triangleDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Triangle) }), triangleConstructorDoc)
        .def_property(
            "alignment", &Triangle::getAlignment, &Triangle::setAlignment, OMNIUI_PYBIND_DOC_Triangle_alignment);
}
