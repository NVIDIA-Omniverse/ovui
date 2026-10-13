/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/VGrid.h>
#include <omni/ui/bind/BindVGrid.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapVGrid(module& m)
{
    constexpr const char* vGridDoc = OMNIUI_PYBIND_CLASS_DOC(VGrid);
    static constexpr char vGridConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(VGrid, VGrid);

    class_<VGrid, Grid, std::shared_ptr<VGrid>>(m, "VGrid", vGridDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(VGrid) }), vGridConstructorDoc);
}
