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

#include <omni/ui/ItemModelHelper.h>
#include <omni/ui/bind/BindItemModelHelper.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapItemModelHelper(module& m)
{
    constexpr const char* itemModelHelperDoc = OMNIUI_PYBIND_CLASS_DOC(ItemModelHelper);
    class_<ItemModelHelper, std::shared_ptr<ItemModelHelper>>(m, "ItemModelHelper", itemModelHelperDoc)
        .def_property("model", &ItemModelHelper::getModel, &ItemModelHelper::setModel, return_value_policy::reference,
                      OMNIUI_PYBIND_DOC_ItemModelHelper_getModel);
}
