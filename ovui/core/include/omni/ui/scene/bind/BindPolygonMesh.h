/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindAbstractShape.h"
#include "DocPolygonMesh.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_PolygonMesh                                                                                 \
    OMNIUI_PYBIND_INIT_AbstractShape                                                                                   \
    OMNIUI_PYBIND_INIT_CALL(positions, setPositions, pythonListToVector3)                                              \
    OMNIUI_PYBIND_INIT_CALL(colors, setColors, pythonListToVector4)                                                    \
    OMNIUI_PYBIND_INIT_CAST(vertex_counts, setVertexCounts, std::vector<uint32_t>)                                     \
    OMNIUI_PYBIND_INIT_CAST(vertex_indices, setVertexIndices, std::vector<uint32_t>)                                   \
    OMNIUI_PYBIND_INIT_CAST(thicknesses, setThicknesses, std::vector<float>)                                           \
    OMNIUI_PYBIND_INIT_CAST(intersection_thickness, setIntersectionThickness, float)                                   \
    OMNIUI_PYBIND_INIT_CALL(normals, setNormals, pythonListToVector3) \
    OMNIUI_PYBIND_INIT_CAST(lighting, setLighting, PolygonMesh::Lighting) \
    OMNIUI_PYBIND_INIT_CAST(wireframe, setWireframe, bool)

#define OMNIUI_PYBIND_KWARGS_DOC_PolygonMesh                                                                           \
    "\n    `positions : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_PolygonMesh_positions                                                                            \
    "\n    `colors : `\n        "                                                                                      \
    OMNIUI_PYBIND_DOC_PolygonMesh_colors                                                                               \
    "\n    `vertex_counts : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_PolygonMesh_vertexCounts                                                                         \
    "\n    `vertex_indices : `\n        "                                                                              \
    OMNIUI_PYBIND_DOC_PolygonMesh_vertexIndices                                                                        \
    "\n    `thicknesses : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_PolygonMesh_thicknesses                                                                          \
    "\n    `intersection_thickness : `\n        "                                                                      \
    OMNIUI_PYBIND_DOC_PolygonMesh_intersectionThickness                                                                \
    "\n    `wireframe: `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_PolygonMesh_wireframe                                                                            \
    "\n    `normals : `\n        Optional object-space normals indexed like positions; mismatched counts render unlit." \
    "\n    `lighting : `\n        MeshLighting.UNLIT by default; HEADLIGHT requires a capable renderer." \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractShape

// clang-format on
