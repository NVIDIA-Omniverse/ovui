/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Spacer.h>
#include <omni/ui/bind/BindSpacer.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapSpacer(module& m)
{
    constexpr const char* spacerDoc = OMNIUI_PYBIND_CLASS_DOC(Spacer);
    static constexpr char spacerConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Spacer, Spacer);
    class_<Spacer, Widget, std::shared_ptr<Spacer>>(m, "Spacer", spacerDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Spacer) }), spacerConstructorDoc)
        /* */;
}
