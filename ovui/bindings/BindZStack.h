/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/ZStack.h>
#include <omni/ui/bind/BindZStack.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapZStack(module& m)
{
    constexpr const char* zStackDoc = OMNIUI_PYBIND_CLASS_DOC(ZStack);
    static constexpr char zStackConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ZStack, ZStack);

    class_<ZStack, Stack, std::shared_ptr<ZStack>>(m, "ZStack", zStackDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(ZStack) }), zStackConstructorDoc);
}
