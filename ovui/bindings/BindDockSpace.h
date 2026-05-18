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

#include <omni/ui/DockSpace.h>
#include <omni/ui/bind/BindDockSpace.h>
#include <omni/ui/bind/BindUtils.h>
#include <pybind11/operators.h>

using namespace pybind11;

namespace omni
{
namespace ui
{
namespace windowmanager
{
struct WindowSet
{
};
}
}
}


OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapDockSpace(module& m)
{
    constexpr const char* dockSpaceDoc = OMNIUI_PYBIND_CLASS_DOC(DockSpace);
    static constexpr char dockSpaceConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(DockSpace, DockSpace);
    class_<DockSpace, std::shared_ptr<DockSpace>>(m, "DockSpace", dockSpaceDoc)
        .def(init([](pybind11::object windowSetPy, kwargs kwargs) {
                 omni::ui::windowmanager::WindowSet* windowSet = nullptr;
                 if (!windowSetPy.is_none())
                 {
                     windowSet = pybind11::cast<omni::ui::windowmanager::WindowSet*>(windowSetPy);
                 }
                 OMNIUI_PYBIND_INIT(DockSpace, windowSet)
        }), dockSpaceConstructorDoc)
        .def_property_readonly("dock_frame", &DockSpace::getDockFrame, OMNIUI_PYBIND_DOC_DockSpace_dockFrame)
        /**/;
}
