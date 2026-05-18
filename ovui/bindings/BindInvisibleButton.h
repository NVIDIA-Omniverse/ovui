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

#include <omni/ui/InvisibleButton.h>
#include <omni/ui/bind/BindInvisibleButton.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapInvisibleButton(module& m)
{
    constexpr const char* invisibleButtonDoc = OMNIUI_PYBIND_CLASS_DOC(InvisibleButton);
    constexpr char invisibleButtonConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(InvisibleButton, InvisibleButton);

    class_<InvisibleButton, Widget, std::shared_ptr<InvisibleButton>>(m, "InvisibleButton", invisibleButtonDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(InvisibleButton) }), invisibleButtonConstructorDoc)
        .OMNIUI_PYBIND_DEF_CALLBACK(clicked, InvisibleButton, Clicked)
        /* */;
}
