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

#include <omni/ui/CollapsableFrame.h>
#include <omni/ui/bind/BindCollapsableFrame.h>
#include <omni/ui/bind/Pybind.h>

#include <memory>
#include <string>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapCollapsableFrame(module& m)
{
    constexpr const char* collapsableFrameDoc = OMNIUI_PYBIND_CLASS_DOC(CollapsableFrame);
    static constexpr char collapsableFrameConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(CollapsableFrame, CollapsableFrame);

    class_<CollapsableFrame, Frame, std::shared_ptr<CollapsableFrame>>(m, "CollapsableFrame", collapsableFrameDoc)
        .def(init([](const std::string& title, kwargs kwargs) { OMNIUI_PYBIND_INIT(CollapsableFrame, title) }),
             arg("title") = std::string{}, collapsableFrameConstructorDoc)
        .def_property("collapsed", &CollapsableFrame::isCollapsed, &CollapsableFrame::setCollapsed,
                      OMNIUI_PYBIND_DOC_CollapsableFrame_collapsed)
        .def_property(
            "title", &CollapsableFrame::getTitle, &CollapsableFrame::setTitle, OMNIUI_PYBIND_DOC_CollapsableFrame_title)
        .def_property("alignment", &CollapsableFrame::getAlignment, &CollapsableFrame::setAlignment,
                      OMNIUI_PYBIND_DOC_CollapsableFrame_alignment)
        .OMNIUI_PYBIND_DEF_CALLBACK(build_header, CollapsableFrame, BuildHeader)
        .def("set_collapsed_changed_fn", wrapCallbackSetter(&CollapsableFrame::setCollapsedChangedFn), arg("fn"),
             OMNIUI_PYBIND_DOC_CollapsableFrame_collapsed);
}
