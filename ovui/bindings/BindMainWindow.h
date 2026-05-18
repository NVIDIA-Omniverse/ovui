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

#include <omni/ui/MainWindow.h>
#include <omni/ui/bind/BindMainWindow.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMainWindow(module& m)
{
    constexpr const char* mainWindowDoc = OMNIUI_PYBIND_CLASS_DOC(MainWindow);
    static constexpr char mainWindowConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(MainWindow, MainWindow);
    class_<MainWindow, std::shared_ptr<MainWindow>>(m, "MainWindow", mainWindowDoc)
        .def(init([](bool showForeground, kwargs kwargs) { OMNIUI_PYBIND_INIT(MainWindow, showForeground) }),
             arg("show_foreground") = false, mainWindowConstructorDoc)
        .def_property_readonly(
            "status_bar_frame", &MainWindow::getStatusBarFrame, OMNIUI_PYBIND_DOC_MainWindow_statusBarFrame)
        .def_property_readonly("main_frame", &MainWindow::getMainFrame, OMNIUI_PYBIND_DOC_MainWindow_mainFrame)
        .def_property_readonly("main_menu_bar", &MainWindow::getMainMenuBar, OMNIUI_PYBIND_DOC_MainWindow_mainMenuBar)
        .def_property("cpp_status_bar_enabled", &MainWindow::getCppStatusBarEnabled,
                      &MainWindow::setCppStatusBarEnabled, OMNIUI_PYBIND_DOC_MainWindow_cppStatusBarEnabled)
        .def_property("show_foreground", &MainWindow::isShowForeground, &MainWindow::setShowForeground,
                      OMNIUI_PYBIND_DOC_MainWindow_showForeground)
        .def("set_active", &MainWindow::setActive,
             arg("active"), arg("show_foreground") = true,
             "Set whether the MainWindow is in an active state")
        /* */;
}
