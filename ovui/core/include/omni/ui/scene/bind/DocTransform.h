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

#define OMNIUI_PYBIND_DOC_Transform                                                                                    \
    "Transforms children with component affine transformations.\n"                                                     \
    "\n"


#define OMNIUI_PYBIND_DOC_Transform_transform "Single transformation matrix.\n"


#define OMNIUI_PYBIND_DOC_Transform_scaleTo                                                                            \
    "Which space the current transform will be rescaled before applying the matrix. It's useful to make the object the same size regardless the distance to the camera.\n"


#define OMNIUI_PYBIND_DOC_Transform_lookAt "Rotates this transform to align the direction with the camera.\n"


#define OMNIUI_PYBIND_DOC_Transform_basis "A custom basis for representing this transform's coordinate system.\n"


#define OMNIUI_PYBIND_DOC_Transform_Transform "Constructor.\n"
