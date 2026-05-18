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

#define OMNIUI_PYBIND_DOC_TexturedMesh                                                                                 \
    "Encodes a polygonal mesh with free-form textures.\n"                                                              \
    "\n"

#define OMNIUI_PYBIND_DOC_TexturedMesh_getGesturePayload "Contains all the information about the intersection.\n"


#define OMNIUI_PYBIND_DOC_TexturedMesh_getGesturePayload01                                                             \
    "Contains all the information about the intersection at the specific state.\n"

#define OMNIUI_PYBIND_DOC_TexturedMesh_uvs                                                                             \
    "This property holds the texture coordinates of the mesh.\n"                                                                


#define OMNIUI_PYBIND_DOC_TexturedMesh_sourceUrl                                                                       \
    "This property holds the image URL. It can be an \"omni:\" path, a \"file:\" path, a direct path or the path "     \
    "relative to the application root directory.\n"


#define OMNIUI_PYBIND_DOC_TexturedMesh_imageProvider                                                                   \
    "This property holds the image provider. It can be an \"omni:\" path, a \"file:\" path, a direct path or the "     \
    "path relative to the application root directory.\n"


#define OMNIUI_PYBIND_DOC_TexturedMesh_imageWidth                                                                      \
    "This property holds the image width\n"


#define OMNIUI_PYBIND_DOC_TexturedMesh_imageHeight                                                                     \
    "This property holds the image height\n"


#define OMNIUI_PYBIND_DOC_TexturedMesh_TexturedMesh                                                                    \
    "Construct a mesh with predefined properties.\n"                                                                   \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `sourceUrl :`\n"                                                                                              \
    "        Describes the texture image url.\n"                                                                       \
    "\n"                                                                                                               \
    "    `uvs :`\n"                                                                                                    \
    "        Describes uvs for the image texture.\n"                                                                   \
    "\n"                                                                                                               \
    "    `positions :`\n"                                                                                              \
    "        Describes points in local space.\n"                                                                       \
    "\n"                                                                                                               \
    "    `colors :`\n"                                                                                                 \
    "        Describes colors per vertex.\n"                                                                           \
    "\n"                                                                                                               \
    "    `vertexCounts :`\n"                                                                                           \
    "        The number of vertices in each face.\n"                                                                   \
    "\n"                                                                                                               \
    "    `vertexIndices :`\n"                                                                                          \
    "        The list of the index of each vertex of each face in the mesh.\n"


#define OMNIUI_PYBIND_DOC_TexturedMesh_TexturedMesh01                                                                  \
    "Construct a mesh with predefined properties.\n"                                                                   \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `imageProvider :`\n"                                                                                          \
    "        Describes the texture image provider.\n"                                                                  \
    "\n"                                                                                                               \
    "    `uvs :`\n"                                                                                                    \
    "        Describes uvs for the image texture.\n"                                                                   \
    "\n"                                                                                                               \
    "    `positions :`\n"                                                                                              \
    "        Describes points in local space.\n"                                                                       \
    "\n"                                                                                                               \
    "    `colors :`\n"                                                                                                 \
    "        Describes colors per vertex.\n"                                                                           \
    "\n"                                                                                                               \
    "    `vertexCounts :`\n"                                                                                           \
    "        The number of vertices in each face.\n"                                                                   \
    "\n"                                                                                                               \
    "    `vertexIndices :`\n"                                                                                          \
    "        The list of the index of each vertex of each face in the mesh.\n"
