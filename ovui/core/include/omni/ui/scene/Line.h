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

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class OMNIUI_SCENE_CLASS_API Line : public AbstractShape
{
    OMNIUI_SCENE_OBJECT(Line);

public:
    class LineGesturePayload : public AbstractGesture::GesturePayload
    {
    public:
        Float lineDistance = 0.0;
        Vector3 lineClosestPoint = Vector3{ 0.0 };
        Float movedDistance = 0.0;
        Vector3 moved = Vector3{ 0.0 };
    };

    OMNIUI_SCENE_API
    virtual ~Line();

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
    const LineGesturePayload* getGesturePayload() const override;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    const LineGesturePayload* getGesturePayload(GestureState state) const override;

    /**
     * @brief The distance in pixels from mouse pointer to the shape for the intersection.
     */
    OMNIUI_SCENE_API
    Float getIntersectionDistance() const override;

    /**
     * @brief The start point of the line
     */
    OMNIUI_PROPERTY(Vector3, start, DEFAULT, Vector3{ 0.0 }, READ, getStart, WRITE, setStart, NOTIFY, _setStartChangedFn);

    /**
     * @brief The end point of the line
     */
    OMNIUI_PROPERTY(Vector3, end, DEFAULT, Vector3{ 0.0 }, READ, getEnd, WRITE, setEnd, NOTIFY, _setEndChangedFn);

    /**
     * @brief The line color
     */
    OMNIUI_PROPERTY(Color4, color, DEFAULT, Color4{ 1.0 }, READ, getColor, WRITE, setColor, NOTIFY, _setColorChangedFn);

    /**
     * @brief The line thickness
     */
    OMNIUI_PROPERTY(float, thickness, DEFAULT, 1.0, READ, getThickness, WRITE, setThickness, NOTIFY, _setThicknessChangedFn);

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

protected:
    struct LineData;

    OMNIUI_SCENE_API
    Line();

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    void _dirty();
    void _setChangedFn();

    /**
     * @brief A simple line
     *
     * @param start The start point of the line
     * @param end The end point of the line
     */
    OMNIUI_SCENE_API
    Line(const Vector3& start, const Vector3& end);
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
