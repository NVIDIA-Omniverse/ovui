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
#include <omni/ui/StringField.h>
#include <omni/ui/bind/BindStringField.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapStringField(module& m)
{
    constexpr const char* stringFieldDoc = OMNIUI_PYBIND_CLASS_DOC(StringField);
    static constexpr char stringFieldConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(StringField, StringField);

    class_<StringField, AbstractField, std::shared_ptr<StringField>>(m, "StringField", stringFieldDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(StringField, model, nullptr)
             }),
             arg("model") = nullptr, stringFieldConstructorDoc)
        .def_property("password_mode", &StringField::isPasswordMode, &StringField::setPasswordMode,
                      OMNIUI_PYBIND_DOC_StringField_passwordMode)
        .def_property(
            "read_only", &StringField::isReadOnly, &StringField::setReadOnly, OMNIUI_PYBIND_DOC_StringField_readOnly)
        .def_property(
            "multiline", &StringField::isMultiline, &StringField::setMultiline, OMNIUI_PYBIND_DOC_StringField_multiline)
        .def_property("allow_tab_input", &StringField::isTabInputAllowed, &StringField::setTabInputAllowed,
                      OMNIUI_PYBIND_DOC_StringField_allowTabInput)
        /* */;
}
