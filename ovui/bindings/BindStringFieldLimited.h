/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/StringFieldLimited.h>
#include <omni/ui/bind/BindStringFieldLimited.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapStringFieldLimited(module& m)
{
    constexpr const char* stringFieldLimitedDoc = OMNIUI_PYBIND_CLASS_DOC(StringFieldLimited);
    static constexpr char stringFieldLimitedConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(StringFieldLimited, StringFieldLimited);

    class_<StringFieldLimited, StringField, std::shared_ptr<StringFieldLimited>>(
        m, "StringFieldLimited", stringFieldLimitedDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(StringFieldLimited, model)
             }),
             arg("model") = nullptr, stringFieldLimitedConstructorDoc)
        .def_property("max_length", &StringFieldLimited::getMaxLength, &StringFieldLimited::setMaxLength,
                      OMNIUI_PYBIND_DOC_StringFieldLimited_maxLength)
        .OMNIUI_PYBIND_DEF_CALLBACK(character_limit_reached, StringFieldLimited, CharacterLimitReached)
        /* */;
}
