/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/AbstractField.h>
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/bind/BindAbstractField.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapField(module& m)
{
    constexpr const char* abstractFieldDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractField);

    class_<AbstractField, Widget, ValueModelHelper, std::shared_ptr<AbstractField>>(m, "AbstractField", abstractFieldDoc)
        .def("focus_keyboard", &AbstractField::focusKeyboard, arg("focus") = true,
             OMNIUI_PYBIND_DOC_AbstractField_focusKeyboard);
}
