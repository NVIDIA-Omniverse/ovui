/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once
#include "Transform.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

enum class StrokeWidthSpace
{
    ePixels, ///< Preserve the backend's existing screen-space width behavior.
    eWorld, ///< Curve half-widths and point radii are world units, scaled by the largest model axis.
    ePixelDiameter, ///< Full physical-pixel stroke diameter, independent of UI scaling, with Hermite edge coverage.
};

/** Scoped width interpretation for Curve/Line/Points. Meshes and images are unaffected.
 * Nested groups override their parent. World-space strokes require
 * SceneView.supportsWorldSpaceWidths(); ordinary scenes retain their existing behavior.
 * World-space curve antialiasing widths use world units (without model scaling).
 * PixelDiameter requires SceneView.supportsPixelDiameterWidths(). Its AA width adds
 * half outside each edge; the core is max(0, diameter - AA), with full peak opacity.
 * Points are circular (normalized radial distance scaled by 1.08) with the same edge law.
 */
class OMNIUI_SCENE_CLASS_API WidthSpaceGroup : public Transform
{
    OMNIUI_SCENE_OBJECT(WidthSpaceGroup);
public:
    OMNIUI_SCENE_API
    StrokeWidthSpace getWidthSpace() const;
    OMNIUI_SCENE_API
    void setWidthSpace(StrokeWidthSpace space);
    /** Point edge transition half-width in world units for World, or total added
     * diameter in physical pixels for PixelDiameter. Unaffected by model scale. */
    OMNIUI_SCENE_API
    Float getPointAntialiasingWidth() const;
    OMNIUI_SCENE_API
    void setPointAntialiasingWidth(Float width);
protected:
    OMNIUI_SCENE_API
    explicit WidthSpaceGroup(StrokeWidthSpace space = StrokeWidthSpace::ePixels, Float pointAntialiasingWidth = 0.0);
    OMNIUI_SCENE_API
    void _preDrawContent(const MouseInput&, const Matrix44&, const Matrix44&, float, float) override;
    OMNIUI_SCENE_API
    void _drawContent(const Matrix44&, const Matrix44&) override;
private:
    StrokeWidthSpace m_space = StrokeWidthSpace::ePixels;
    Float m_pointAntialiasingWidth = 0.0;
};

class DrawBuffer;
struct WidthSpaceDrawBuffer
{
    const DrawBuffer* buffer;
    StrokeWidthSpace space;
    Float pointAntialiasingWidth;
    bool operator==(const WidthSpaceDrawBuffer& other) const
    {
        return buffer == other.buffer && space == other.space && pointAntialiasingWidth == other.pointAntialiasingWidth;
    }
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
