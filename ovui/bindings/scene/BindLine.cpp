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
#include <omni/ui/scene/Line.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindLine.h>
#include <omni/ui/scene/bind/BindMath.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapLine(module& m)
{
    constexpr const char* lineDoc = OMNIUI_PYBIND_CLASS_DOC(Line);
    static constexpr char lineConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Line, Line);

    class_<Line::LineGesturePayload, AbstractGesture::GesturePayload, std::shared_ptr<Line::LineGesturePayload>>(
        m, "LineGesturePayload")
        .def_property_readonly("line_closest_point", [](const Line::LineGesturePayload& self)
                               { return vector3ToPython(self.lineClosestPoint); })
        .def_property_readonly("line_distance", [](const Line::LineGesturePayload& self) { return self.lineDistance; })
        .def_property_readonly("moved", [](const Line::LineGesturePayload& self) { return vector3ToPython(self.moved); })
        /* */;

    class_<Line, AbstractShape, std::shared_ptr<Line>>(m, "Line", lineDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Line) }), lineConstructorDoc)
        .def(init([](object start, object end, kwargs kwargs) {
            const auto v0 = pythonToVector3(start), v1 = pythonToVector3(end);
            OMNIUI_PYBIND_INIT(Line, v0, v1)
        }), lineConstructorDoc)
        .def_property("start", [](const Line& self) { return vector3ToPython(self.getStart()); },
                      [](Line& self, const pybind11::handle& obj) { return self.setStart(pythonToVector3(obj)); },
                      OMNIUI_PYBIND_DOC_Line_start)
        .def_property("end", [](const Line& self) { return vector3ToPython(self.getEnd()); },
                      [](Line& self, const pybind11::handle& obj) { return self.setEnd(pythonToVector3(obj)); },
                      OMNIUI_PYBIND_DOC_Line_end)
        .def_property("color", [](const Line& self) { return vector4ToPython(self.getColor()); },
                      [](Line& self, const pybind11::handle& obj) { self.setColor(pythonToColor4(obj)); },
                      OMNIUI_PYBIND_DOC_Line_color)
        .def_property("thickness", &Line::getThickness, &Line::setThickness, OMNIUI_PYBIND_DOC_Line_thickness)
        .def_property("intersection_thickness", &Line::getIntersectionThickness, &Line::setIntersectionThickness, OMNIUI_PYBIND_DOC_Line_intersectionThickness)
        .def_property_readonly("gesture_payload", [](const Line& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_Line_getGesturePayload)
        .def("get_gesture_payload", [](const Line& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Line_getGesturePayload)
        .def("get_gesture_payload", [](const Line& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Line_getGesturePayload01);
}
