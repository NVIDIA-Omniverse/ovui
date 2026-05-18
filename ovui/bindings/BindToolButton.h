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
#include <omni/ui/ToolButton.h>
#include <omni/ui/bind/BindToolButton.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapToolButton(module& m)
{
    constexpr const char* toolButtonDoc = OMNIUI_PYBIND_CLASS_DOC(ToolButton);
    static constexpr char toolButtonConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ToolButton, ToolButton);

    class_<ToolButton, Button, ValueModelHelper, std::shared_ptr<ToolButton>>(m, "ToolButton", toolButtonDoc)
        .def(init([](const std::shared_ptr<AbstractValueModel>& model, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(ToolButton, model)
             }),
             arg("model") = nullptr, toolButtonConstructorDoc);
}
