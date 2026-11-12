/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindWindow.h" // getCallingPythonModuleName

#include <omni/ui/ToolBar.h>
#include <omni/ui/Window.h>
#include <omni/ui/bind/BindToolBar.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapToolBar(module& m)
{
    enum_<ToolBar::Axis>(m, "ToolBarAxis").value("X", ToolBar::Axis::eX).value("Y", ToolBar::Axis::eY);

    constexpr const char* toolBarDoc = OMNIUI_PYBIND_CLASS_DOC(ToolBar);
    static constexpr char toolBarConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ToolBar, ToolBar);
    class_<ToolBar, Window, std::shared_ptr<ToolBar>>(m, "ToolBar", toolBarDoc)
        .def(init([](std::string title, kwargs kwargs) {
                 // Capture the calling Python module BEFORE releasing the GIL — used by the
                 // extension-usage telemetry hook to attribute clicks back to the owning ext.
                 const std::string ownerModule = getCallingPythonModuleName();
                 std::shared_ptr<ToolBar> result;
                 {
                     pybind11::gil_scoped_release gil;
                     result = ToolBar::create(title);
                 }
                 if (result)
                 {
                     result->setOwnerModule(ownerModule);
                     OMNIUI_PYBIND_INIT_BEGIN
                         OMNIUI_PYBIND_INIT_ToolBar
                     OMNIUI_PYBIND_INIT_END
                 }
                 return result;
             }),
             arg("title"), toolBarConstructorDoc)
        .def_property("axis", &ToolBar::getAxis, &ToolBar::setAxis)
        .def("set_axis_changed_fn", [](ToolBar& self, std::function<void(ToolBar::Axis)> fn) {
            self.setAxisChangedFn(wrapPythonCallback(std::move(fn)));
        });
}
