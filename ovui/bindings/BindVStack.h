/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
