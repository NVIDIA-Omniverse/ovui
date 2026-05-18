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

#include <omni/ui/HGrid.h>
#include <omni/ui/bind/BindHGrid.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapHGrid(module& m)
{
    constexpr const char* hGridDoc = OMNIUI_PYBIND_CLASS_DOC(HGrid);
    static constexpr char hGridConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(HGrid, HGrid);

    class_<HGrid, Grid, std::shared_ptr<HGrid>>(m, "HGrid", hGridDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(HGrid) }), hGridConstructorDoc);
}
