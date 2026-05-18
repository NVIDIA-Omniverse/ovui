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

#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Math.h>
#include <omni/ui/scene/Rectangle.h>

#include "RectangleData.h"

#include <numeric>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

Rectangle::RectangleData::~RectangleData()
{
}

Rectangle::Rectangle(Float width, Float height, RectangleData* dataPtr)
    : AbstractShape(dataPtr ? dataPtr : new RectangleData)
{
    this->_setWidthChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setHeightChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setThicknessChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setColorChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setAxisChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setWireframeChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setIntersectionThicknessChangedFn([this](const auto&) {
        _getData<RectangleData>().m_intersectionThicknessExplicitlyChanged = true;
    });
    this->setWidth(width);
    this->setHeight(height);
}

Rectangle::~Rectangle() = default;

void Rectangle::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    this->_rebuildCache();

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        auto& data = _getData<RectangleData>();
        if (this->isWireframe())
        {
            drawList->addPolygonLines(data.m_cachedPoints.data(), data.m_cachedColors.data(), data.m_cachedThicknesses.data(),
                                      data.m_cachedVertexIndices.data(), data.m_cachedVertexCounts.data(), nullptr,
                                      data.m_cachedVertexCounts.size());
        }
        else
        {
            drawList->addPolygonMesh(data.m_cachedPoints.data(), data.m_cachedColors.data(), data.m_cachedVertexIndices.data(),
                                     data.m_cachedVertexCounts.data(), data.m_cachedVertexCounts.size());
        }
    }
}

void Rectangle::intersect(const Vector3 origin,
                          const Vector3 direction,
                          const Vector2 mouse,
                          const Matrix44& projection,
                          const Matrix44& view,
                          GestureState state)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& data = _getData<RectangleData>();
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<RectangleGesturePayload>();
    }

    auto& gesturePayload = data.m_lastGesturePayload;
    Vector3 lastClosestPoint = gesturePayload.rayClosestPoint;
    Float lastS = gesturePayload.s;
    Float lastT = gesturePayload.t;

    auto transform = this->getParent()->getAccumulatedTransform();

    Float halfWidth = this->getWidth() * (Float)0.5;
    Float halfHeight = this->getHeight() * (Float)0.5;

    Vector3 p0;
    Vector3 p1;
    Vector3 p2;
    switch (this->getAxis())
    {
    case 0:
        p0 = Vector3{ transform * Vector4{ 0.0, -halfWidth, -halfHeight, 1.0 } };
        p1 = Vector3{ transform * Vector4{ 0.0, halfWidth, -halfHeight, 1.0 } };
        p2 = Vector3{ transform * Vector4{ 0.0, -halfWidth, halfHeight, 1.0 } };
        break;
    case 1:
        p0 = Vector3{ transform * Vector4{ -halfWidth, 0.0, -halfHeight, 1.0 } };
        p1 = Vector3{ transform * Vector4{ halfWidth, 0.0, -halfHeight, 1.0 } };
        p2 = Vector3{ transform * Vector4{ -halfWidth, 0.0, halfHeight, 1.0 } };
        break;
    default:
        p0 = Vector3{ transform * Vector4{ -halfWidth, -halfHeight, 0.0, 1.0 } };
        p1 = Vector3{ transform * Vector4{ halfWidth, -halfHeight, 0.0, 1.0 } };
        p2 = Vector3{ transform * Vector4{ -halfWidth, halfHeight, 0.0, 1.0 } };
        break;
    }

    Vector3 v1 = p1 - p0;
    Vector3 v2 = p2 - p0;

    if (!raySegPlaneGesturePayload(origin, direction, p0, v1, v2, &gesturePayload.rayClosestPoint,
                                   &gesturePayload.s, &gesturePayload.t))
    {
        // We are here if the ray is not pointing to the plane of the rect
        gesturePayload.rayDistance = 0.0;
        gesturePayload.rayClosestPoint = origin;
        gesturePayload.itemClosestPoint = origin;
        return;
    }

    Float sClamped = std::min((Float)1.0, std::max((Float)0.0, gesturePayload.s));
    Float tClamped = std::min((Float)1.0, std::max((Float)0.0, gesturePayload.t));

    gesturePayload.itemClosestPoint = p0 + v1 * sClamped + v2 * tClamped;
    gesturePayload.rayDistance = glm::length(gesturePayload.rayClosestPoint - origin);

    gesturePayload.movedS = gesturePayload.s - lastS;
    gesturePayload.movedT = gesturePayload.t - lastT;
    gesturePayload.moved = gesturePayload.rayClosestPoint - lastClosestPoint;

    // Copy
    *stateGesturePayload = gesturePayload;
}

