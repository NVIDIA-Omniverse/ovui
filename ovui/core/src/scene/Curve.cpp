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

#include <omni/ui/platform/Assert.h>
#include <omni/ui/platform/Log.h>
#include <omni/ui/Profile.h>

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/Curve.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Math.h>

#include "AbstractShapeData.h"

#include <numeric>
#include <limits>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

struct Curve::CurveData : public AbstractShape::AbstractShapeData
{
    ~CurveData() override = default;

    // Cache to avoid computation every frame
    std::vector<Vector3> m_cachedPositions;
    std::vector<Color4> m_cachedColors;
    std::vector<uint32_t> m_cachedVertexIndices;
    std::vector<uint32_t> m_cachedVertexCounts;
    std::vector<uint32_t> m_cachedFlags;
    std::vector<float> m_cachedThicknesses;
    // accumulated length from the start of the curve till the current vertex
    std::vector<float> m_cachedLengths;
    bool m_cacheIsDirty = true;

    CurveGesturePayload m_lastGesturePayload;
    std::array<std::unique_ptr<CurveGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;

    bool m_intersectionThicknessExplicitlyChanged = false;
};

Curve::Curve(const std::vector<Vector3>& positions)
    : AbstractShape(new CurveData)
{
    this->_setPositionsChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setColorsChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setThicknessesChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setCurveTypeChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setTessellationChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setIntersectionThicknessChangedFn([this](const auto&) {
        _getData<CurveData>().m_intersectionThicknessExplicitlyChanged = true;
    });

    this->setPositions(positions);
}

Curve::~Curve() = default;

void Curve::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    this->_rebuildCache();

    // OM-98612: There is the potential where we will return before m_cachedPositions has any data
    // populated from _rebuildCache() -- In this case addPolygonLines will crash the app.
    auto& data = _getData<CurveData>();
    if (data.m_cachedPositions.size() == 0)
    {
        return;
    }

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        drawList->addPolygonLines(data.m_cachedPositions.data(), data.m_cachedColors.data(), data.m_cachedThicknesses.data(),
                                  data.m_cachedVertexIndices.data(), data.m_cachedVertexCounts.data(), nullptr,
                                  data.m_cachedVertexCounts.size());
    }
}

void Curve::intersect(const Vector3 origin,
                      const Vector3 direction,
                      const Vector2 mouse,
                      const Matrix44& projection,
                      const Matrix44& view,
                      GestureState state)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& data = _getData<CurveData>();
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<CurveGesturePayload>();
    }

    Vector3 lastClosestPoint = data.m_lastGesturePayload.rayClosestPoint;
    Float lastMovedDistance = data.m_lastGesturePayload.curveDistance;

    auto transform = this->getParent()->getAccumulatedTransform();

    const auto& positions = data.m_cachedPositions;
    size_t vertexCount = positions.size();

    if (vertexCount < 2)
    {
        return;
    }

    Vector3 minRayPoint (0.f, 0.f, 0.f);
    Vector3 minSegPoint (0.f, 0.f, 0.f);
    Float minRayDistance = std::numeric_limits<Float>::max();
    Float minDistanceToSeg = std::numeric_limits<Float>::max();
    Float minDistanceRaySeg = std::numeric_limits<Float>::max();
    size_t minSegIndex = 0;
    // iterate all of the segments and find the closest one.
    Vector3 start = Vector3{ transform * Vector4{ positions[0], 1.0 } };
    for (size_t i = 1; i < vertexCount; ++i)
    {
        Vector3 end = Vector3{ transform * Vector4{ positions[i], 1.0 } };

        Vector3 rayPoint;
        Vector3 segPoint;
        Float rayDistance;
        Float segDistance;

        // Get two points, one on the line, another on the ray
        raySegFindClosestPoints(origin, direction, start, end, &rayPoint, &segPoint, &rayDistance, &segDistance);

        Vector3 dist = rayPoint - segPoint;
        Float distanceRaySeg = dist.x * dist.x + dist.y * dist.y + dist.z * dist.z;

        if (i == 1 || distanceRaySeg < minDistanceRaySeg)
        {
            minRayPoint = rayPoint;
            minSegPoint = segPoint;
            minRayDistance = rayDistance;
            minDistanceToSeg = segDistance;
            minSegIndex = i;
            minDistanceRaySeg = distanceRaySeg;
        }
        start = end;
    }

    Float minCurveDistance = data.m_cachedLengths[minSegIndex-1] + minDistanceToSeg * (data.m_cachedLengths[minSegIndex] - data.m_cachedLengths[minSegIndex-1]);
    data.m_lastGesturePayload.rayClosestPoint = minRayPoint;
    data.m_lastGesturePayload.itemClosestPoint = minSegPoint;
    data.m_lastGesturePayload.rayDistance = minRayDistance;
    data.m_lastGesturePayload.curveDistance = minCurveDistance / data.m_cachedLengths[vertexCount-1];
    data.m_lastGesturePayload.moved = data.m_lastGesturePayload.rayClosestPoint - lastClosestPoint;
    data.m_lastGesturePayload.movedDistance = data.m_lastGesturePayload.curveDistance - lastMovedDistance;

    // Copy
    *stateGesturePayload = data.m_lastGesturePayload;
}

