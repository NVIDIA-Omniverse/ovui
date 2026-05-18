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

#include "AbstractDrawSystem.h"

#include <omni/ui/FontHelper.h>

#include <memory>
#include <vector>


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class DrawBuffer;

/**
 * @brief The InvisibleButton widget provides a transparent command button.
 */
class OMNIUI_SCENE_CLASS_API ImguiDrawSystem : public AbstractDrawSystem, public FontHelper
{
public:
    ImguiDrawSystem();
    ~ImguiDrawSystem() override;

    void setup() override;
    void beginFrame() override;
    void render(const DrawBuffer* const * buffers,
                size_t bufferCount,
                const Matrix44& projection,
                const Matrix44& view,
                float width,
                float height,
                float dpiScale) override;
    void endFrame() override;
    void destroy() override;

private:
    void _drawLines(const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height, float dpiScale) const;
    void _cachePolys(const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height) const;
    void _cachePoints(const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height) const;

    void _drawPolys(const Matrix44& projectionView, float width, float height, float dpiScale);
    void _drawPoints(const Matrix44& projectionView, float width, float height, float dpiScale);

    void _drawTexts(const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height, float dpiScale);

    std::unique_ptr<DrawBuffer> m_flatPolyCache;
    std::vector<Float> m_polyDepth;
    std::vector<size_t> m_polySorted;
    std::vector<size_t> m_indexStart;

    std::unique_ptr<DrawBuffer> m_flatPointCache;
    std::vector<size_t> m_pointSorted;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
