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

#include <omni/ui/BezierCurve.h>
#include <omni/ui/ShapeAnchorHelper.h>
#include <omni/ui/bind/BindBezierCurve.h>
#include <omni/ui/bind/Pybind.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapBezierCurve(module& m)
{
    constexpr const char* bezierCurveDoc = OMNIUI_PYBIND_CLASS_DOC(BezierCurve);
    static constexpr char bezierCurveConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(BezierCurve, BezierCurve);

    class_<BezierCurve, Shape, ArrowHelper, ShapeAnchorHelper, std::shared_ptr<BezierCurve>>(m, "BezierCurve", bezierCurveDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(BezierCurve) }), bezierCurveConstructorDoc)
        .def_property("start_tangent_width", &BezierCurve::getStartTangentWidth, &BezierCurve::setStartTangentWidth,
                      OMNIUI_PYBIND_DOC_BezierCurve_startTangentWidth)
        .def_property("start_tangent_height", &BezierCurve::getStartTangentHeight, &BezierCurve::setStartTangentHeight,
                      OMNIUI_PYBIND_DOC_BezierCurve_startTangentHeight)
        .def_property("end_tangent_width", &BezierCurve::getEndTangentWidth, &BezierCurve::setEndTangentWidth,
                      OMNIUI_PYBIND_DOC_BezierCurve_endTangentWidth)
        .def_property("end_tangent_height", &BezierCurve::getEndTangentHeight, &BezierCurve::setEndTangentHeight,
                      OMNIUI_PYBIND_DOC_BezierCurve_endTangentHeight)
        .OMNIUI_PYBIND_DEF_CALLBACK(mouse_hovered, BezierCurve, MouseHovered)
        ;
}
