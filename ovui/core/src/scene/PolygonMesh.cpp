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
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Math.h>
#include <omni/ui/scene/PolygonMesh.h>

#include "PolygonMeshData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

#define EPS 1e-6

PolygonMesh::PolygonMeshData::PolygonMeshData()
    : m_lastGesturePayload(std::make_unique<PolygonMeshGesturePayload>())
{
}

PolygonMesh::PolygonMeshData::~PolygonMeshData()
{
}

PolygonMesh::PolygonMesh(const std::vector<Vector3>& positions,
                         const std::vector<Color4>& colors,
                         const std::vector<uint32_t>& vertexCounts,
                         const std::vector<uint32_t>& vertexIndices,
                         PolygonMeshData* data)
    : AbstractShape(data ? data : new PolygonMeshData)
{
    this->_setPositionsChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setColorsChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setVertexCountsChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setVertexIndicesChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setThicknessesChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setWireframeChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setIntersectionThicknessChangedFn([this](const auto&) {
        _getData<PolygonMeshData>().m_intersectionThicknessExplicitlyChanged = true;
    });

    auto& lastGesturePayload = _getData<PolygonMeshData>().m_lastGesturePayload;
    lastGesturePayload->itemClosestPoint = Vector3{ 0.0 };
    lastGesturePayload->rayClosestPoint = Vector3{ 0.0 };
    lastGesturePayload->rayDistance = 0.0;

    this->setPositions(positions);
    this->setColors(colors);
    this->setVertexCounts(vertexCounts);
    this->setVertexIndices(vertexIndices);
}

PolygonMesh::~PolygonMesh() = default;

void PolygonMesh::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    if (this->getPositions().empty())
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        if (this->isWireframe())
        {
            if (!this->getThicknesses().empty())
            {
                this->_rebuildCache();

                auto& data = _getData<PolygonMeshData>();
                drawList->addPolygonLines(this->getPositions().data(), data.m_cachedColors.data(),
                                          data.m_cachedThicknesses.data(), data.m_cachedVertexIndices.data(),
                                          data.m_cachedVertexCounts.data(), nullptr, data.m_cachedVertexCounts.size());
            }
        }
        else
        {
            drawList->addPolygonMesh(this->getPositions().data(), this->getColors().data(),
                                     this->getVertexIndices().data(), this->getVertexCounts().data(),
                                     this->getVertexCounts().size());
        }
    }
}

void PolygonMesh::_calculateST(const Vector3 origin, const Vector3 direction, Float& g_s, Float& g_t, int32_t& g_faceId,
                               Vector3& g_itemClosestPoint, Vector3& g_rayClosestPoint, Float& g_rayDistance)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto transform = this->getParent()->getAccumulatedTransform();

    const auto& vertexCounts = this->getVertexCounts();
    const auto& positions = this->getPositions();
    uint32_t i = 0;
    g_faceId = -1;
    for (uint32_t id = 0; id < vertexCounts.size(); id++)
    {
        uint32_t count = vertexCounts[id];
        // do it here since different count conditions might return earlier
        i += count;
        if (i > positions.size())
            break;

        if (count != 3 && count != 4)
            continue;

        Vector3 p0 = Vector3{ transform * Vector4{ positions[i - count], 1.0 } };
        Vector3 p1 = Vector3{ transform * Vector4{ positions[i - count + 1], 1.0 } };
        Vector3 p2 = Vector3{ transform * Vector4{ positions[i - count + 2], 1.0 } };
        Vector3 v1 = p1 - p0;

        if (count == 3)
        {
            Vector3 v2 = p2 - p0;

            Float s, t;
            Vector3 rayClosestPoint;
            if (!raySegPlaneGesturePayload(origin, direction, p0, v1, v2, &rayClosestPoint, &s, &t))
                continue;
            if ( s < 0 || s > 1 || t < 0 ||t > 1 || t + s > 1)
                continue;

            g_s = s;
            g_t = t;
            g_faceId = id;
            g_itemClosestPoint = p0 + v1 * s + v2 * t;
            g_rayClosestPoint = rayClosestPoint;
            g_rayDistance = glm::length(rayClosestPoint - origin);
            break;
        }
        else if (count == 4)
        {
            Vector3 p3 = Vector3{ transform * Vector4{ positions[i - count + 3], 1.0 } };

            Vector3 v2 = p3 - p0;
            Vector3 v3 = p3 - p2;
            Vector3 v4 = p1 - p2;

            Vector3 normal1 = glm::cross(v1, v2);
            Vector3 normal2 = glm::cross(v3, v4);

            // we only care about 4 points shape which are on the same plane. Otherwise, we could potencially
            // have more than one intersection
            if (glm::length(glm::cross(normal1, normal2)) > EPS)
                continue;

            Float s0, t0, s1, t1;
            Vector3 rayClosestPoint0, rayClosestPoint1;
            if (!raySegPlaneGesturePayload(origin, direction, p0, v1, v2, &rayClosestPoint0, &s0, &t0))
                continue;

            if (!raySegPlaneGesturePayload(origin, direction, p2, v3, v4, &rayClosestPoint1, &s1, &t1))
                continue;

            Vector3 p, rayClosestPoint;
            Float s = -1.0, t = -1.0;

            if (glm::dot(normal1, normal2) < -EPS)
            {
                //  p2 is inside of the triangle of p0-p1-p3
                // outside of the shape
                if (s0 < 0 || t0 < 0 || (s1 > 0 && t1 > 0))
                    continue;

                p = p0 + v1 * s0 + v2 * t0;
                s = s0;
                t = t0;
                rayClosestPoint = rayClosestPoint0;
            }
            else
            {
                // normal cases where p2 is outside of the triangle of p0-p1-p3
                // outside of the shape
                if (s0 < 0 || t0 < 0 || s1 < 0 || t1 < 0)
                    continue;

                if (s0 + t0 <= 1)
                {
                    p = p0 + v1 * s0 + v2 * t0;
                    s = s0;
                    t = t0;
                    rayClosestPoint = rayClosestPoint0;
                }
                else if ( s1 + t1 <= 1 )
                {
                    p = p2 + v3 * s1 + v4 * t1;
                    s = 1 - s1;
                    t = 1 - t1;
                    rayClosestPoint = rayClosestPoint1;
                }
            }
            g_s = s;
            g_t = t;
            g_faceId = id;
            g_itemClosestPoint = p;
            g_rayClosestPoint = rayClosestPoint;
            g_rayDistance = glm::length(rayClosestPoint - origin);
            break;
        }
    }
    // no intersection
    if (g_faceId == -1)
    {
        // We are here if the ray is not intersecting with the polygon mesh
        g_s = -1.0;
        g_t = -1.0;
        g_rayDistance = 0.0;
        g_rayClosestPoint = origin;
        g_itemClosestPoint = origin;
    }
}

