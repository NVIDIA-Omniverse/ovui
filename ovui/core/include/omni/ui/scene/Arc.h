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
#include "Culling.h"
#include "Math.h"
#include "Object.h"

#include <array>
#include <cstdint>
#include <memory>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class OMNIUI_SCENE_CLASS_API Arc : public AbstractShape
{
    OMNIUI_SCENE_OBJECT(Arc);

public:
    class ArcGesturePayload : public AbstractGesture::GesturePayload
    {
    public:
        Float distanceToCenter = 0.0;
        Float angle = 0.0;
        Float movedDistanceToCenter = 0.0;
        Float movedAngle = 0.0;
        Vector3 moved = Vector3{ 0.0 };
        bool culled = false;
    };

    OMNIUI_SCENE_API
    virtual ~Arc();

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
    const ArcGesturePayload* getGesturePayload() const override;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    const ArcGesturePayload* getGesturePayload(GestureState state) const override;

    /**
     * @brief The distance in pixels from mouse pointer to the shape for the intersection.
     */
    OMNIUI_SCENE_API
    Float getIntersectionDistance() const override;

    /**
     * @brief The radius of the circle
     */
    OMNIUI_PROPERTY(Float, radius, READ, getRadius, WRITE, setRadius, NOTIFY, _setRadiusChangedFn);

    /**
     * @brief The start angle of the arc.
     *
     * Angle placement and directions are (0 to 90): Y to Z, Z to X, X to Y
     */
    OMNIUI_PROPERTY(Float, begin, DEFAULT, -Float(M_PI), READ, getBegin, WRITE, setBegin, NOTIFY, _setBeginChangedFn);

    /**
     * @brief The end angle of the arc.
     *
     * Angle placement and directions are (0 to 90): Y to Z, Z to X, X to Y
     */
    OMNIUI_PROPERTY(Float, end, DEFAULT, Float(M_PI), READ, getEnd, WRITE, setEnd, NOTIFY, _setEndChangedFn);

    /**
     * @brief The thickness of the line
     */
    OMNIUI_PROPERTY(
        float, thickness, DEFAULT, 1.0, READ, getThickness, WRITE, setThickness, PROTECTED, NOTIFY, _setThicknessChangedFn);

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
     * @brief The color of the line
     */
    OMNIUI_PROPERTY(
        Color4, color, DEFAULT, Color4{ 1.0 }, READ, getColor, WRITE, setColor, PROTECTED, NOTIFY, _setColorChangedFn);

    /**
     * @brief Number of points on the curve
     */
    OMNIUI_PROPERTY(uint16_t,
                    tesselation,
                    DEFAULT,
                    36,
                    READ,
                    getTesselation,
                    WRITE,
                    setTesselation,
                    PROTECTED,
                    NOTIFY,
                    _setTesselationChangedFn);

    /**
     * @brief When true, it's a line. When false it's a mesh.
     */
    OMNIUI_PROPERTY(
        bool, wireframe, DEFAULT, false, READ, isWireframe, WRITE, setWireframe, PROTECTED, NOTIFY, _setWireframeChangedFn);

    /**
     * @brief Draw two radii of the circle
     */
    OMNIUI_PROPERTY(bool, sector, DEFAULT, true, READ, isSector, WRITE, setSector, PROTECTED, NOTIFY, _setSectorChangedFn);

    /**
     * @brief The axis the circle plane is perpendicular to
     */
    OMNIUI_PROPERTY(uint8_t, axis, DEFAULT, 2, READ, getAxis, WRITE, setAxis, NOTIFY, _setAxisChangedFn);

    /**
     * @brief Draw two radii of the circle
     */
    OMNIUI_PROPERTY(
        Culling, culling, DEFAULT, Culling::eNone, READ, getCulling, WRITE, setCulling, PROTECTED, NOTIFY, _setCullingChangedFn);

protected:
    struct ArcData;

    /**
     * @brief Constructs Arc
     */
    OMNIUI_SCENE_API
    Arc(Float radius);

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    void _dirtyCache();
    void _rebuildCache();
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
