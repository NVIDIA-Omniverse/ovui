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
