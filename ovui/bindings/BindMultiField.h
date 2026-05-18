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

#include <omni/ui/MultiField.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/bind/BindMultiField.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMultiField(module& m)
{
    constexpr const char* multiFloatFieldDoc = OMNIUI_PYBIND_CLASS_DOC(MultiFloatField);
    static constexpr char multiFloatFieldConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(MultiFloatField, MultiFloatField);

    // The float implementation of MultiField.
    class_<MultiFloatField, AbstractMultiField, std::shared_ptr<MultiFloatField>>(m, "MultiFloatField", multiFloatFieldDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(MultiFloatField) }))
        .def(init([](const std::shared_ptr<AbstractItemModel>& model, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(MultiFloatField, model)
        }))
        .def(init([](args args, kwargs kwargs) {
            auto argVec = argsToVector<float, float_>(args);
            OMNIUI_PYBIND_INIT(MultiFloatField, SimpleListModel::create(std::move(argVec)))
        }), multiFloatFieldConstructorDoc);

    constexpr const char* multiIntFieldDoc = OMNIUI_PYBIND_CLASS_DOC(MultiIntField);
    static constexpr char multiIntFieldConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(MultiIntField, MultiIntField);

    // The int implementation of MultiField.
    class_<MultiIntField, AbstractMultiField, std::shared_ptr<MultiIntField>>(m, "MultiIntField", multiIntFieldDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(MultiIntField) }))
        .def(init([](const std::shared_ptr<AbstractItemModel>& model, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(MultiIntField, model)
        }))
        .def(init([](args args, kwargs kwargs) {
            auto argVec = argsToVector<int, int_>(args);
            OMNIUI_PYBIND_INIT(MultiIntField, SimpleListModel::create(std::move(argVec)))
        }), multiIntFieldConstructorDoc);

    constexpr const char* multiStringFieldDoc = OMNIUI_PYBIND_CLASS_DOC(MultiStringField);
    static constexpr char multiStringFieldConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(MultiStringField, MultiStringField);

    // The string implementation of MultiField.
    class_<MultiStringField, AbstractMultiField, std::shared_ptr<MultiStringField>>(
        m, "MultiStringField", multiStringFieldDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(MultiStringField) }))
        .def(init([](const std::shared_ptr<AbstractItemModel>& model, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(MultiStringField, model)
        }))
        .def(init([](args args, kwargs kwargs) {
            auto argVec = argsToVector<std::string>(args);
            OMNIUI_PYBIND_INIT(MultiStringField, SimpleListModel::create(std::move(argVec)))
        }), multiStringFieldConstructorDoc);
}
