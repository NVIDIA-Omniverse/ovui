/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_Matrix44                                                                                     \
    "Stores a 4x4 matrix of float elements. A basic type.\n"                                                           \
    "Matrices are defined to be in row-major order.\n"                                                                 \
    "The matrix mode is required to define the matrix that resets the transformation to fit the geometry into NDC, Screen space, or rotate it to the camera direction.\n"


#define OMNIUI_PYBIND_DOC_Matrix44_setLookAtView                                                                       \
    "Rotates the matrix to be aligned with the camera.\n"                                                              \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `view :`\n"                                                                                                   \
    "        The view matrix of the camera\n"


#define OMNIUI_PYBIND_DOC_Matrix44_getTranslationMatrix                                                                \
    "Creates a matrix to specify a translation at the given coordinates.\n"


#define OMNIUI_PYBIND_DOC_Matrix44_getRotationMatrix                                                                   \
    "Creates a matrix to specify a rotation around each axis.\n"                                                       \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `degrees :`\n"                                                                                                \
    "        true if the angles are specified in degrees\n"


#define OMNIUI_PYBIND_DOC_Matrix44_getScaleMatrix                                                                      \
    "Creates a matrix to specify a scaling with the given scale factor per axis.\n"
