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

#include <omni/ui/Frame.h>
#include <omni/ui/Window.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/BindWindow.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapWindow(module& m)
{
    enum_<Window::DockPreference>(m, "DockPreference")
        .value("DISABLED", Window::DockPreference::eDisabled)
        .value("MAIN", Window::DockPreference::eMain)
        .value("RIGHT", Window::DockPreference::eRight)
        .value("LEFT", Window::DockPreference::eLeft)
        .value("RIGHT_TOP", Window::DockPreference::eRightTop)
        .value("RIGHT_BOTTOM", Window::DockPreference::eRightBottom)
        .value("LEFT_BOTTOM", Window::DockPreference::eLeftBottom);

    enum_<Window::DockPolicy>(m, "DockPolicy")
        .value("DO_NOTHING", Window::DockPolicy::eDoNothing)
        .value("CURRENT_WINDOW_IS_ACTIVE", Window::DockPolicy::eCurrentWindowIsActive)
        .value("TARGET_WINDOW_IS_ACTIVE", Window::DockPolicy::eTargetWindowIsActive);

    enum_<Window::FocusPolicy>(m, "FocusPolicy")
        .value("DEFAULT", Window::FocusPolicy::eDefault)
        .value("FOCUS_ON_LEFT_MOUSE_DOWN", Window::FocusPolicy::eFocusOnLeftMouseDown)
        .value("FOCUS_ON_ANY_MOUSE_DOWN", Window::FocusPolicy::eFocusOnAnyMouseDown)
        .value("FOCUS_ON_HOVER", Window::FocusPolicy::eFocusOnHover);

    m.attr("WINDOW_FLAGS_NONE") = int_(Window::kWindowFlagNone);
    m.attr("WINDOW_FLAGS_NO_TITLE_BAR") = int_(Window::kWindowFlagNoTitleBar);
    m.attr("WINDOW_FLAGS_NO_RESIZE") = int_(Window::kWindowFlagNoResize);
    m.attr("WINDOW_FLAGS_NO_MOVE") = int_(Window::kWindowFlagNoMove);
    m.attr("WINDOW_FLAGS_NO_SCROLLBAR") = int_(Window::kWindowFlagNoScrollbar);
    m.attr("WINDOW_FLAGS_NO_SCROLL_WITH_MOUSE") = int_(Window::kWindowFlagNoScrollWithMouse);
    m.attr("WINDOW_FLAGS_NO_COLLAPSE") = int_(Window::kWindowFlagNoCollapse);
    m.attr("WINDOW_FLAGS_NO_BACKGROUND") = int_(Window::kWindowFlagNoBackground);
    m.attr("WINDOW_FLAGS_NO_SAVED_SETTINGS") = int_(Window::kWindowFlagNoSavedSettings);
    m.attr("WINDOW_FLAGS_NO_MOUSE_INPUTS") = int_(Window::kWindowFlagNoMouseInputs);
    m.attr("WINDOW_FLAGS_MENU_BAR") = int_(Window::kWindowFlagMenuBar);
    m.attr("WINDOW_FLAGS_SHOW_HORIZONTAL_SCROLLBAR") = int_(Window::kWindowFlagShowHorizontalScrollbar);
    m.attr("WINDOW_FLAGS_NO_FOCUS_ON_APPEARING") = int_(Window::kWindowFlagNoFocusOnAppearing);
    m.attr("WINDOW_FLAGS_FORCE_VERTICAL_SCROLLBAR") = int_(Window::kWindowFlagForceVerticalScrollbar);
    m.attr("WINDOW_FLAGS_FORCE_HORIZONTAL_SCROLLBAR") = int_(Window::kWindowFlagForceHorizontalScrollbar);
    m.attr("WINDOW_FLAGS_NO_DOCKING") = int_(Window::kWindowFlagNoDocking);
    m.attr("WINDOW_FLAGS_POPUP") = int_(Window::kWindowFlagPopup);
    m.attr("WINDOW_FLAGS_MODAL") = int_(Window::kWindowFlagModal);
    m.attr("WINDOW_FLAGS_NO_CLOSE") = int_(Window::kWindowFlagNoClose);

    constexpr const char* windowDoc = OMNIUI_PYBIND_CLASS_DOC(Window);
    static constexpr char windowConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Window, Window);

    m.def("dock_window_in_window", Window::dockWindowInWindow, OMNIUI_PYBIND_DOC_Window_dockWindowInWindow);
    // Unlike IEditor::getEditorWindowWidth and IEditor::getEditorWindowHeight that are accessible from Python, the
    // following functions are in points and can be used when computing sizes with ovui.
    m.def("get_main_window_width", Window::getMainWindowWidth, OMNIUI_PYBIND_DOC_Window_getMainWindowWidth);
    m.def("get_main_window_height", Window::getMainWindowHeight, OMNIUI_PYBIND_DOC_Window_getMainWindowHeight);

    class_<Window, WindowHandle, std::shared_ptr<Window>>(m, "Window", windowDoc)
        .def(init([](std::string title, Window::DockPreference dockPreference, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(Window, title, dockPreference)
             }),
             arg("title"), arg("dockPreference") = Window::DockPreference::eDisabled, windowConstructorDoc)
        .def("destroy", &Window::destroy, OMNIUI_PYBIND_DOC_Window_destroy)
        .def("notify_app_window_change", &Window::notifyAppWindowChange, OMNIUI_PYBIND_DOC_Window_notifyAppWindowChange)
        .def("get_window_callback", &Window::getWindowCallback, OMNIUI_PYBIND_DOC_Window_getWindowCallback,
             pybind11::return_value_policy::reference)
        .def("move_to_app_window", &Window::moveToAppWindow, OMNIUI_PYBIND_DOC_Window_moveToAppWindow)
        .def("set_top_modal", &Window::setTopModal, OMNIUI_PYBIND_DOC_Window_setTopModal)
        .def_property("visible", &Window::isVisible, &Window::setVisible, OMNIUI_PYBIND_DOC_Window_visible)
        .def_property("title", &Window::getTitle, &Window::setTitle, OMNIUI_PYBIND_DOC_Window_title)
        .def_property("flags", &Window::getFlags, &Window::setFlags, OMNIUI_PYBIND_DOC_Window_flags)
        .def_property("padding_x", &Window::getPaddingX, &Window::setPaddingX, OMNIUI_PYBIND_DOC_Window_paddingX)
        .def_property("padding_y", &Window::getPaddingY, &Window::setPaddingY, OMNIUI_PYBIND_DOC_Window_paddingY)
        .def_property("width", &Window::getWidth, &Window::setWidth, OMNIUI_PYBIND_DOC_Window_width)
        .def_property("height", &Window::getHeight, &Window::setHeight, OMNIUI_PYBIND_DOC_Window_heigh)
        .def_property("position_x", &Window::getPositionX, &Window::setPositionX, OMNIUI_PYBIND_DOC_Window_positionX)
        .def_property("position_y", &Window::getPositionY, &Window::setPositionY, OMNIUI_PYBIND_DOC_Window_positionY)
        .def("setPosition", &Window::setPosition, arg("x"), arg("y"), OMNIUI_PYBIND_DOC_Window_setPosition)
        .def_property("auto_resize", &Window::getAutoResize, &Window::setAutoResize, OMNIUI_PYBIND_DOC_Window_autoResize)
        .def_property("noTabBar", &Window::getNoTabBar, &Window::setNoTabBar, OMNIUI_PYBIND_DOC_Window_noTabBar)
        .def_property("tabBar_tooltip", &Window::getTabBarTooltip, &Window::setTabBarTooltip, OMNIUI_PYBIND_DOC_Window_tabBarTooltip)
        .def_property("exclusive_keyboard", &Window::isExclusiveKeyboard, &Window::setExclusiveKeyboard,
                      OMNIUI_PYBIND_DOC_Window_exclusiveKeyboard)
        .def_property("detachable", &Window::isDetachable, &Window::setDetachable, OMNIUI_PYBIND_DOC_Window_detachable)
        .def_property_readonly("docked", &Window::isDocked, OMNIUI_PYBIND_DOC_Window_docked)
        .def_property_readonly("selected_in_dock", &Window::isSelectedInDock, OMNIUI_PYBIND_DOC_Window_selectedInDock)
        .def_property_readonly("frame", &Window::getFrame, OMNIUI_PYBIND_DOC_Window_frame)
        .def_property_readonly("menu_bar", &Window::getMenuBar)
        .def_property_readonly("focused", &Window::getFocused, OMNIUI_PYBIND_DOC_Window_focused)
        .def_property("focus_policy", &Window::getFocusPolicy, &Window::setFocusPolicy, OMNIUI_PYBIND_DOC_Window_focusPolicy)
        .def_property_readonly("app_window", &Window::getAppWindow)
        .def_property("raster_policy", &Window::getRasterPolicy, &Window::setRasterPolicy, OMNIUI_PYBIND_DOC_Window_getRasterPolicy)
        .def_property("fill_app_window", &Window::getFillAppWindow, &Window::setFillAppWindow, OMNIUI_PYBIND_DOC_Window_fillAppWindow)
        .def("set_active", &Window::setActive, arg("active"), "Set whether the Window is in an active state")

        .def("set_visibility_changed_fn",
             [](Window& self, std::function<void(bool)> fn) {
                if(fn)
                {
                    return self.setVisibilityChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setVisibilityChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_visible)
        .def("set_width_changed_fn",
             [](Window& self, std::function<void(const float&)> fn) {
                if(fn)
                {
                    return self.setWidthChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setWidthChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_width)
        .def("set_height_changed_fn",
             [](Window& self, std::function<void(const float&)> fn) {
                if(fn)
                {
                    return self.setHeightChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setHeightChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_heigh)
        .def("set_position_x_changed_fn",
             [](Window& self, std::function<void(const float&)> fn) {
                if(fn)
                {
                    return self.setPositionXChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setPositionXChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_positionX)
        .def("set_position_y_changed_fn",
             [](Window& self, std::function<void(const float&)> fn) {
                if(fn)
                {
                    return self.setPositionYChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setPositionYChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_positionY)
        .def("set_docked_changed_fn",
             [](Window& self, std::function<void(const bool&)> fn) {
                if (fn)
                {
                    return self.setDockedChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setDockedChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_docked)
        .def("set_selected_in_dock_changed_fn",
             [](Window& self, std::function<void(const bool&)> fn) {
                if(fn)
                {
                    return self.setSelectedInDockChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setSelectedInDockChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_selectedInDock)
        .OMNIUI_PYBIND_DEF_CALLBACK(key_pressed, Window, KeyPressed)
        .def("dock_in_window", &Window::dockInWindow, arg("title"), arg("dockPosition"), arg("ratio") = 0.5,
             OMNIUI_PYBIND_DOC_Window_dockInWindow)
        .def("deferred_dock_in", &Window::deferredDockIn, arg("target_window"),
             arg("active_window") = Window::DockPolicy::eDoNothing, OMNIUI_PYBIND_DOC_Window_deferredDockIn)
        .def("set_focused_changed_fn",
             [](Window& self, std::function<void(const bool&)> fn) {
                if(fn)
                {
                    return self.setFocusedChangedFn(wrapPythonCallback(std::move(fn)));
                }
                else
                {
                    return self.setFocusedChangedFn(nullptr);
                }
             },
             OMNIUI_PYBIND_DOC_Window_focused)
        .def("move_to_new_os_window", &Window::moveToNewOSWindow, OMNIUI_PYBIND_DOC_Window_moveToNewOSWindow)
        .def("move_to_main_os_window", &Window::moveToMainOSWindow, OMNIUI_PYBIND_DOC_Window_moveToMainOSWindow)
    ;
}