const Rectangle::RectangleGesturePayload* Rectangle::getGesturePayload() const
{
    auto& data = _getData<RectangleData>();
    return &data.m_lastGesturePayload;
}

const Rectangle::RectangleGesturePayload* Rectangle::getGesturePayload(GestureState state) const
{
    return _getData<RectangleData>().m_itersections[static_cast<uint32_t>(state)].get();
}

Float Rectangle::getIntersectionDistance() const
{
    if (!this->isWireframe())
    {
        return AbstractShape::getIntersectionDistance();
    }

    auto& data = _getData<RectangleData>();
    if (data.m_intersectionThicknessExplicitlyChanged)
    {
        return this->getIntersectionThickness();
    }

    return std::max(AbstractShape::getIntersectionDistance(), this->getThickness() * 0.5);
}

void Rectangle::_dirtyCache()
{
    _getData<RectangleData>().m_cacheIsDirty = true;
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void Rectangle::_rebuildCache()
{
    auto& data = _getData<RectangleData>();
    if (!data.m_cacheIsDirty)
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    Float halfWidth = this->getWidth() * (Float).5;
    Float halfHeight = this->getHeight() * (Float).5;

    uint32_t vertexCount = this->isWireframe() ? 5 : 4;

    data.m_cachedPoints.clear();
    _ensureCapacity(data.m_cachedPoints, 4);

    switch (this->getAxis())
    {
    case 0:
        data.m_cachedPoints.emplace_back(0.0, -halfWidth, halfHeight);
        data.m_cachedPoints.emplace_back(0.0, halfWidth, halfHeight);
        data.m_cachedPoints.emplace_back(0.0, halfWidth, -halfHeight);
        data.m_cachedPoints.emplace_back(0.0, -halfWidth, -halfHeight);

        break;
    case 1:
        data.m_cachedPoints.emplace_back(halfWidth, 0.0, -halfHeight);
        data.m_cachedPoints.emplace_back(halfWidth, 0.0, halfHeight);
        data.m_cachedPoints.emplace_back(-halfWidth, 0.0, halfHeight);
        data.m_cachedPoints.emplace_back(-halfWidth, 0.0, -halfHeight);

        break;
    default:
        data.m_cachedPoints.emplace_back(halfWidth, -halfHeight, 0.0);
        data.m_cachedPoints.emplace_back(halfWidth, halfHeight, 0.0);
        data.m_cachedPoints.emplace_back(-halfWidth, halfHeight, 0.0);
        data.m_cachedPoints.emplace_back(-halfWidth, -halfHeight, 0.0);

        break;
    }

    data.m_cachedColors.resize(vertexCount);
    std::fill(data.m_cachedColors.begin(), data.m_cachedColors.end(), this->getColor());

    data.m_cachedThicknesses.resize(vertexCount);
    std::fill(data.m_cachedThicknesses.begin(), data.m_cachedThicknesses.end(), this->getThickness());

    data.m_cachedVertexIndices.clear();
    data.m_cachedVertexIndices.resize(vertexCount);
    std::iota(data.m_cachedVertexIndices.begin(), data.m_cachedVertexIndices.end(), 0);

    // Repeat first vertex.
    // This matches the rest of omni.ui.scene primitives that always have all
    // point attribute sizes match and makes it somewhat easier for other backends (OpenGL)
    // to consume the data as is rather that do conversions to ingest it (at the cost of one additional point)
    if (vertexCount == 5)
    {
        data.m_cachedPoints.emplace_back(data.m_cachedPoints.front());
    }

    data.m_cachedVertexCounts.clear();
    data.m_cachedVertexCounts.push_back(vertexCount);

    data.m_cacheIsDirty = false;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
