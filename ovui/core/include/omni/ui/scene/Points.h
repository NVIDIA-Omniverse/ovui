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
 * @brief Represents the point cloud.
 */
class OMNIUI_SCENE_CLASS_API Points : public AbstractShape
{
    OMNIUI_SCENE_OBJECT(Points);

public:
    class PointsGesturePayload : public AbstractGesture::GesturePayload
    {
    public:
        Float distanceToPoint = Float(0.0);
        Vector3 moved = Vector3{ 0.0 };
        uint32_t closestPoint = UINT32_MAX;
    };

    OMNIUI_SCENE_API
    virtual ~Points();

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
    const PointsGesturePayload* getGesturePayload() const override;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    const PointsGesturePayload* getGesturePayload(GestureState state) const override;

    /**
     * @brief The distance in pixels from mouse pointer to the shape for the intersection.
     */
    OMNIUI_SCENE_API
    Float getIntersectionDistance() const override;

    /**
     * @brief List with positions of the points
     */
    OMNIUI_PROPERTY(std::vector<Vector3>, positions, READ, getPositions, WRITE, setPositions, NOTIFY, _setPositionsChangedFn);

    /**
     * @brief List of colors of the points
     */
    OMNIUI_PROPERTY(std::vector<Color4>, colors, READ, getColors, WRITE, setColors, NOTIFY, _setColorsChangedFn);

    /**
     * @brief List of point sizes
     */
    OMNIUI_PROPERTY(std::vector<float>, sizes, READ, getSizes, WRITE, setSizes, NOTIFY, _setSizesChangedFn);

    /**
     * @brief The size of the points for the intersection
     */
    OMNIUI_PROPERTY(float,
                    intersectionSize,
                    DEFAULT,
                    0.0,
                    READ,
                    getIntersectionSize,
                    WRITE,
                    setIntersectionSize,
                    PROTECTED,
                    NOTIFY,
                    _setIntersectionSizeChangedFn);

protected:
    /**
     * @brief Constructs the point cloud object
     *
     * @param positions List of positions
     */
    OMNIUI_SCENE_API
    Points(const std::vector<Vector3>& positions = {});

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    void _dirtyCache();

    struct PointsData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
