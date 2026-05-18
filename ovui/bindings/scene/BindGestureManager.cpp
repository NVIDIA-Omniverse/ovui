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
#include <pybind11/chrono.h>
#include <pybind11/stl.h>

using namespace pybind11;
using namespace omni::ui;

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class PyGestureManager : public GestureManager
{
public:
    static std::shared_ptr<PyGestureManager> create()
    {
        return std::make_shared<PyGestureManager>();
    }

    bool canBePrevented(AbstractGesture* gesture) const override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(bool, GestureManager, GestureManager::canBePrevented, can_be_prevented, gesture);
    }

    bool shouldPrevent(AbstractGesture* gesture, const AbstractGesture* gesturePreventer) const override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(
            bool, GestureManager, GestureManager::shouldPrevent, should_prevent, gesture, gesturePreventer);
    }

    MouseInput amendInput(MouseInput input) const override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(MouseInput, GestureManager, GestureManager::amendInput, amend_input, input);
    }
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapGestureManager(module& m)
{
    constexpr const char* gestureManagerDoc = OMNIUI_PYBIND_CLASS_DOC(GestureManager);
    static constexpr char gestureManagerConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(GestureManager, GestureManager);

    class_<GestureManager, PyGestureManager, std::shared_ptr<GestureManager>>(m, "GestureManager", gestureManagerDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(PyGestureManager) }), gestureManagerConstructorDoc)
        .def("can_be_prevented", &GestureManager::canBePrevented, OMNIUI_PYBIND_DOC_GestureManager_canBePrevented)
        .def("should_prevent", &GestureManager::shouldPrevent, OMNIUI_PYBIND_DOC_GestureManager_shouldPrevent)
        .def("amend_input", &GestureManager::amendInput, OMNIUI_PYBIND_DOC_GestureManager_amendInput)
        /**/;
}
