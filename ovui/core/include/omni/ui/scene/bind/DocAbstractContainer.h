/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_AbstractContainer                                                                            \
    "Base class for all the items that have children.\n"                                                               \
    "\n"


#define OMNIUI_PYBIND_DOC_AbstractContainer_transformSpace                                                             \
    "Transform the given point from the coordinate system fromspace to the coordinate system tospace.\n"


#define OMNIUI_PYBIND_DOC_AbstractContainer_transformSpace01                                                           \
    "Transform the given vector from the coordinate system fromspace to the coordinate system tospace.\n"


#define OMNIUI_PYBIND_DOC_AbstractContainer_addChild                                                                   \
    "Adds item to this container in a manner specific to the container. If it's allowed to have one sub-widget only, it will be overwriten.\n"


#define OMNIUI_PYBIND_DOC_AbstractContainer_clear "Removes the container items from the container.\n"
