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

#include <omni/ui/MenuHelper.h>
#include <omni/ui/bind/BindMenuHelper.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMenuHelper(module& m)
{
    constexpr const char* menuHelperDoc = OMNIUI_PYBIND_CLASS_DOC(MenuHelper);
    static constexpr char menuHelperConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(MenuHelper, MenuHelper);
    class_<MenuHelper, std::shared_ptr<MenuHelper>>(m, "MenuHelper", menuHelperDoc)
        .def_property("text", &MenuHelper::getText, &MenuHelper::setText, OMNIUI_PYBIND_DOC_MenuHelper_text)
        .def_property("delegate", &MenuHelper::getDelegate, &MenuHelper::setDelegate)
        .def_property("hotkey_text", &MenuHelper::getHotkeyText, &MenuHelper::setHotkeyText,
                      OMNIUI_PYBIND_DOC_MenuHelper_hotkeyText)
        .def_property(
            "checkable", &MenuHelper::isCheckable, &MenuHelper::setCheckable, OMNIUI_PYBIND_DOC_MenuHelper_checkable)
        .def_property("hide_on_click", &MenuHelper::isHideOnClick, &MenuHelper::setHideOnClick,
                      OMNIUI_PYBIND_DOC_MenuHelper_hideOnClick)
        .def_property("menu_compatibility", &MenuHelper::isMenuCompatibility, &MenuHelper::setMenuCompatibility)
        .OMNIUI_PYBIND_DEF_CALLBACK(triggered, MenuHelper, Triggered)
        /* */;
}
