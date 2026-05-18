/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
