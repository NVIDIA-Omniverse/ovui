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
