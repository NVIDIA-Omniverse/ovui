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
#include <omni/ui/IntField.h>
#include <omni/ui/bind/BindIntField.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapIntField(module& m)
{
    constexpr const char* intFieldDoc = OMNIUI_PYBIND_CLASS_DOC(IntField);
    static constexpr char intFieldConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(IntField, IntField);
    class_<IntField, AbstractField, std::shared_ptr<IntField>>(m, "IntField", intFieldDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(IntField, model)
             }),
             arg("model") = nullptr, intFieldConstructorDoc);
}
