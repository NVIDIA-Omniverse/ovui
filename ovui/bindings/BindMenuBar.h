/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/MenuBar.h>
#include <omni/ui/MenuDelegate.h>
#include <omni/ui/bind/BindMenuBar.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMenuBar(module& m)
{
    constexpr const char* menuBarDoc = OMNIUI_PYBIND_CLASS_DOC(MenuBar);
    static constexpr char menuBarConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(MenuBar, MenuBar);
    class_<MenuBar, Menu, std::shared_ptr<MenuBar>>(m, "MenuBar", menuBarDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(MenuBar) }), menuBarConstructorDoc)
        /* */;
}
