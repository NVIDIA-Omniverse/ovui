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

#include <omni/ui/ValueModelHelper.h>
#include <omni/ui/bind/BindUtils.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapValueModelHelper(module& m)
{
    class_<ValueModelHelper, std::shared_ptr<ValueModelHelper>>(m, "ValueModelHelper",
    "The ValueModelHelper class provides the basic functionality for value widget classes. ValueModelHelper class is the\
     base class for every standard widget that uses a AbstractValueModel. ValueModelHelper is an abstract class and \
     itself cannot be instantiated. It provides a standard interface for interoperating with models.")
        .def_property("model", &ValueModelHelper::getModel, &ValueModelHelper::setModel, return_value_policy::reference);
}
