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

#include <omni/ui/Profile.h>

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/Arc.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Math.h>

#include "AbstractShapeData.h"

#include <numeric>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

struct Arc::ArcData : public AbstractShape::AbstractShapeData
{
    ~ArcData() override = default;

    // Cache to avoid computation every frame
    std::vector<Vector3> m_cachedPoints;
    std::vector<Color4> m_cachedColors;
    std::vector<uint32_t> m_cachedVertexIndices;
    std::vector<uint32_t> m_cachedVertexCounts;
    std::vector<uint32_t> m_cachedFlags;
    std::vector<float> m_cachedThicknesses;
    bool m_cacheIsDirty = true;

    ArcGesturePayload m_lastGesturePayload;
    std::array<std::unique_ptr<ArcGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;

    bool m_intersectionThicknessExplicitlyChanged = false;
};

Arc::Arc(Float radius)
    : AbstractShape(new ArcData)
{
    this->_setRadiusChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setBeginChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setEndChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setThicknessChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setColorChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setTesselationChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setWireframeChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setSectorChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setAxisChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setCullingChangedFn(std::bind(&This::_dirtyCache, this));
    this->setRadius(radius);
    this->_setIntersectionThicknessChangedFn([this](const auto&) {
        _getData< ArcData>().m_intersectionThicknessExplicitlyChanged = true;
    });
}

Arc::~Arc() = default;

void Arc::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    this->_rebuildCache();

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        auto& data = _getData< ArcData>();
        if (this->isWireframe())
        {
            drawList->addPolygonLines(data.m_cachedPoints.data(), data.m_cachedColors.data(), data.m_cachedThicknesses.data(),
                                      data.m_cachedVertexIndices.data(), data.m_cachedVertexCounts.data(),
                                      data.m_cachedFlags.data(), data.m_cachedVertexCounts.size());
        }
        else
        {
            drawList->addPolygonMesh(data.m_cachedPoints.data(), data.m_cachedColors.data(), data.m_cachedVertexIndices.data(),
                                     data.m_cachedVertexCounts.data(), data.m_cachedVertexCounts.size());
        }
    }
}

void Arc::intersect(const Vector3 origin,
                    const Vector3 direction,
                    const Vector2 mouse,
                    const Matrix44& projection,
                    const Matrix44& view,
                    GestureState state)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& data = _getData< ArcData>();
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<ArcGesturePayload>();
    }

    Vector3 lastClosestPoint = data.m_lastGesturePayload.rayClosestPoint;
    Float lastDistanceToCenter = data.m_lastGesturePayload.distanceToCenter;
    Float lastAngle = data.m_lastGesturePayload.angle;

    auto transform = this->getParent()->getAccumulatedTransform();

    Float radius = this->getRadius();
    Float from = this->getBegin();
    Float to = this->getEnd();

    Vector3 p0 = Vector3{ transform * Vector4{ 0.0, 0.0, 0.0, 1.0 } };
    Vector3 p1;
    Vector3 p2;
    switch (this->getAxis())
    {
    case 0:
        p1 = Vector3{ transform * Vector4{ 0.0, radius, 0.0, 1.0 } };
        p2 = Vector3{ transform * Vector4{ 0.0, 0.0, radius, 1.0 } };
        break;
    case 1:
        p1 = Vector3{ transform * Vector4{ 0.0, 0.0, radius, 1.0 } };
        p2 = Vector3{ transform * Vector4{ radius, 0.0, 0.0, 1.0 } };
        break;
    default:
        p1 = Vector3{ transform * Vector4{ radius, 0.0, 0.0, 1.0 } };
        p2 = Vector3{ transform * Vector4{ 0.0, radius, 0.0, 1.0 } };
        break;
    }


    Vector3 v1 = p1 - p0;
    Vector3 v2 = p2 - p0;

    Vector2 st;

    if (!raySegPlaneGesturePayload(origin, direction, p0, v1, v2, &data.m_lastGesturePayload.rayClosestPoint, &st.x, &st.y))
    {
        // We are here if the ray is not pointing to the plane of the rect
        data.m_lastGesturePayload.rayDistance = 0.0;
        data.m_lastGesturePayload.rayClosestPoint = origin;
        data.m_lastGesturePayload.itemClosestPoint = origin;
        return;
    }

    Float lengthSt = glm::length(st);
    Vector2 normalizedSt = glm::normalize(st);
    Float angleSt = glm::atan(normalizedSt.y, normalizedSt.x);

    // Correction for continuous rotation when rotating 360 degrees
    Float distance = abs(lastAngle - angleSt);
    if (state != GestureState::ePossible && state != GestureState::eBegan && distance > (Float)M_PI)
    {
        Float direction = angleSt > lastAngle ? (Float)-1.0 : (Float)1.0;
        angleSt += glm::round((Float)0.5 * distance / (Float)M_PI) * direction * (Float)2.0 * (Float)M_PI;
    }

    Float angleStUnclamped = angleSt;

    bool clamped = false;

    // If it's not a circle, we do correction
    if (glm::abs(to - from) < Float(2.0 * M_PI) && (angleSt < from || angleSt > to))
    {
        angleSt = glm::clamp(angleSt, from, to);
        normalizedSt = Vector2{ glm::cos(angleSt), glm::sin(angleSt) };
        st = normalizedSt * lengthSt;
        clamped = true;
    }

    if (this->isWireframe())
    {
        // Calculate the direction from the center of the arc to the intersection point.
        // This direction represents where on the arc the gesture happened.
        Vector3 dirFromCenterToIntersection = v1 * normalizedSt.x + v2 * normalizedSt.y;

        // Check for culling settings to decide if the interaction is on the visible side of the arc
        auto culling = this->getCulling();
        if (culling != Culling::eNone)
        {
            data.m_lastGesturePayload.culled = false;
        }
        else
        {
            // The third column of the view matrix represents the negative camera's forward direction
            Vector3 camDir = -Vector3(view[0][2], view[1][2], view[2][2]);

            // Check if the direction from the center to the intersection is in the same direction as
            // the camera's forward direction. If it is, then the intersection is in front of the camera.
            bool isIntersectionInFront = glm::dot(dirFromCenterToIntersection, camDir) > (Float)-0.05;

            // Set the culled flag based on the culling setting and whether the intersection is in front.
            // If culling is set to back and the intersection is in front, then it's culled. and visa versa.
            data.m_lastGesturePayload.culled = (culling == Culling::eBack) ? isIntersectionInFront : !isIntersectionInFront;
        }

        // Store the world-space position of the closest point on the arc where the interaction happened.
        data.m_lastGesturePayload.itemClosestPoint = p0 + dirFromCenterToIntersection;
    }
    else
    {
        Float clampedDistance = std::min(lengthSt, Float(1.0));
        data.m_lastGesturePayload.itemClosestPoint =
            p0 + v1 * normalizedSt.x * clampedDistance + v2 * normalizedSt.y * clampedDistance;
        data.m_lastGesturePayload.culled = false;
    }

    data.m_lastGesturePayload.rayDistance = glm::length(data.m_lastGesturePayload.rayClosestPoint - origin);
    data.m_lastGesturePayload.distanceToCenter = lengthSt * radius;
    data.m_lastGesturePayload.angle = angleStUnclamped;
    data.m_lastGesturePayload.movedDistanceToCenter = data.m_lastGesturePayload.distanceToCenter - lastDistanceToCenter;
    data.m_lastGesturePayload.movedAngle = angleStUnclamped - lastAngle;
    data.m_lastGesturePayload.moved = data.m_lastGesturePayload.rayClosestPoint - lastClosestPoint;

    // Copy
    *stateGesturePayload = data.m_lastGesturePayload;
}

