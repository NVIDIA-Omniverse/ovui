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
#include <omni/ui/MenuHelper.h>
#include <omni/ui/bind/BindMenuDelegate.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Class-helper that redirects all the abstract methods to python so that it's possible to reimplement this class
 * in python.
 */
class PyMenuDelegate : public MenuDelegate
{
public:
    static std::shared_ptr<PyMenuDelegate> create()
    {
        return std::make_shared<PyMenuDelegate>();
    }

    void buildItem(const MenuHelper* item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, MenuDelegate, MenuDelegate::buildItem, build_item, item);
    }

    void buildTitle(const MenuHelper* item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, MenuDelegate, MenuDelegate::buildTitle, build_title, item);
    }

    void buildStatus(const MenuHelper* item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, MenuDelegate, MenuDelegate::buildStatus, build_status, item);
    }
};

OMNIUI_NAMESPACE_CLOSE_SCOPE

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMenuDelegate(module& m)
{
    constexpr const char* menuDelegateDoc = OMNIUI_PYBIND_CLASS_DOC(MenuDelegate);
    static constexpr char menuDelegateConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(MenuDelegate, MenuDelegate);

    class_<MenuDelegate, PyMenuDelegate, std::shared_ptr<MenuDelegate>>(m, "MenuDelegate", menuDelegateDoc)
        .def(init([](kwargs kwargs) -> std::shared_ptr<PyMenuDelegate> { OMNIUI_PYBIND_INIT(PyMenuDelegate) }),
             menuDelegateConstructorDoc)
        .def("build_item", &MenuDelegate::buildItem, arg("item"), OMNIUI_PYBIND_DOC_MenuDelegate_buildItem)
        .def("build_title", &MenuDelegate::buildTitle, arg("item"), OMNIUI_PYBIND_DOC_MenuDelegate_buildTitle)
        .def("build_status", &MenuDelegate::buildStatus, arg("item"), OMNIUI_PYBIND_DOC_MenuDelegate_buildStatus)
        .def_static("set_default_delegate", &MenuDelegate::setDefaultDelegate, arg("delegate"),
                    OMNIUI_PYBIND_DOC_MenuDelegate_setDefaultDelegate)
        .def_property("propagate", &MenuDelegate::isPropagate, &MenuDelegate::setPropagate)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_build_item, MenuDelegate, OnBuildItem)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_build_title, MenuDelegate, OnBuildTitle)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_build_status, MenuDelegate, OnBuildStatus)
        /* */;
}