const Curve::CurveGesturePayload* Curve::getGesturePayload() const
{
    auto& data = _getData<CurveData>();
    return &data.m_lastGesturePayload;
}

const Curve::CurveGesturePayload* Curve::getGesturePayload(GestureState state) const
{
    return _getData<CurveData>().m_itersections[static_cast<uint32_t>(state)].get();
}

Float Curve::getIntersectionDistance() const
{
    auto& data = _getData<CurveData>();
    if (data.m_intersectionThicknessExplicitlyChanged)
    {
        return this->getIntersectionThickness();
    }

    if (this->getThicknesses().size() < 1)
    {
        return AbstractShape::getIntersectionDistance();
    }

    // TODO: `this->getThicknesses()[0]` is wrong. We need to find correct value
    // using the payload.
    return std::max(AbstractShape::getIntersectionDistance(), this->getThicknesses()[0] * 0.5);
}

void Curve::_dirtyCache()
{
    _getData<CurveData>().m_cacheIsDirty = true;
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void Curve::_rebuildCache()
{
    auto& data = _getData<CurveData>();
    if (!data.m_cacheIsDirty)
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const auto& positions = this->getPositions();
    size_t vertexCount = positions.size();

    if (vertexCount < 2)
    {
        OMNIUI_LOG_ERROR("Input Error: input positions size should be larger than 1 to create a curve");
        // To prevent recomputing with invalid data, instead wait for something to change
        // before attempting to rebuild cache again.
        data.m_cacheIsDirty = false;
        return;
    }
    size_t segmentCount = vertexCount - 1;

    Curve::CurveType curve_type = this->getCurveType();
    uint16_t tessellation = this->getTessellation() - 1;

    data.m_cachedPositions.clear();
    if (curve_type == Curve::CurveType::cubic)
    {
        // check the vertexCount satisfies the cubic curve
        if (segmentCount % 3 != 0)
        {
            OMNIUI_LOG_ERROR("Input Error: input positions size does not construct a bezier curve");
            // To prevent recomputing with invalid data, instead wait for something to change
            // before attempting to rebuild cache again.
            data.m_cacheIsDirty = false;
            return;
        }

        vertexCount += segmentCount * (tessellation - 1);

        data.m_cachedPositions.reserve(vertexCount);
        data.m_cachedPositions.push_back(positions[0]);
        for (size_t i = 0; i + 2 < segmentCount; i += 3)
        {
            _computeCurvePoses(
                positions[i], positions[i + 1], positions[i + 2], positions[i + 3], tessellation, data.m_cachedPositions);
        }
    }
    else
    {
        data.m_cachedPositions = positions;
    }

    // vertex counts and vertex indices
    data.m_cachedVertexCounts.clear();
    data.m_cachedVertexCounts.push_back(uint32_t(vertexCount));

    data.m_cachedVertexIndices.resize(vertexCount);
    std::iota(std::begin(data.m_cachedVertexIndices), std::end(data.m_cachedVertexIndices), 0);

    // lengths
    data.m_cachedLengths.clear();
    data.m_cachedLengths.reserve(vertexCount);
    data.m_cachedLengths.push_back(0.0f);
    for (size_t i = 1; i < vertexCount; ++i)
    {
        Vector3 dist = data.m_cachedPositions[i] - data.m_cachedPositions[i-1];
        float length = float(std::sqrt(dist.x * dist.x + dist.y * dist.y + dist.z * dist.z)) + data.m_cachedLengths[i-1];
        data.m_cachedLengths.push_back(length);
    }

    // colors
    const auto& colors = this->getColors();
    const Color4 defaultColor = colors.empty() ? Color4{ 1.0 } : colors.back();
    size_t colorsSize = colors.size();
    data.m_cachedColors.clear();
    data.m_cachedColors.reserve(vertexCount);
    if (colorsSize == 0 || colorsSize == 1)
    {
        data.m_cachedColors.resize(vertexCount);
        std::fill(data.m_cachedColors.begin(), data.m_cachedColors.end(), defaultColor);
    }
    else if (colorsSize == 2)
    {
        _interpolateColor(colors[0], colors[1], vertexCount - 1, data.m_cachedColors);
        // push the last color
        data.m_cachedColors.push_back(colors[1]);
    }
    else if (colorsSize == segmentCount)
    {
        for (size_t count = 0; count < segmentCount; ++count)
        {
            // push the tessellation color
            if (curve_type == Curve::CurveType::cubic)
            {
                for (uint16_t i = 0; i < tessellation; ++i)
                {
                    data.m_cachedColors.push_back(colors[count]);
                }
            }
            else
            {
                data.m_cachedColors.push_back(colors[count]);
            }
        }
        // push the last color
        data.m_cachedColors.push_back(colors[segmentCount - 1]);
    }
    else if (colorsSize == segmentCount + 1)
    {
        for (size_t count = 0; count < segmentCount; ++count)
        {
            // push the tessellation color
            if (curve_type == Curve::CurveType::cubic)
            {
                _interpolateColor(colors[count], colors[count + 1], tessellation, data.m_cachedColors);
            }
            else
            {
                data.m_cachedColors.push_back(colors[count]);
            }
        }
        // push the last color
        data.m_cachedColors.push_back(colors[segmentCount]);
    }
    else
    {
        OMNIUI_LOG_ERROR(
            "Input Error: input color size does not construct a bezier curve. \
        It could be 0, 1, 2, %i, %i",
            int(segmentCount), int(segmentCount + 1));

        // give the whilte color instead of crashing
        data.m_cachedColors.resize(vertexCount);
        std::fill(data.m_cachedColors.begin(), data.m_cachedColors.end(), Color4{ 1.0 });
    }

    // thickness
    const auto& thicknesses = this->getThicknesses();
    const auto defaultThickness = thicknesses.empty() ? 1 : thicknesses.back();
    size_t thicknessesSize = thicknesses.size();
    data.m_cachedThicknesses.clear();
    data.m_cachedThicknesses.reserve(vertexCount);

    if (thicknessesSize == 0 || thicknessesSize == 1)
    {
        data.m_cachedThicknesses.resize(vertexCount);
        std::fill(data.m_cachedThicknesses.begin(), data.m_cachedThicknesses.end(), defaultThickness);
    }
    else if (thicknessesSize == 2)
    {
        _interpolateFloat(thicknesses[0], thicknesses[1], vertexCount - 1, data.m_cachedThicknesses);
        // push the last thickness
        data.m_cachedThicknesses.push_back(thicknesses[1]);
    }
    else if (thicknessesSize == segmentCount)
    {
        for (size_t count = 0; count < segmentCount; ++count)
        {
            // push the tessellation thickness
            if (curve_type == Curve::CurveType::cubic)
            {
                for (uint16_t i = 0; i < tessellation; ++i)
                {
                    data.m_cachedThicknesses.push_back(thicknesses[count]);
                }
            }
            else
            {
                data.m_cachedThicknesses.push_back(thicknesses[count]);
            }
        }
        // push the last thickness
        data.m_cachedThicknesses.push_back(thicknesses[segmentCount - 1]);
    }
    else if (thicknessesSize == segmentCount + 1)
    {
        for (size_t count = 0; count < segmentCount; ++count)
        {
            // push the tessellation thickness
            if (curve_type == Curve::CurveType::cubic)
            {
                _interpolateFloat(thicknesses[count], thicknesses[count + 1], tessellation, data.m_cachedThicknesses);
            }
            else
            {
                data.m_cachedThicknesses.push_back(thicknesses[count]);
            }
        }
        // push the last thickness
        data.m_cachedThicknesses.push_back(thicknesses[segmentCount]);
    }
    else
    {
        OMNIUI_LOG_ERROR(
            "Input Error: input thickness size does not construct a bezier curve. \
        It could be 0, 1, 2, %i, %i",
            int(segmentCount), int(segmentCount + 1));

        // give the thickness of 1 instead of crashing
        data.m_cachedThicknesses.resize(vertexCount);
        std::fill(data.m_cachedThicknesses.begin(), data.m_cachedThicknesses.end(), 1.0f);
    }
    data.m_cacheIsDirty = false;
}

void Curve::_interpolateFloat(float start, float end, size_t segment, std::vector<float>& result)
{
    float step = (end - start) / segment;

    for (size_t i = 0; i < segment; ++i)
    {
        result.push_back(start + step * i);
    }
}

void Curve::_interpolateColor(Color4 start, Color4 end, size_t segment, std::vector<Color4>& result)
{
    float stepR = float(end[0] - start[0]) / segment;
    float stepG = float(end[1] - start[1]) / segment;
    float stepB = float(end[2] - start[2]) / segment;
    float stepA = float(end[3] - start[3]) / segment;

    for (size_t i = 0; i < segment; ++i)
    {
        result.push_back({ start[0] + stepR * i, start[1] + stepG * i, start[2] + stepB * i, start[3] + stepA * i });
    }
}

void Curve::_computeCurvePoses(const Vector3 p0,
                               const Vector3 p1,
                               const Vector3 p2,
                               const Vector3 p3,
                               const uint16_t tessellation,
                               std::vector<Vector3>& poses)
{
    // see https://en.wikipedia.org/wiki/B%C3%A9zier_curve about the cubic bezier curve equation
    uint16_t totalSeg = tessellation * 3;
    double step = 1.0 / double(totalSeg);
    for (uint16_t i = 1; i < totalSeg; ++i)
    {
        double t = step * i;
        double p = 1 - t;
        double w1 = std::pow(p, 3);
        double w2 = 3 * p * p * t;
        double w3 = 3 * p * t * t;
        double w4 = std::pow(t, 3);
        double bCurveXt = w1 * p0.x + w2 * p1.x + w3 * p2.x + w4 * p3.x;
        double bCurveYt = w1 * p0.y + w2 * p1.y + w3 * p2.y + w4 * p3.y;
        double bCurveZt = w1 * p0.z + w2 * p1.z + w3 * p2.z + w4 * p3.z;

        poses.push_back(Vector3{ bCurveXt, bCurveYt, bCurveZt });
    }
    poses.push_back(p3);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
