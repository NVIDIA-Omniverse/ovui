/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
