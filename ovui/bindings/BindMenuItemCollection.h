/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/MenuDelegate.h>
#include <omni/ui/MenuItemCollection.h>
#include <omni/ui/bind/BindMenuItemCollection.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMenuItemCollection(module& m)
{
    constexpr const char* menuItemCollectionDoc = OMNIUI_PYBIND_CLASS_DOC(MenuItemCollection);
    static constexpr char menuItemCollectionConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(MenuItemCollection, MenuItemCollection);
    class_<MenuItemCollection, Menu, std::shared_ptr<MenuItemCollection>>(m, "MenuItemCollection", menuItemCollectionDoc)
        .def(init([](const std::string& text, kwargs kwargs) { OMNIUI_PYBIND_INIT(MenuItemCollection, text) }),
             arg("text") = "", menuItemCollectionConstructorDoc)
        /* */;
}
