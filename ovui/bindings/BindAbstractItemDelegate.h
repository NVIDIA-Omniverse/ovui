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

#include <omni/ui/AbstractItemDelegate.h>
#include <omni/ui/bind/BindAbstractItemDelegate.h>
#include <omni/ui/bind/BindUtils.h>
#include <pybind11/stl.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Class-helper that redirects all the abstract methods to python so that it's possible to reimplement this class
 * in python.
 */
class PyAbstractItemDelegate : public AbstractItemDelegate
{
public:
    void buildBranch(const std::shared_ptr<AbstractItemModel>& model,
                     const std::shared_ptr<const AbstractItemModel::AbstractItem>& item = nullptr,
                     size_t index = 0,
                     uint32_t level = 0,
                     bool expanded = false) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, AbstractItemDelegate, AbstractItemDelegate::buildBranch, build_branch, model,
                                  item, index, level, expanded);
    }

    void buildWidget(const std::shared_ptr<AbstractItemModel>& model,
                     const std::shared_ptr<const AbstractItemModel::AbstractItem>& item = nullptr,
                     size_t index = 0,
                     uint32_t level = 0,
                     bool expanded = false) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(void, AbstractItemDelegate, build_widget, model, item, index, level, expanded);
    }

    void buildHeader(size_t index = 0) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, AbstractItemDelegate, AbstractItemDelegate::buildHeader, build_header, index);
    }
};

OMNIUI_NAMESPACE_CLOSE_SCOPE

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapAbstractItemDelegate(module& m)
{
    constexpr const char* abstractItemDelegateDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractItemDelegate);
    constexpr const char* abstractItemDelegateConstructorDoc =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(AbstractItemDelegate, AbstractItemDelegate);

    class_<AbstractItemDelegate, PyAbstractItemDelegate, std::shared_ptr<AbstractItemDelegate>>(
        m, "AbstractItemDelegate", abstractItemDelegateDoc)
        .def(init<>(), abstractItemDelegateConstructorDoc)
        .def("build_branch", &AbstractItemDelegate::buildBranch, arg("model"), arg("item") = nullptr,
             arg("column_id") = 0, arg("level") = 0, arg("expanded") = false,
             OMNIUI_PYBIND_DOC_AbstractItemDelegate_buildBranch)
        .def("build_widget", &AbstractItemDelegate::buildWidget, arg("model"), arg("item") = nullptr, arg("index") = 0,
             arg("level") = 0, arg("expanded") = false, OMNIUI_PYBIND_DOC_AbstractItemDelegate_buildWidget)
        .def("build_header", &AbstractItemDelegate::buildHeader, arg("column_id") = 0,
             OMNIUI_PYBIND_DOC_AbstractItemDelegate_buildHeader)
        /* */;
}
