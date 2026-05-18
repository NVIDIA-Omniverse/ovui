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
#include <omni/ui/scene/Arc.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindArc.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapArc(module& m)
{
    constexpr const char* arcDoc = OMNIUI_PYBIND_CLASS_DOC(Arc);
    static constexpr char arcConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Arc, Arc);

    class_<Arc::ArcGesturePayload, AbstractGesture::GesturePayload, std::shared_ptr<Arc::ArcGesturePayload>>(
        m, "ArcGesturePayload")
        .def_property_readonly(
            "distance_to_center", [](const Arc::ArcGesturePayload& self) { return self.distanceToCenter; })
        .def_property_readonly("angle", [](const Arc::ArcGesturePayload& self) { return self.angle; })
        .def_property_readonly(
            "moved_distance_to_center", [](const Arc::ArcGesturePayload& self) { return self.movedDistanceToCenter; })
        .def_property_readonly("moved_angle", [](const Arc::ArcGesturePayload& self) { return self.movedAngle; })
        .def_property_readonly("moved", [](const Arc::ArcGesturePayload& self) { return vector3ToPython(self.moved); })
        .def_property_readonly("culled", [](const Arc::ArcGesturePayload& self) { return self.culled; })
        /* */;

    class_<Arc, AbstractShape, std::shared_ptr<Arc>>(m, "Arc", arcDoc)
        .def(init([](Float radius, kwargs kwargs) { OMNIUI_PYBIND_INIT(Arc, radius) }), arg("radius"), arcConstructorDoc)
        .def_property("radius", &Arc::getRadius, &Arc::setRadius)
        .def_property("begin", &Arc::getBegin, &Arc::setBegin, OMNIUI_PYBIND_DOC_Arc_begin)
        .def_property("end", &Arc::getEnd, &Arc::setEnd, OMNIUI_PYBIND_DOC_Arc_end)
        .def_property("thickness", &Arc::getThickness, &Arc::setThickness, OMNIUI_PYBIND_DOC_Arc_thickness)
        .def_property("intersection_thickness", &Arc::getIntersectionThickness, &Arc::setIntersectionThickness, OMNIUI_PYBIND_DOC_Arc_intersectionThickness)
        .def_property("color", [](const Arc& self) { return vector4ToPython(self.getColor()); },
                      [](Arc& self, const pybind11::handle& obj) { self.setColor(pythonToColor4(obj)); },
                      OMNIUI_PYBIND_DOC_Arc_color)
        .def_property("tesselation", &Arc::getTesselation, &Arc::setTesselation, OMNIUI_PYBIND_DOC_Arc_tesselation)
        .def_property("wireframe", &Arc::isWireframe, &Arc::setWireframe, OMNIUI_PYBIND_DOC_Arc_wireframe)
        .def_property("sector", &Arc::isSector, &Arc::setSector, OMNIUI_PYBIND_DOC_Arc_sector)
        .def_property("axis", &Arc::getAxis, &Arc::setAxis, OMNIUI_PYBIND_DOC_Arc_axis)
        .def_property("culling", &Arc::getCulling, &Arc::setCulling, OMNIUI_PYBIND_DOC_Arc_culling)
        .def_property_readonly("gesture_payload", [](const Arc& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_Arc_getGesturePayload)
        .def("get_gesture_payload", [](const Arc& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Arc_getGesturePayload)
        .def("get_gesture_payload", [](const Arc& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Arc_getGesturePayload01);
}
