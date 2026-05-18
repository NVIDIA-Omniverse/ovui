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

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/FloatField.h>
#include <omni/ui/bind/BindFloatField.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapFloatField(module& m)
{
    constexpr const char* floatFieldDoc = OMNIUI_PYBIND_CLASS_DOC(FloatField);
    static constexpr char floatFieldConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(FloatField, FloatField);
    class_<FloatField, AbstractField, std::shared_ptr<FloatField>>(m, "FloatField", floatFieldDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(FloatField, model)
             }),
             arg("model") = nullptr, floatFieldConstructorDoc)
        .def_property("precision", &FloatField::getPrecision, &FloatField::setPrecision, OMNIUI_PYBIND_DOC_FloatField_precision)
        /* */;
}
