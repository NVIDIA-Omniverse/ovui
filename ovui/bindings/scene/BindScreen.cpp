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
#include <omni/ui/scene/Screen.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindScreen.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapScreen(module& m)
{
    constexpr const char* screenDoc = OMNIUI_PYBIND_CLASS_DOC(Screen);
    static constexpr char screenConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Screen, Screen);

    class_<Screen::ScreenGesturePayload, AbstractGesture::GesturePayload, std::shared_ptr<Screen::ScreenGesturePayload>>(
        m, "ScreenGesturePayload")
        .def_property_readonly(
            "direction", [](const Screen::ScreenGesturePayload& self) { return vector3ToPython(self.direction); })
        .def_property_readonly(
            "moved", [](const Screen::ScreenGesturePayload& self) { return vector3ToPython(self.moved); })
        .def_property_readonly(
            "mouse", [](const Screen::ScreenGesturePayload& self) { return vector2ToPython(self.mouse); })
        .def_property_readonly(
            "mouse_moved", [](const Screen::ScreenGesturePayload& self) { return vector2ToPython(self.mouseMoved); })
        /* */;

    class_<Screen, AbstractShape, std::shared_ptr<Screen>>(m, "Screen", screenDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Screen) }), screenConstructorDoc)
        .def_property_readonly("gesture_payload", [](const Screen& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_Screen_getGesturePayload)
        .def("get_gesture_payload", [](const Screen& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Screen_getGesturePayload)
        .def("get_gesture_payload", [](const Screen& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_Screen_getGesturePayload01);
}
