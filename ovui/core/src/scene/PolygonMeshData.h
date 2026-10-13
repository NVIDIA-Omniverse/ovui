/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/scene/PolygonMesh.h>
#include "AbstractShapeData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct PolygonMesh::PolygonMeshData : public AbstractShapeData
{
    PolygonMeshData();
    ~PolygonMeshData() override;

    std::unique_ptr<PolygonMeshGesturePayload> m_lastGesturePayload;
    std::array<std::unique_ptr<PolygonMeshGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;

    // Cache to avoid computation every frame
    std::vector<Color4> m_cachedColors;
    std::vector<uint32_t> m_cachedVertexIndices;
    std::vector<uint32_t> m_cachedVertexCounts;
    std::vector<float> m_cachedThicknesses;
    std::vector<Vector2> m_cachedUvs;
    std::vector<void*> m_cachedTextures;
    bool m_cacheIsDirty = true;
    std::vector<Vector3> m_normals;
    Lighting m_lighting = Lighting::eUnlit;

    bool m_intersectionThicknessExplicitlyChanged = false;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
