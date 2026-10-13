/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/scene/Rectangle.h>

#include "AbstractShapeData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct Rectangle::RectangleData : public AbstractShape::AbstractShapeData
{
    ~RectangleData() override;

    RectangleGesturePayload m_lastGesturePayload;
    std::array<std::unique_ptr<RectangleGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;

    // Cache to avoid computation every frame
    std::vector<Vector3> m_cachedPoints;
    std::vector<Color4> m_cachedColors;
    std::vector<uint32_t> m_cachedVertexIndices;
    std::vector<uint32_t> m_cachedVertexCounts;
    std::vector<float> m_cachedThicknesses;
    bool m_cacheIsDirty = true;

    bool m_intersectionThicknessExplicitlyChanged = false;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
