/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
 * @brief Represents the curve.
 */
class OMNIUI_SCENE_CLASS_API Curve : public AbstractShape
{
    OMNIUI_SCENE_OBJECT(Curve);

public:
    class CurveGesturePayload : public AbstractGesture::GesturePayload
    {
    public:
        // The normalized distance [0..1] along the curve from begin of the
        // segment to itemClosestPoint
        Float curveDistance = 0.0;
        // The difference between rayClosestPoint in the previous frame and
        // rayClosestPoint in current frame.
        Vector3 moved = Vector3{ 0.0 };
        // The difference between curveDistance in the previous frame and
        // curveDistance in current frame.
        Float movedDistance = 0.0;
    };

    OMNIUI_SCENE_API
    virtual ~Curve();

    enum class CurveType
    {
        linear,
        cubic,
    };

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
    const CurveGesturePayload* getGesturePayload() const override;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    const CurveGesturePayload* getGesturePayload(GestureState state) const override;

    /**
     * @brief The distance in pixels from mouse pointer to the shape for the intersection.
     */
    OMNIUI_SCENE_API
    Float getIntersectionDistance() const override;

    /**
     * @brief The list of positions which defines the curve. It has at least two positions. The curve has
     * `len(positions)-1` segments.
     */
    OMNIUI_PROPERTY(std::vector<Vector3>, positions, READ, getPositions, WRITE, setPositions, NOTIFY, _setPositionsChangedFn);

    /**
     * Optional counts partitioning positions into independent linear polylines.
     * Empty preserves the original single-curve behavior. Otherwise every count
     * must be at least two, their sum must equal positions.size(), and curveType
     * must be linear. Invalid partitions draw nothing. Colors and thicknesses
     * retain their existing interpolation across the flattened positions array.
     * Gesture distances exclude gaps between polylines.
     * Stored privately to preserve the published Curve object layout and vtable.
     */
    OMNIUI_SCENE_API
    const std::vector<uint32_t>& getVertexCounts() const;
    OMNIUI_SCENE_API
    void setVertexCounts(const std::vector<uint32_t>& counts);

    /** Optional raster coverage transition width in pixels. Zero preserves
     * renderer defaults. Standard OpenGL supports positive finite widths;
     * other draw systems may retain their existing antialiasing behavior.
     * Stored privately to preserve the Curve layout and vtable. */
    OMNIUI_SCENE_API
    float getAntialiasingWidth() const;
    OMNIUI_SCENE_API
    void setAntialiasingWidth(float width);

    /**
     * @brief The list of colors which defines color per vertex. It has the same length as positions
     */
    OMNIUI_PROPERTY(std::vector<Color4>, colors, READ, getColors, WRITE, setColors, NOTIFY, _setColorsChangedFn);

    /**
     * @brief The list of thicknesses which defines thickness per vertex. It has the same length as positions
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
     * @brief The curve interpolation type
     */
    OMNIUI_PROPERTY(CurveType,
                    curveType,
                    DEFAULT,
                    CurveType::cubic,
                    READ,
                    getCurveType,
                    WRITE,
                    setCurveType,
                    NOTIFY,
                    _setCurveTypeChangedFn);

    /**
     * @brief The number of points per curve segment. It can't be less than 2
     */
    OMNIUI_PROPERTY(
        uint16_t, tessellation, DEFAULT, 9, READ, getTessellation, WRITE, setTessellation, NOTIFY, _setTessellationChangedFn);

protected:
    struct CurveData;

    /**
     * @brief Constructs Curve
     * @param positions List of positions
     */
    OMNIUI_SCENE_API
    Curve(const std::vector<Vector3>& positions = {});

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    bool _getFollowReport(Vector3& moved) const override;
    void _captureBaseline() const override;

    void _dirtyCache();
    void _rebuildCache();

    /**
     * @brief Compute curve positions with input 4 vertices and tessellation
     * @param p0 start position
     * @param p1 second control position
     * @param p2 thrid constrol position
     * @param p3 end position
     * @param tessellation tessellation of the curve
     */
    void _computeCurvePoses(const Vector3 p0,
                            const Vector3 p1,
                            const Vector3 p2,
                            const Vector3 p3,
                            const uint16_t tessellation,
                            std::vector<Vector3>& poses);

    /**
     * @brief Interpolate float with start and end floats into segment sized floats
     * @param start start float
     * @param end end float
     * @param segment size of segment
     * @param result the resulted vector of the interpolated floats. It includes the start, but not the end float
     */
    void _interpolateFloat(float start, float end, size_t segment, std::vector<float>& result);

    /**
     * @brief Interpolate color with start and end colors into segment sized colors
     * @param start start color
     * @param end end color
     * @param segment size of segment
     * @param result the resulted vector of the interpolated colors. It includes the start, but not the end color
     */
    void _interpolateColor(Color4 start, Color4 end, size_t segment, std::vector<Color4>& result);
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
