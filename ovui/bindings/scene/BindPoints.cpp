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
#include <omni/ui/scene/Points.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindPoints.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapPoints(module& m)
{
    constexpr const char* pointsDoc = OMNIUI_PYBIND_CLASS_DOC(Points);
    static constexpr char pointsConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Points, Points);

    class_<Points::PointsGesturePayload, AbstractGesture::GesturePayload, std::shared_ptr<Points::PointsGesturePayload>>(
        m, "PointsGesturePayload")
        .def_property_readonly(
            "distance_to_point", [](const Points::PointsGesturePayload& self) { return self.distanceToPoint; })
        .def_property_readonly(
            "moved", [](const Points::PointsGesturePayload& self) { return vector3ToPython(self.moved); })
        .def_property_readonly(
            "closest_point", [](const Points::PointsGesturePayload& self) { return self.closestPoint; })
        /* */;

    class_<Points, AbstractShape, std::shared_ptr<Points>>(m, "Points", pointsDoc)
        .def(init([](object positions, kwargs kwargs) {
            auto pos = pythonListToVector3(positions);
            OMNIUI_PYBIND_INIT(Points, std::move(pos))
        }), pointsConstructorDoc)
        .def_property("positions", [](const Points& self) { return vector3ToPythonList(self.getPositions()); },
                      [](Points& self, const pybind11::handle& obj) { self.setPositions(pythonListToVector3(obj)); },
                      OMNIUI_PYBIND_DOC_Points_positions)
        .def_property("colors", [](const Points& self) { return vector4ToPythonList(self.getColors()); },
                      [](Points& self, const pybind11::handle& obj) { self.setColors(pythonListToVector4(obj)); },
                      OMNIUI_PYBIND_DOC_Points_colors)
        .def_property("sizes", &Points::getSizes, &Points::setSizes, OMNIUI_PYBIND_DOC_Points_sizes)
        .def_property("intersection_sizes", &Points::getIntersectionSize, &Points::setIntersectionSize, OMNIUI_PYBIND_DOC_Points_intersectionSize)
        .def_property_readonly("gesture_payload", [](const Points& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_Points_getGesturePayload)
        .def("get_gesture_payload", [](const Points& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Points_getGesturePayload)
        .def("get_gesture_payload", [](const Points& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Points_getGesturePayload01);
}
