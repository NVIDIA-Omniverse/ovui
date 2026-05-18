/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/Curve.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindCurve.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapCurve(module& m)
{
    constexpr const char* curveDoc = OMNIUI_PYBIND_CLASS_DOC(Curve);
    static constexpr char curveConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Curve, Curve);

    class_<Curve::CurveGesturePayload, AbstractGesture::GesturePayload, std::shared_ptr<Curve::CurveGesturePayload>>(
        m, "CurveGesturePayload")
        .def_property_readonly(
            "curve_distance", [](const Curve::CurveGesturePayload& self) { return self.curveDistance; })
        .def_property_readonly(
            "moved", [](const Curve::CurveGesturePayload& self) { return vector3ToPython(self.moved); })
        .def_property_readonly(
            "moved_distance", [](const Curve::CurveGesturePayload& self) { return self.movedDistance; })
        /* */;

    auto curve = class_<Curve, AbstractShape, std::shared_ptr<Curve>>(m, "Curve", curveDoc);

    enum_<Curve::CurveType>(curve, "CurveType", "")
        .value("LINEAR", Curve::CurveType::linear)
        .value("CUBIC", Curve::CurveType::cubic);

    curve
        .def(init([](object positions, kwargs kwargs) {
            auto pos = pythonListToVector3(positions); 
            OMNIUI_PYBIND_INIT(Curve, std::move(pos))
        }), curveConstructorDoc)
        .def_property("positions", [](const Curve& self) { return vector3ToPythonList(self.getPositions()); },
                      [](Curve& self, const pybind11::handle& obj) { self.setPositions(pythonListToVector3(obj)); },
                      OMNIUI_PYBIND_DOC_Curve_positions)
        .def_property("colors", [](const Curve& self) { return vector4ToPythonList(self.getColors()); },
                      [](Curve& self, const pybind11::handle& obj) { self.setColors(pythonListToVector4(obj)); },
                      OMNIUI_PYBIND_DOC_Curve_colors)
        .def_property("thicknesses", &Curve::getThicknesses, &Curve::setThicknesses, OMNIUI_PYBIND_DOC_Curve_thicknesses)
        .def_property("intersection_thicknesses", &Curve::getIntersectionThickness, &Curve::setIntersectionThickness, OMNIUI_PYBIND_DOC_Curve_intersectionThickness)
        .def_property("curve_type", &Curve::getCurveType, &Curve::setCurveType, OMNIUI_PYBIND_DOC_Curve_curveType)
        .def_property_readonly("gesture_payload", [](const Curve& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_Curve_getGesturePayload)
        .def_property(
            "tessellation", &Curve::getTessellation, &Curve::setTessellation, OMNIUI_PYBIND_DOC_Curve_tessellation)
        .def_property(
            "tesselation", &Curve::getTessellation, &Curve::setTessellation, OMNIUI_PYBIND_DOC_Curve_tessellation)
        .def("get_gesture_payload", [](const Curve& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Curve_getGesturePayload)
        .def("get_gesture_payload", [](const Curve& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Curve_getGesturePayload01);
}
