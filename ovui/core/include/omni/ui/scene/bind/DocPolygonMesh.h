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

#define OMNIUI_PYBIND_DOC_PolygonMesh                                                                                  \
    "Encodes a mesh.\n"                                                                                                \
    "\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_getGesturePayload "Contains all the information about the intersection.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_getGesturePayload01                                                              \
    "Contains all the information about the intersection at the specific state.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_getIntersectionDistance                                                          \
    "The distance in pixels from mouse pointer to the shape for the intersection.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_positions "The primary geometry attribute, describes points in local space.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_colors "Describes colors per vertex.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_vertexCounts                                                                     \
    "Provides the number of vertices in each face of the mesh, which is also the number of consecutive indices in vertex_indices that define the face. The length of this attribute is the number of faces in the mesh.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_vertexIndices                                                                    \
    "Flat list of the index (into the points attribute) of each vertex of each face in the mesh.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_thicknesses "When wireframe is true, it defines the thicknesses of lines.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_intersectionThickness "The thickness of the line for the intersection.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_wireframe "When true, the mesh is drawn as lines.\n"


#define OMNIUI_PYBIND_DOC_PolygonMesh_PolygonMesh                                                                      \
    "Construct a mesh with predefined properties.\n"                                                                   \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
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
