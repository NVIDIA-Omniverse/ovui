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
#include <omni/ui/scene/Rectangle.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindRectangle.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapRectangle(module& m)
{
    constexpr const char* rectangleDoc = OMNIUI_PYBIND_CLASS_DOC(Rectangle);
    static constexpr char rectangleConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Rectangle, Rectangle);

    class_<Rectangle::RectangleGesturePayload, AbstractGesture::GesturePayload,
           std::shared_ptr<Rectangle::RectangleGesturePayload>>(m, "RectangleGesturePayload")
        .def_property_readonly("s", [](const Rectangle::RectangleGesturePayload& self) { return self.s; })
        .def_property_readonly("t", [](const Rectangle::RectangleGesturePayload& self) { return self.t; })
        .def_property_readonly("moved_s", [](const Rectangle::RectangleGesturePayload& self) { return self.movedS; })
        .def_property_readonly("moved_t", [](const Rectangle::RectangleGesturePayload& self) { return self.movedT; })
        .def_property_readonly(
            "moved", [](const Rectangle::RectangleGesturePayload& self) { return vector3ToPython(self.moved); })
        /* */;

    class_<Rectangle, AbstractShape, std::shared_ptr<Rectangle>>(m, "Rectangle", rectangleDoc)
        .def(init([](Float width, Float height, kwargs kwargs) { OMNIUI_PYBIND_INIT(Rectangle, width, height) }),
             arg("width") = 1.0, arg("height") = 1.0, rectangleConstructorDoc)
        .def_property("width", &Rectangle::getWidth, &Rectangle::setWidth, OMNIUI_PYBIND_DOC_Rectangle_width)
        .def_property("height", &Rectangle::getHeight, &Rectangle::setHeight, OMNIUI_PYBIND_DOC_Rectangle_height)
        .def_property(
            "thickness", &Rectangle::getThickness, &Rectangle::setThickness, OMNIUI_PYBIND_DOC_Rectangle_thickness)
        .def_property("intersection_thickness", &Rectangle::getIntersectionThickness, &Rectangle::setIntersectionThickness, OMNIUI_PYBIND_DOC_Rectangle_intersectionThickness)
        .def_property("color", [](const Rectangle& self) { return vector4ToPython(self.getColor()); },
                      [](Rectangle& self, const pybind11::handle& obj) { self.setColor(pythonToColor4(obj)); },
                      OMNIUI_PYBIND_DOC_Rectangle_color)
        .def_property(
            "wireframe", &Rectangle::isWireframe, &Rectangle::setWireframe, OMNIUI_PYBIND_DOC_Rectangle_wireframe)
        .def_property("axis", &Rectangle::getAxis, &Rectangle::setAxis, OMNIUI_PYBIND_DOC_Rectangle_axis)
        .def_property_readonly("gesture_payload", [](const Rectangle& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_Rectangle_getGesturePayload)
        .def("get_gesture_payload", [](const Rectangle& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Rectangle_getGesturePayload)
        .def("get_gesture_payload",
             [](const Rectangle& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Rectangle_getGesturePayload01);
}
