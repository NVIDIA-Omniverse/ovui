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

#include <omni/ui/FreeShape.h>
#include <omni/ui/bind/BindFreeShape.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapFreeShape(module& m)
{
    constexpr const char* freeBezierCurveDoc = OMNIUI_PYBIND_CLASS_DOC(FreeBezierCurve);
    static constexpr char freeBezierCurveConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(FreeBezierCurve, FreeBezierCurve);
    class_<FreeBezierCurve, BezierCurve, std::shared_ptr<FreeBezierCurve>>(m, "FreeBezierCurve", freeBezierCurveDoc)
        .def(init([](std::shared_ptr<Widget> from, std::shared_ptr<Widget> to, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FreeBezierCurve, std::move(from), std::move(to))
             }),
             freeBezierCurveConstructorDoc)
        /**/;

    constexpr const char* freeCircleDoc = OMNIUI_PYBIND_CLASS_DOC(FreeCircle);
    static constexpr char freeCircleConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FreeCircle, FreeCircle);
    class_<FreeCircle, Circle, std::shared_ptr<FreeCircle>>(m, "FreeCircle", freeCircleDoc)
        .def(init([](std::shared_ptr<Widget> from, std::shared_ptr<Widget> to, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FreeCircle, std::move(from), std::move(to))
             }),
             freeCircleConstructorDoc)
        /**/;

    constexpr const char* freeEllipseDoc = OMNIUI_PYBIND_CLASS_DOC(FreeEllipse);
    static constexpr char freeEllipseConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FreeEllipse, FreeEllipse);
    class_<FreeEllipse, Ellipse, std::shared_ptr<FreeEllipse>>(m, "FreeEllipse", freeEllipseDoc)
        .def(init([](std::shared_ptr<Widget> from, std::shared_ptr<Widget> to, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FreeEllipse, std::move(from), std::move(to))
             }),
             freeEllipseConstructorDoc)
        /**/;

    constexpr const char* freeLineDoc = OMNIUI_PYBIND_CLASS_DOC(FreeLine);
    static constexpr char freeLineConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FreeLine, FreeLine);
    class_<FreeLine, Line, std::shared_ptr<FreeLine>>(m, "FreeLine", freeLineDoc)
        .def(init([](std::shared_ptr<Widget> from, std::shared_ptr<Widget> to, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FreeLine, std::move(from), std::move(to))
             }),
             freeLineConstructorDoc)
        /**/;

    constexpr const char* freeRectangleDoc = OMNIUI_PYBIND_CLASS_DOC(FreeRectangle);
    static constexpr char freeRectangleConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FreeRectangle, FreeRectangle);
    class_<FreeRectangle, Rectangle, std::shared_ptr<FreeRectangle>>(m, "FreeRectangle", freeRectangleDoc)
        .def(init([](std::shared_ptr<Widget> from, std::shared_ptr<Widget> to, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FreeRectangle, std::move(from), std::move(to))
             }),
             freeRectangleConstructorDoc)
        /**/;

    constexpr const char* freeTriangleDoc = OMNIUI_PYBIND_CLASS_DOC(FreeTriangle);
    static constexpr char freeTriangleConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FreeTriangle, FreeTriangle);
    class_<FreeTriangle, Triangle, std::shared_ptr<FreeTriangle>>(m, "FreeTriangle", freeTriangleDoc)
        .def(init([](std::shared_ptr<Widget> from, std::shared_ptr<Widget> to, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FreeTriangle, std::move(from), std::move(to))
             }),
             freeTriangleConstructorDoc)
        /**/;
}
