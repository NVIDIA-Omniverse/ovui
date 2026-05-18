/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Menu.h>
#include <omni/ui/MenuDelegate.h>
#include <omni/ui/bind/BindMenu.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMenu(module& m)
{
    constexpr const char* menuDoc = OMNIUI_PYBIND_CLASS_DOC(Menu);
    static constexpr char menuConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Menu, Menu);

    class_<Menu, Stack, MenuHelper, std::shared_ptr<Menu>>(m, "Menu", menuDoc)
        .def(init([](std::string text, kwargs kwargs) { OMNIUI_PYBIND_INIT(Menu, text) }), arg("text") = "",
             menuConstructorDoc)
        .def_property_readonly("shown", &Menu::isShown, OMNIUI_PYBIND_DOC_Menu_shown)
        .def_static("get_current", &Menu::getCurrent, OMNIUI_PYBIND_DOC_Menu_getCurrent)
        .def("show", &Menu::show, OMNIUI_PYBIND_DOC_Menu_show)
        .def("show_at", &Menu::showAt, OMNIUI_PYBIND_DOC_Menu_showAt)
        .def("tear_at", &Menu::tearAt, OMNIUI_PYBIND_DOC_Menu_tearAt)
        .def("hide", &Menu::hide, OMNIUI_PYBIND_DOC_Menu_hide)
        .def("invalidate", &Menu::invalidate, OMNIUI_PYBIND_DOC_Menu_invalidate)
        .def("set_shown_changed_fn", wrapCallbackSetter(&Menu::setShownChangedFn), arg("fn"), OMNIUI_PYBIND_DOC_Menu_shown)
        .def_property("tearable", &Menu::isTearable, &Menu::setTearable, OMNIUI_PYBIND_DOC_Menu_tearable)
        .def_property_readonly("teared", &Menu::isTeared, OMNIUI_PYBIND_DOC_Menu_teared)
        .def("set_teared_changed_fn", wrapCallbackSetter(&Menu::setTearedChangedFn), arg("fn"),
             OMNIUI_PYBIND_DOC_Menu_teared)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_build, Menu, OnBuild)
        /* */;
}
