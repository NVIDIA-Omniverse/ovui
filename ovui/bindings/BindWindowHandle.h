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

#include <omni/ui/WindowHandle.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/BindWindowHandle.h>
#include <imgui/imgui_internal.h>

using namespace pybind11;

// Stub MSVC warning macros for non-MSVC builds
#ifndef OMNIUI_IGNOREWARNING_MSC_WITH_PUSH
#  ifdef _MSC_VER
#    define OMNIUI_IGNOREWARNING_MSC_WITH_PUSH(x) __pragma(warning(push)) __pragma(warning(disable : x))
#  else
#    define OMNIUI_IGNOREWARNING_MSC_WITH_PUSH(x)
#  endif
#endif
#ifndef OMNIUI_IGNOREWARNING_MSC_POP
#  ifdef _MSC_VER
#    define OMNIUI_IGNOREWARNING_MSC_POP __pragma(warning(pop))
#  else
#    define OMNIUI_IGNOREWARNING_MSC_POP
#  endif
#endif

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapWindowHandle(module& m)
{
    constexpr const char* windowHandleDoc = OMNIUI_PYBIND_CLASS_DOC(WindowHandle);

    enum_<WindowHandle::DockPosition>(m, "DockPosition")
        .value("RIGHT", WindowHandle::DockPosition::eRight)
        .value("LEFT", WindowHandle::DockPosition::eLeft)
        .value("TOP", WindowHandle::DockPosition::eTop)
        .value("BOTTOM", WindowHandle::DockPosition::eBottom)
        .value("SAME", WindowHandle::DockPosition::eSame);

    OMNIUI_IGNOREWARNING_MSC_WITH_PUSH(4996) // deprecation for WindowHandle::setVisible
    class_<WindowHandle, std::shared_ptr<WindowHandle>>(m, "WindowHandle", windowHandleDoc)
        .def("notify_app_window_change", &WindowHandle::notifyAppWindowChange,
             OMNIUI_PYBIND_DOC_WindowHandle_notifyAppWindowChange)
        .def_property_readonly("title", &WindowHandle::getTitle, OMNIUI_PYBIND_DOC_WindowHandle_getTitle)
        .def_property("position_x", &WindowHandle::getPositionX, &WindowHandle::setPositionX,
                      OMNIUI_PYBIND_DOC_WindowHandle_getPositionX)
        .def_property("position_y", &WindowHandle::getPositionY, &WindowHandle::setPositionY,
                      OMNIUI_PYBIND_DOC_WindowHandle_getPositionY)
        .def_property("width", &WindowHandle::getWidth, &WindowHandle::setWidth, OMNIUI_PYBIND_DOC_WindowHandle_getWidth)
        .def_property(
            "height", &WindowHandle::getHeight, &WindowHandle::setHeight, OMNIUI_PYBIND_DOC_WindowHandle_getHeight)
        .def_property(
            "visible",
            [](const WindowHandle& self) -> pybind11::object {
                // Special handling for Status Bar visibility, since it is not an omni.ui Window
                std::string title = self.getTitle();
                if (title == "Status Bar")
                {
                    ImGuiWindow* window = ImGui::FindWindowByName(title.c_str());
                    if (window)
                    {
                        return pybind11::cast(!window->Hidden);
                    }
                }
                return pybind11::none();
            },
            [](WindowHandle& self, const bool& visible) {
                std::string title = self.getTitle();
                if (title == "Status Bar")
                {
                    ImGuiWindow* window = ImGui::FindWindowByName(title.c_str());
                    if (window)
                    {
                        window->Hidden = !visible;
                        // A hack to hide the window. It should be hidden for about 414 days.
                        window->HiddenFramesCanSkipItems = visible ? 0 : std::numeric_limits<int>::max();
                    }
                }
                else
                {
                    self.setVisible(visible);  // print deprecation message. And error message in the future.
                }
            }, OMNIUI_PYBIND_DOC_WindowHandle_isVisible)
        .def_property("dock_tab_bar_visible", &WindowHandle::isDockTabBarVisible, &WindowHandle::setDockTabBarVisible,
                      OMNIUI_PYBIND_DOC_WindowHandle_isDockTabBarVisible)
        .def_property("dock_tab_bar_enabled", &WindowHandle::isDockTabBarEnabled, &WindowHandle::setDockTabBarEnabled,
                      OMNIUI_PYBIND_DOC_WindowHandle_isDockTabBarEnabled)
        .def_property("dock_order", &WindowHandle::getDockOrder, &WindowHandle::setDockOrder,
                      OMNIUI_PYBIND_DOC_WindowHandle_getDockOrder)
        .def_property_readonly("docked", &WindowHandle::isDocked, OMNIUI_PYBIND_DOC_WindowHandle_isDocked)
        .def_property_readonly("dock_id", &WindowHandle::getDockId, OMNIUI_PYBIND_DOC_WindowHandle_getDockId)
        .def("undock", &WindowHandle::undock, OMNIUI_PYBIND_DOC_WindowHandle_undock)
        .def("dock_in", &WindowHandle::dockIn, arg("window"), arg("dock_position"), arg("ratio") = 0.5f,
             OMNIUI_PYBIND_DOC_WindowHandle_dockIn)
        .def("focus", &WindowHandle::focus, OMNIUI_PYBIND_DOC_WindowHandle_focus)
        .def("is_selected_in_dock", &WindowHandle::isSelectedInDock, OMNIUI_PYBIND_DOC_WindowHandle_isSelectedInDock)
        .def("__repr__", [](const WindowHandle& self) { return self.getTitle(); });
    OMNIUI_IGNOREWARNING_MSC_POP
}
