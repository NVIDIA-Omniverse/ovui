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

#include <omni/ui/MenuDelegate.h>
#include <omni/ui/MenuItem.h>
#include <omni/ui/bind/BindMenuItem.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMenuItem(module& m)
{
    constexpr const char* menuItemDoc = OMNIUI_PYBIND_CLASS_DOC(MenuItem);
    static constexpr char menuItemConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(MenuItem, MenuItem);
    class_<MenuItem, Widget, MenuHelper, std::shared_ptr<MenuItem>>(m, "MenuItem", menuItemDoc)
        .def(init([](std::string title, kwargs kwargs) { OMNIUI_PYBIND_INIT(MenuItem, title) }), menuItemConstructorDoc)
        /* */;
}
