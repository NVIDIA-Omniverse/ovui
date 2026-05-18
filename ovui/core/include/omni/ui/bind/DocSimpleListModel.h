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

#define OMNIUI_PYBIND_DOC_SimpleListModel                                                                              \
    "A very simple model that holds the the root model and the flat list of models.\n"                                 \
    "\n"


#define OMNIUI_PYBIND_DOC_SimpleListModel_getItemChildren                                                              \
    "Reimplemented. Returns the vector of items that are nested to the given parent item.\n"


#define OMNIUI_PYBIND_DOC_SimpleListModel_appendChildItem                                                              \
    "Reimplemented. Creates a new item from the value model and appends it to the list of the children of the given item.\n"


#define OMNIUI_PYBIND_DOC_SimpleListModel_removeItem "Reimplemented. Removes the item from the model.\n"


#define OMNIUI_PYBIND_DOC_SimpleListModel_getItemValueModel                                                            \
    "Reimplemented. Get the value model associated with this item.\n"


#define OMNIUI_PYBIND_DOC_SimpleListModel_SimpleListModel                                                              \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `rootModel :`\n"                                                                                              \
    "        The model that will be returned when querying the root item.\n"                                           \
    "\n"                                                                                                               \
    "    `models :`\n"                                                                                                 \
    "        The list of all the value submodels of this model.\n"
