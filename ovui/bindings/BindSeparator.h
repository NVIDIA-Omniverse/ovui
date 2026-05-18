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

#include <omni/ui/MenuDelegate.h>
#include <omni/ui/Separator.h>
#include <omni/ui/bind/BindSeparator.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapSeparator(module& m)
{
    constexpr const char* separatorDoc = OMNIUI_PYBIND_CLASS_DOC(Separator);
    static constexpr char separatorConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Separator, Separator);
    class_<Separator, Widget, MenuHelper, std::shared_ptr<Separator>>(m, "Separator", separatorDoc)
        .def(init([](std::string text, kwargs kwargs) { OMNIUI_PYBIND_INIT(Separator, text) }), arg("text") = "",
             separatorConstructorDoc)
        /* */;
}
