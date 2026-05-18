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

#include "AbstractShape.h"
#include "Math.h"
#include "Object.h"

#include <array>
#include <memory>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief Encodes a mesh.
 */
class OMNIUI_SCENE_CLASS_API PolygonMesh : public AbstractShape
{
    OMNIUI_SCENE_OBJECT(PolygonMesh);

public:
    class PolygonMeshGesturePayload : public AbstractGesture::GesturePayload
    {
    public:
        // The id of the face intersected.
        int32_t faceId = -1;
        // The coords of the intersection in the space of the face.
        Float s = 0.0;
        Float t = 0.0;
    };

    OMNIUI_SCENE_API
    virtual ~PolygonMesh();

    OMNIUI_SCENE_API
    void intersect(const Vector3 origin,
                   const Vector3 direction,
                   const Vector2 mouse,
                   const Matrix44& projection,
                   const Matrix44& view,
                   GestureState state) override;

    /**
     * @brief Contains all the information about the intersection
     */
    OMNIUI_SCENE_API
    const PolygonMeshGesturePayload* getGesturePayload() const override;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    const PolygonMeshGesturePayload* getGesturePayload(GestureState state) const override;

    /**
     * @brief The distance in pixels from mouse pointer to the shape for the intersection.
     */
    OMNIUI_SCENE_API
    Float getIntersectionDistance() const override;

    /**
     * @brief The primary geometry attribute, describes points in local space.
     */
    OMNIUI_PROPERTY(std::vector<Vector3>, positions, READ, getPositions, WRITE, setPositions, NOTIFY, _setPositionsChangedFn);

    /**
     * @brief Describes colors per vertex.
     */
    OMNIUI_PROPERTY(std::vector<Color4>, colors, READ, getColors, WRITE, setColors, NOTIFY, _setColorsChangedFn);

    /**
     * @brief Provides the number of vertices in each face of the mesh, which is
     * also the number of consecutive indices in vertex_indices that define the
     * face. The length of this attribute is the number of faces in the mesh.
     */
    OMNIUI_PROPERTY(std::vector<uint32_t>,
                    vertexCounts,
                    READ,
                    getVertexCounts,
                    WRITE,
                    setVertexCounts,
                    NOTIFY,
                    _setVertexCountsChangedFn);

    /**
     * @brief Flat list of the index (into the points attribute) of each vertex
     * of each face in the mesh.
     */
    OMNIUI_PROPERTY(std::vector<uint32_t>,
                    vertexIndices,
                    READ,
                    getVertexIndices,
                    WRITE,
                    setVertexIndices,
                    NOTIFY,
                    _setVertexIndicesChangedFn);

    /**
     * @brief When wireframe is true, it defines the thicknesses of lines.
     */
    OMNIUI_PROPERTY(
        std::vector<float>, thicknesses, READ, getThicknesses, WRITE, setThicknesses, NOTIFY, _setThicknessesChangedFn);

    /**
     * @brief The thickness of the line for the intersection
     */
    OMNIUI_PROPERTY(float,
                    intersectionThickness,
                    DEFAULT,
                    0.0,
                    READ,
                    getIntersectionThickness,
                    WRITE,
                    setIntersectionThickness,
                    PROTECTED,
                    NOTIFY,
                    _setIntersectionThicknessChangedFn);

    /**
     * @brief When true, the mesh is drawn as lines.
     */
    OMNIUI_PROPERTY(bool, wireframe, DEFAULT, false, READ, isWireframe, WRITE, setWireframe, NOTIFY, _setWireframeChangedFn);

protected:
    struct PolygonMeshData;

    /**
     * @brief Construct a mesh with predefined properties.
     *
     * @param positions Describes points in local space.
     * @param colors Describes colors per vertex.
     * @param vertexCounts The number of vertices in each face.
     * @param vertexIndices The list of the index of each vertex of each face in
     *                      the mesh.
     */
    OMNIUI_SCENE_API
    PolygonMesh(const std::vector<Vector3>& positions,
                const std::vector<Color4>& colors,
                const std::vector<uint32_t>& vertexCounts,
                const std::vector<uint32_t>& vertexIndices,
                PolygonMeshData* data = nullptr);

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    void _dirtyCache();
    void _rebuildCache();
    void _calculateST(const Vector3 origin, const Vector3 direction, Float& g_s, Float& g_t, int32_t& g_faceId,
                      Vector3& g_itemClosestPoint, Vector3& g_rayClosestPoint, Float& g_rayDistance);
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
