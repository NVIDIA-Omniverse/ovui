/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/SceneContainerScope.h>
#include <omni/ui/scene/bind/BindAbstractContainer.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapAbstractContainer(module& m)
{
    constexpr const char* abstractContainerDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractContainer);

    class_<AbstractContainer, AbstractItem, std::shared_ptr<AbstractContainer>>(
        m, "AbstractContainer", abstractContainerDoc)
        // .def("add_child", &AbstractContainer::addChild, OMNIUI_PYBIND_DOC_AbstractContainer_addChild)
        .def("clear", &AbstractContainer::clear, OMNIUI_PYBIND_DOC_AbstractContainer_clear)
        .def("__enter__", [](std::shared_ptr<AbstractContainer>& self) { SceneContainerStack::instance().push(self); return self;})
        .def("__exit__", [](std::shared_ptr<AbstractContainer>& self, object exc_type, object exc_value,
                            object traceback) { SceneContainerStack::instance().pop(); });
}
