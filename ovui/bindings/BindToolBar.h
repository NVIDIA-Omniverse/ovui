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
        .def(init([](std::string title, kwargs kwargs) { OMNIUI_PYBIND_INIT(ToolBar, title) }), arg("title"),
             toolBarConstructorDoc)
        .def_property("axis", &ToolBar::getAxis, &ToolBar::setAxis)
        .def("set_axis_changed_fn", [](ToolBar& self, std::function<void(ToolBar::Axis)> fn) {
            self.setAxisChangedFn(wrapPythonCallback(std::move(fn)));
        });
}
