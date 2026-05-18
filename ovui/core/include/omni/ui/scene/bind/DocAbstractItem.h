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

#define OMNIUI_PYBIND_DOC_AbstractItem                                                                                 \
    "\n"                                                                                                               \
    "\n"


#define OMNIUI_PYBIND_DOC_AbstractItem_destroy "Removes all the callbacks and circular references.\n"


#define OMNIUI_PYBIND_DOC_AbstractItem_transformSpace                                                                  \
    "Transform the given point from the coordinate system fromspace to the coordinate system tospace.\n"


#define OMNIUI_PYBIND_DOC_AbstractItem_transformSpace01                                                                \
    "Transform the given vector from the coordinate system fromspace to the coordinate system tospace.\n"


#define OMNIUI_PYBIND_DOC_AbstractItem_computeVisibility                                                               \
    "Calculate the effective visibility of this prim, as defined by its most ancestral invisible opinion, if any.\n"


#define OMNIUI_PYBIND_DOC_AbstractItem_sceneView "The current SceneView this item is parented to.\n"


#define OMNIUI_PYBIND_DOC_AbstractItem_visible "This property holds whether the item is visible.\n"
