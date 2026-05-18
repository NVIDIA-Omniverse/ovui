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

#include <omni/ui/Grid.h>
#include <omni/ui/bind/BindGrid.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapGrid(module& m)
{
    constexpr const char* gridDoc = OMNIUI_PYBIND_CLASS_DOC(Grid);
    static constexpr char gridConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Grid, Grid);

    class_<Grid, Stack, std::shared_ptr<Grid>>(m, "Grid", gridDoc)
        .def(init([](Stack::Direction direction, kwargs kwargs) { OMNIUI_PYBIND_INIT(Grid, direction) }),
             gridConstructorDoc)
        .def_property("column_width", &Grid::getColumnWidth, &Grid::setColumnWidth, OMNIUI_PYBIND_DOC_Grid_columnWidth)
        .def_property("row_height", &Grid::getRowHeight, &Grid::setRowHeight, OMNIUI_PYBIND_DOC_Grid_rowHeight)
        .def_property("column_count", &Grid::getColumnCount, &Grid::setColumnCount, OMNIUI_PYBIND_DOC_Grid_columnCount)
        .def_property("row_count", &Grid::getRowCount, &Grid::setRowCount, OMNIUI_PYBIND_DOC_Grid_rowCount);
}
