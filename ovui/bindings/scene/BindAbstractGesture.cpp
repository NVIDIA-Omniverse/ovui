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
#include <omni/ui/scene/AbstractGesture.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/bind/BindAbstractGesture.h>
#include <omni/ui/scene/bind/BindGestureManager.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/bind/Pybind.h>
#include <pybind11/chrono.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapAbstractGesture(module& m)
{
    constexpr const char* gestureDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractGesture);

    enum_<GestureState>(m, "GestureState")
        .value("NONE", GestureState::eNone)
        .value("POSSIBLE", GestureState::ePossible)
        .value("BEGAN", GestureState::eBegan)
        .value("CHANGED", GestureState::eChanged)
        .value("ENDED", GestureState::eEnded)
        .value("CANCELED", GestureState::eCanceled)
        .value("PREVENTED", GestureState::ePrevented);


    class_<AbstractGesture, std::shared_ptr<AbstractGesture>> abstractGesture(m, "AbstractGesture", gestureDoc);

    class_<AbstractGesture::GesturePayload, std::shared_ptr<AbstractGesture::GesturePayload>>(
        abstractGesture, "GesturePayload")
        .def(init(
            [](object itemClosest, object rayClosest,
               Float rayDistance) -> std::shared_ptr<AbstractGesture::GesturePayload> {
                return std::make_shared<AbstractGesture::GesturePayload>(AbstractGesture::GesturePayload{
                    pythonToVector3(itemClosest), pythonToVector3(rayClosest), rayDistance });
            }))
        .def(init(
            [](const AbstractGesture::GesturePayload& payload) -> std::shared_ptr<AbstractGesture::GesturePayload> {
                    return std::make_shared<AbstractGesture::GesturePayload>(payload);
            }))
        .def_property_readonly("item_closest_point", [](const AbstractGesture::GesturePayload& self)
                               { return vector3ToPython(self.itemClosestPoint); })
        .def_property_readonly("ray_closest_point", [](const AbstractGesture::GesturePayload& self)
                               { return vector3ToPython(self.rayClosestPoint); })
        .def_property_readonly(
            "ray_distance", [](const AbstractGesture::GesturePayload& self) { return self.rayDistance; });

    abstractGesture
        .def("__repr__",
             [](const std::shared_ptr<AbstractGesture>& self) -> std::string { return "<AbstractGesture " + (self ? self->getName(): "") + ">"; })
        .def("get_gesture_payload", [](const AbstractGesture& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_AbstractGesture_getGesturePayload)
        .def("get_gesture_payload",
             [](const AbstractGesture& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_AbstractGesture_getGesturePayload01)
        .def("process", &AbstractGesture::process, OMNIUI_PYBIND_DOC_AbstractGesture_process)
        .def_property("name", &AbstractGesture::getName, &AbstractGesture::setName, OMNIUI_PYBIND_DOC_AbstractGesture_name)
        .def_property(
            "state", &AbstractGesture::getState, &AbstractGesture::setState, OMNIUI_PYBIND_DOC_AbstractGesture_getState)
        .def_property("manager", &AbstractGesture::getManager, &AbstractGesture::setManager,
                      OMNIUI_PYBIND_DOC_AbstractGesture_getManager)
        .def_property_readonly("gesture_payload", [](const AbstractGesture& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_AbstractGesture_getGesturePayload)
        /* */;
}
