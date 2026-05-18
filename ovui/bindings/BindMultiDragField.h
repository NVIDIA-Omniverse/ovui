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

#include <omni/ui/MultiDragField.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/bind/BindMultiDragField.h>
#include <omni/ui/bind/BindMultiField.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMultiDragField(module& m)
{
    constexpr const char* multiFloatDragFieldDoc = OMNIUI_PYBIND_CLASS_DOC(MultiFloatDragField);
    const char* multiFloatDragFieldConstructorDoc =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(MultiFloatDragField, MultiFloatDragField);

    // The float implementation of MultiDragField.
    class_<MultiFloatDragField, AbstractMultiField, std::shared_ptr<MultiFloatDragField>>(
        m, "MultiFloatDragField", multiFloatDragFieldDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(MultiFloatDragField) }))
        .def(init([](const std::shared_ptr<AbstractItemModel>& model, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(MultiFloatDragField, model)
        }))
        .def(init([](args args, kwargs kwargs) {
            auto argVec = SimpleListModel::create(argsToVector<double, float_>(args));
            OMNIUI_PYBIND_INIT(MultiFloatDragField, std::move(argVec))
        }), multiFloatDragFieldConstructorDoc)
        .def_property(
            "min", &MultiFloatDragField::getMin, &MultiFloatDragField::setMin, OMNIUI_PYBIND_DOC_MultiDragField_min)
        .def_property(
            "max", &MultiFloatDragField::getMax, &MultiFloatDragField::setMax, OMNIUI_PYBIND_DOC_MultiDragField_max)
        .def_property(
            "step", &MultiFloatDragField::getStep, &MultiFloatDragField::setStep, OMNIUI_PYBIND_DOC_MultiDragField_step)
        /**/;

    constexpr const char* multiIntDragFieldDoc = OMNIUI_PYBIND_CLASS_DOC(MultiIntDragField);
    static constexpr char multiIntDragFieldConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(MultiIntDragField, MultiIntDragField);

    // The int implementation of MultiDragField.
    class_<MultiIntDragField, AbstractMultiField, std::shared_ptr<MultiIntDragField>>(
        m, "MultiIntDragField", multiIntDragFieldDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(MultiIntDragField) }))
        .def(init([](const std::shared_ptr<AbstractItemModel>& model, kwargs kwargs) {
            OMNIUI_PYBIND_INIT(MultiIntDragField, model)
        }))
        .def(init([](args args, kwargs kwargs) {
            auto argVec = SimpleListModel::create(argsToVector<int, int_>(args));
            OMNIUI_PYBIND_INIT(MultiIntDragField, std::move(argVec))
        }), multiIntDragFieldConstructorDoc)
        .def_property("min", &MultiIntDragField::getMin, &MultiIntDragField::setMin, OMNIUI_PYBIND_DOC_MultiDragField_min)
        .def_property("max", &MultiIntDragField::getMax, &MultiIntDragField::setMax, OMNIUI_PYBIND_DOC_MultiDragField_max)
        .def_property(
            "step", &MultiIntDragField::getStep, &MultiIntDragField::setStep, OMNIUI_PYBIND_DOC_MultiDragField_step)
        /**/;
}
