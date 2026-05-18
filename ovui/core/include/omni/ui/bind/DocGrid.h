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

#define OMNIUI_PYBIND_DOC_Grid                                                                                                                                                \
    "Grid is a container that arranges its child views in a grid. The grid vertical/horizontal direction is the direction the grid size growing with creating more children.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_Grid_CellSizeMode                                                                            \
    "The grid has two modes of working. When the current mode is eSizeFromCount, the grid computes the size of the cell using the number of columns/rows. When eCountFromSize, the size of the cells is always the same, but the number of columns varies depending on the grid's full size.\n"


#define OMNIUI_PYBIND_DOC_Grid_setComputedContentWidth                                                                 \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_Grid_setComputedContentHeight                                                                \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_Grid_columnWidth                                                                             \
    "The width of the column. It's only possible to set it if the grid is vertical. Once it's set, the column count depends on the size of the widget.\n"


#define OMNIUI_PYBIND_DOC_Grid_rowHeight                                                                               \
    "The height of the row. It's only possible to set it if the grid is horizontal. Once it's set, the row count depends on the size of the widget.\n"


#define OMNIUI_PYBIND_DOC_Grid_columnCount                                                                             \
    "The number of columns. It's only possible to set it if the grid is vertical. Once it's set, the column width depends on the widget size.\n"


#define OMNIUI_PYBIND_DOC_Grid_rowCount                                                                                \
    "The number of rows. It's only possible to set it if the grid is horizontal. Once it's set, the row height depends on the widget size.\n"


#define OMNIUI_PYBIND_DOC_Grid_Grid                                                                                    \
    "Constructor.\n"                                                                                                   \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `direction :`\n"                                                                                              \
    "        Determines the direction the widget grows when adding more children.\n"
