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

#include <omni/ui/Container.h>
#include <omni/ui/ContainerScope.h>
#include <omni/ui/bind/BindContainer.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE
OMNIUI_NAMESPACE_USING_DIRECTIVE
OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapContainer(module& m)
{
    constexpr const char* containerDoc = OMNIUI_PYBIND_CLASS_DOC(Container);

    class_<Container, Widget, std::shared_ptr<Container>>(
        m, "Container", "Base class for all UI containers. Container can hold one or many other :class:`omni.ui.Widget` s")
        .def("add_child", &Container::addChild, OMNIUI_PYBIND_DOC_Container_addChild)
        .def("clear", &Container::clear, OMNIUI_PYBIND_DOC_Container_clear)
        .def("__enter__", [](std::shared_ptr<Container> self) { ContainerStack::instance().push(self); return self;})
        .def("__exit__", [](std::shared_ptr<Container> self, object exc_type, object exc_value, object traceback) {
            ContainerStack::instance().pop();
        });
}