const Arc::ArcGesturePayload* Arc::getGesturePayload() const
{
    return &(_getData< ArcData>().m_lastGesturePayload);
}

const Arc::ArcGesturePayload* Arc::getGesturePayload(GestureState state) const
{
    return _getData< ArcData>().m_itersections[static_cast<uint32_t>(state)].get();
}

Float Arc::getIntersectionDistance() const
{
    if (!this->isWireframe())
    {
        return AbstractShape::getIntersectionDistance();
    }

    if (_getData< ArcData>().m_intersectionThicknessExplicitlyChanged)
    {
        return this->getIntersectionThickness();
    }

    return std::max(AbstractShape::getIntersectionDistance(), this->getThickness() * 0.5);
}

void Arc::_dirtyCache()
{
    _getData< ArcData>().m_cacheIsDirty = true;
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void Arc::_rebuildCache()
{
    auto& data = _getData< ArcData>();
    if (!data.m_cacheIsDirty)
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    uint16_t tesselation = this->getTesselation() + 2;
    Float radius = this->getRadius();
    Float from = this->getBegin();
    Float to = this->getEnd();

    bool isSector = this->isSector();
    bool isWireframe = this->isWireframe();
    if (abs(to - from) >= (Float)M_PI * 2.0)
    {
        // It's full circle and we don't want weird geometry
        from = -(Float)M_PI;
        to = (Float)M_PI;
        isSector = false;
    }

    uint32_t pointCount = tesselation;

    if (isSector)
    {
        pointCount += isWireframe ? 2 : 1;
    }

    data.m_cachedPoints.clear();
    data.m_cachedPoints.reserve(pointCount);

    if (isSector)
    {
        data.m_cachedPoints.emplace_back(0.0, 0.0, 0.0);
    }

    auto axis = this->getAxis();

    for (uint16_t i = 0, n = tesselation; i < n; ++i)
    {
        Float angle = from + (to - from) * static_cast<Float>(i) / (tesselation - 1);

        switch (axis)
        {
        case 0:
            data.m_cachedPoints.emplace_back(0.0, glm::cos(angle) * radius, glm::sin(angle) * radius);
            break;
        case 1:
            data.m_cachedPoints.emplace_back(glm::sin(angle) * radius, 0.0, glm::cos(angle) * radius);
            break;
        default:
            data.m_cachedPoints.emplace_back(glm::cos(angle) * radius, glm::sin(angle) * radius, 0.0);
            break;
        };
    }

    if (isSector && isWireframe)
    {
        data.m_cachedPoints.emplace_back(0.0, 0.0, 0.0);
    }

    data.m_cachedColors.resize(pointCount);
    std::fill(data.m_cachedColors.begin(), data.m_cachedColors.end(), this->getColor());

    data.m_cachedThicknesses.resize(pointCount);
    std::fill(data.m_cachedThicknesses.begin(), data.m_cachedThicknesses.end(), this->getThickness());

    data.m_cachedVertexIndices.resize(pointCount);
    std::iota(data.m_cachedVertexIndices.begin(), data.m_cachedVertexIndices.end(), 0);

    data.m_cachedVertexCounts.clear();
    data.m_cachedVertexCounts.push_back(pointCount);

    data.m_cachedFlags.clear();
    switch (this->getCulling())
    {
    case Culling::eBack:
        data.m_cachedFlags.push_back(DrawList::LINE_FLAG_BACK_CULLING);
        break;
    case Culling::eFront:
        data.m_cachedFlags.push_back(DrawList::LINE_FLAG_FRONT_CULLING);
        break;
    default:
        data.m_cachedFlags.push_back(DrawList::LINE_FLAG_NONE);
    }

    data.m_cacheIsDirty = false;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
