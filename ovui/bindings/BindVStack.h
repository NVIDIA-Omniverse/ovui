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

#include <omni/ui/VStack.h>
#include <omni/ui/bind/BindVStack.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapVStack(module& m)
{
    constexpr const char* vStackDoc = OMNIUI_PYBIND_CLASS_DOC(VStack);
    static constexpr char vStackConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(VStack, VStack);

    class_<VStack, Stack, std::shared_ptr<VStack>>(m, "VStack", vStackDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(VStack) }), vStackConstructorDoc);
}
