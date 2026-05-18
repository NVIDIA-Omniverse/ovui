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
#include <omni/ui/CheckBox.h>
#include <omni/ui/bind/BindCheckBox.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapCheckBox(module& m)
{
    constexpr const char* checkBoxDoc = OMNIUI_PYBIND_CLASS_DOC(CheckBox);
    static constexpr char checkBoxConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(CheckBox, CheckBox);

    class_<CheckBox, Widget, ValueModelHelper, std::shared_ptr<CheckBox>>(m, "CheckBox", checkBoxDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(CheckBox, model)
             }),
             arg("model") = nullptr, checkBoxConstructorDoc);
}
