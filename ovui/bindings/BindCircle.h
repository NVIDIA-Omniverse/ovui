/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Circle.h>
#include <omni/ui/bind/BindCircle.h>
#include <omni/ui/bind/Pybind.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapCircle(module& m)
{
    // TODO: find a good way to consolide that, maybe we need a consistatn Shape::SizePolicy ?
    enum_<Circle::SizePolicy>(m, "CircleSizePolicy", OMNIUI_PYBIND_DOC_Circle_sizePolicy)
        .value("STRETCH", Circle::SizePolicy::eStretch)
        .value("FIXED", Circle::SizePolicy::eFixed);

    constexpr const char* circleDoc = OMNIUI_PYBIND_CLASS_DOC(Circle);
    static constexpr char circleConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Circle, Circle);

    class_<Circle, Shape, std::shared_ptr<Circle>>(m, "Circle", circleDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Circle) }), circleConstructorDoc)
        .def_property("radius", &Circle::getRadius, &Circle::setRadius, OMNIUI_PYBIND_DOC_Circle_radius)
        .def_property("segments", &Circle::getSegments, &Circle::setSegments, OMNIUI_PYBIND_DOC_Circle_segments)
        .def_property("alignment", &Circle::getAlignment, &Circle::setAlignment, OMNIUI_PYBIND_DOC_Circle_alignment)
        .def_property("arc", &Circle::getArc, &Circle::setArc, OMNIUI_PYBIND_DOC_Circle_arc)
        .def_property("size_policy", &Circle::getSizePolicy, &Circle::setSizePolicy, OMNIUI_PYBIND_DOC_Circle_sizePolicy);
}
