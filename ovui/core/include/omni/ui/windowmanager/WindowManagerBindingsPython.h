/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "IWindowCallbackManager.h"

#include <pybind11/pybind11.h>
#include <pybind11/functional.h>

#include <functional>
#include <memory>

namespace omni
{

namespace ui
{
namespace windowmanager
{
namespace py = pybind11;

struct WindowSet
{
};

class PythonEventListener : public IEventListener
{
public:
    PythonEventListener(const std::function<void(float)>& fn) : m_fn(fn)
    {
    }

    void onDraw(float dt) override
    {
        py::gil_scoped_acquire gil;
        try
        {
            if (m_fn) m_fn(dt);
        }
        catch (const py::error_already_set& error)
        {
            try
            {
                py::module_::import("sys").attr("excepthook")(error.type(), error.value(), error.trace());
            }
            catch (const std::exception& nested)
            {
                OMNIUI_LOG_ERROR("While handling Python callback error (%s): %s", error.what(), nested.what());
            }
        }
        catch (const std::runtime_error& error)
        {
            OMNIUI_LOG_ERROR("%s", error.what());
        }
    }

private:
    std::function<void(float)> m_fn;
};


/// acquireFn: function that returns IWindowCallbackManager* for this environment.
/// In standalone, pass a lambda that calls PlatformRegistry::instance().windowCallbackManager().
/// In Kit, pass a lambda that acquires via the Carbonite framework.
inline void definePythonModule(
    py::module& m,
    std::function<IWindowCallbackManager*()> acquireFn,
    std::function<py::object(AppWindowHandle)> wrapAppWindow,
    std::function<AppWindowHandle(py::handle)> unwrapAppWindow)
{
    m.doc() = "pybind11 omni.ui.windowmanager bindings";

    py::class_<WindowSet>(m, "WindowSet");


    py::class_<IWindowCallback, IWindowCallbackPtr>(m, "IWindowCallback", R"(
        IWindowCallback object.
        )")
        .def("get_title", &IWindowCallback::getTitle)
        .def("get_width", &IWindowCallback::getWidth)
        .def("get_height", &IWindowCallback::getHeight)
        .def("get_dock_preference", &IWindowCallback::getDockPreference)
        .def("get_window_set", &IWindowCallback::getWindowSet, py::return_value_policy::reference)
        .def("get_app_window", [wrapAppWindow](IWindowCallback* self) { return wrapAppWindow(self->getAppWindow()); })
        .def("draw", &IWindowCallback::draw)
        /**/;

    m.def("acquire_window_callback_manager_interface",
          [acquireFn]() { return acquireFn(); },
          py::return_value_policy::reference)
        /**/;

    py::class_<IWindowCallbackManager>(m, "IWindowCallbackManager")
        .def("create_window_callback",
             [](IWindowCallbackManager* self, const char* title, uint32_t width, uint32_t height,
                DockPreference dockPreference, const std::function<void(float)>& onDrawFn) {
                 return self->createWindowCallback(
                     title, width, height, dockPreference, takeCallbackReference(new PythonEventListener(onDrawFn)).get());
             },
             py::return_value_policy::reference)
        .def("remove_window_callback", &IWindowCallbackManager::removeWindowCallback)
        .def("get_window_callback_count", &IWindowCallbackManager::getWindowCallbackCount)
        .def("get_window_callback_at", &IWindowCallbackManager::getWindowCallbackAt, py::return_value_policy::reference)

        .def("create_window_set", &IWindowCallbackManager::createWindowSet, py::return_value_policy::reference)
        .def("destroy_window_set", &IWindowCallbackManager::destroyWindowSet)
        .def("get_default_window_set", &IWindowCallbackManager::getDefaultWindowSet)
        .def("attach_window_set_to_app_window", [unwrapAppWindow](IWindowCallbackManager* self, WindowSet* set, py::object window) {
            self->attachWindowSetToAppWindow(set, unwrapAppWindow(window));
        })
        .def("get_window_set_by_app_window", [unwrapAppWindow](IWindowCallbackManager* self, py::object window) {
            return self->getWindowSetByAppWindow(unwrapAppWindow(window));
        },
             py::return_value_policy::reference)
        .def("get_app_window_from_window_set", [wrapAppWindow](IWindowCallbackManager* self, WindowSet* set) {
            return wrapAppWindow(self->getAppWindowFromWindowSet(set));
        })

        .def("get_window_set_count", &IWindowCallbackManager::getWindowSetCount)
        .def("get_window_set_at", &IWindowCallbackManager::getWindowSetAt, py::return_value_policy::reference)

        .def("create_window_set_callback",
             [](IWindowCallbackManager* self, WindowSet* windowSet, const char* title, uint32_t width, uint32_t height,
                DockPreference dockPreference, const std::function<void(float)>& onDrawFn) {
                 return self->createWindowSetCallback(windowSet, title, width, height, dockPreference,
                                                      takeCallbackReference(new PythonEventListener(onDrawFn)).get());
             },
             py::return_value_policy::reference)
        .def("create_app_window_callback",
             [unwrapAppWindow](IWindowCallbackManager* self, py::object appWindow, const char* title, uint32_t width,
                uint32_t height, DockPreference dockPreference, const std::function<void(float)>& onDrawFn) {
                 return self->createAppWindowCallback(unwrapAppWindow(appWindow), title, width, height, dockPreference,
                                                      takeCallbackReference(new PythonEventListener(onDrawFn)).get());
             },
             py::return_value_policy::reference)
        .def("add_window_set_callback", &IWindowCallbackManager::addWindowSetCallback)
        .def("remove_window_set_callback", &IWindowCallbackManager::removeWindowSetCallback)
        .def("remove_app_window_callback", [unwrapAppWindow](IWindowCallbackManager* self, py::object window, IWindowCallback* callback) {
            self->removeAppWindowCallback(unwrapAppWindow(window), callback);
        })
        .def("move_callback_to_app_window", [unwrapAppWindow](IWindowCallbackManager* self, IWindowCallback* callback, py::object window) {
            self->moveCallbackToAppWindow(callback, unwrapAppWindow(window));
        })
        .def("get_window_set_callback_count", &IWindowCallbackManager::getWindowSetCallbackCount)
        .def("get_window_set_callback_at", &IWindowCallbackManager::getWindowSetCallbackAt,
             py::return_value_policy::reference)
        /**/;
}

}
}
}
