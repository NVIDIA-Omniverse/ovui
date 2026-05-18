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