void PolygonMesh::intersect(const Vector3 origin,
                            const Vector3 direction,
                            const Vector2 mouse,
                            const Matrix44& projection,
                            const Matrix44& view,
                            GestureState state)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& data = _getData<PolygonMeshData>();

    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<PolygonMeshGesturePayload>();
    }

    auto& lastGesturePaylod = _getData<PolygonMeshData>().m_lastGesturePayload;
    _calculateST(origin, direction, lastGesturePaylod->s, lastGesturePaylod->t, lastGesturePaylod->faceId,
        lastGesturePaylod->itemClosestPoint, lastGesturePaylod->rayClosestPoint, lastGesturePaylod->rayDistance);

    *stateGesturePayload.get() = *lastGesturePaylod.get();
}

const PolygonMesh::PolygonMeshGesturePayload* PolygonMesh::getGesturePayload() const
{
    return _getData<PolygonMeshData>().m_lastGesturePayload.get();
}

const PolygonMesh::PolygonMeshGesturePayload* PolygonMesh::getGesturePayload(GestureState state) const
{
    return _getData<PolygonMeshData>().m_itersections[static_cast<uint32_t>(state)].get();
}

void PolygonMesh::_dirtyCache()
{
    _getData<PolygonMeshData>().m_cacheIsDirty = true;
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void PolygonMesh::_rebuildCache()
{
    auto& data = _getData<PolygonMeshData>();

    // It's only called for the wireframe mode
    if (!data.m_cacheIsDirty)
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    size_t vertexCount = 0;

    data.m_cachedVertexCounts.clear();
    _ensureCapacity(data.m_cachedVertexCounts, this->getVertexCounts().size());
    // Copy vertexCounts increasing each face count
    for (uint32_t count : this->getVertexCounts())
    {
        data.m_cachedVertexCounts.push_back(++count);
        vertexCount += count;
    }

    const auto& colors = this->getColors();
    const auto& vertexIndices = this->getVertexIndices();
    const auto& thicknesses = this->getThicknesses();
    const size_t totalSize = this->getVertexIndices().size() + this->getVertexCounts().size();

    data.m_cachedColors.reserve(totalSize);
    data.m_cachedVertexIndices.reserve(totalSize);
    data.m_cachedThicknesses.reserve(totalSize);

    // Repeat the last values if the buffers aren't a correct length
    const Color4 defaultColor = colors.empty() ? Color4(1, 1, 1, 1) : colors.back();
    const auto defaultThickness = thicknesses.empty() ? 1 : thicknesses.back();

    // Copy vertexIndices, colors, thicknesses and close the shape
    size_t vertexCounter = 0;
    for (uint32_t count : this->getVertexCounts())
    {
        const auto& firstColor = vertexCounter < colors.size() ? colors[vertexCounter] : defaultColor;
        const auto& firstIndex = vertexCounter < vertexIndices.size() ? vertexIndices[vertexCounter] : vertexIndices.back();
        const auto& firstThicknesses = vertexCounter < thicknesses.size() ? thicknesses[vertexCounter] : defaultThickness;

        for (size_t i = 0; i < count; ++i, ++vertexCounter)
        {
            data.m_cachedColors.push_back(vertexCounter < colors.size() ? colors[vertexCounter] : firstColor);
            data.m_cachedVertexIndices.push_back(vertexCounter < vertexIndices.size() ? vertexIndices[vertexCounter] : firstIndex);
            data.m_cachedThicknesses.push_back(vertexCounter < thicknesses.size() ? thicknesses[vertexCounter] : firstThicknesses);
        }

        // Close shape
        data.m_cachedColors.push_back(firstColor);
        data.m_cachedVertexIndices.push_back(firstIndex);
        data.m_cachedThicknesses.push_back(firstThicknesses);
    }

    data.m_cacheIsDirty = false;
}

Float PolygonMesh::getIntersectionDistance() const
{
    auto& data = _getData<PolygonMeshData>();
    if (data.m_intersectionThicknessExplicitlyChanged && this->isWireframe())
    {
        return this->getIntersectionThickness();
    }

    if (!data.m_lastGesturePayload || !this->isWireframe() || this->getThicknesses().size() < 1)
    {
        return AbstractShape::getIntersectionDistance();
    }

    // TODO: `this->getThicknesses()[0]` is wrong. We need to find correct value
    // using the payload.
    return std::max(AbstractShape::getIntersectionDistance(), this->getThicknesses()[0] * 0.5);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
