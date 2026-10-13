/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_AbstractItemDelegate                                                                         \
    "AbstractItemDelegate is used to generate widgets that display and edit data items from a model.\n"                \
    "\n"


#define OMNIUI_PYBIND_DOC_AbstractItemDelegate_buildBranch                                                             \
    "This pure abstract method must be reimplemented to generate custom collapse/expand button.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemDelegate_buildWidget                                                             \
    "This pure abstract method must be reimplemented to generate custom widgets for specific item in the model.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemDelegate_buildHeader                                                             \
    "This pure abstract method must be reimplemented to generate custom widgets for the header table.\n"


#define OMNIUI_PYBIND_DOC_AbstractItemDelegate_AbstractItemDelegate "Constructs AbstractItemDelegate.\n"
