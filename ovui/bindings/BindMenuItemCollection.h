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
