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
#include <omni/ui/scene/Points.h>

#include <limits>
#include "AbstractShapeData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

struct Points::PointsData : public AbstractShapeData
{
    PointsData()
        : m_lastGesturePayload(std::make_unique<PointsGesturePayload>())
    {
    }
    ~PointsData() override = default;

    std::unique_ptr<PointsGesturePayload> m_lastGesturePayload;
    std::array<std::unique_ptr<PointsGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;

    bool m_intersectionSizeExplicitlyChanged = false;
};

Points::Points(const std::vector<Vector3>& positions) : AbstractShape(new PointsData)
{
    this->_setPositionsChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setColorsChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setSizesChangedFn(std::bind(&This::_dirtyCache, this));
    this->_setIntersectionSizeChangedFn([this](const auto&) { _getData< PointsData>().m_intersectionSizeExplicitlyChanged = true; });
    this->setPositions(positions);
}

Points::~Points() = default;

void Points::_dirtyCache()
{
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void Points::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    if (this->getPositions().empty())
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        if (this->getColors().size() == 1 && this->getSizes().size() == 1)
        {
            drawList->addPoints(this->getPositions().data(), this->getColors().front(),
                                            this->getSizes().front(), this->getPositions().size());
        }
        else if (this->getPositions().size() == this->getColors().size() &&
                this->getPositions().size() == this->getSizes().size())
        {
            drawList->addPoints(this->getPositions().data(), this->getColors().data(), this->getSizes().data(),
                                            this->getPositions().size());
        }
    }
}

void Points::intersect(const Vector3 origin,
                       const Vector3 direction,
                       const Vector2 mouse,
                       const Matrix44& projection,
                       const Matrix44& view,
                       GestureState state)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& data = _getData<PointsData>();
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<PointsGesturePayload>();
    }

    auto transform = this->getParent()->getAccumulatedTransform();

    const auto& positions = this->getPositions();
    if (positions.size() == 0)
    {
        return;
    }

    Float minDistanceToPoint = std::numeric_limits<Float>::max();
    Float minDepth = std::numeric_limits<Float>::max();
    size_t minIndex = 0;
    Vector3 minRayClosestPoint(0.f, 0.f, 0.f);

    // Iterate all of them and find the closest one.
    // TODO: BVH tree
    for (size_t i = 0, n = positions.size(); i < n; ++i)
    {
        Vector3 position = Vector3{ transform * Vector4{ positions[i], 1.0 } };

        Vector3 currentClosest;
        Float currentDepth;

        raySegFindClosestPoint(origin, direction, position, &currentClosest, &currentDepth);

        Float distanceToPoint = screenSpaceDistance(position, currentClosest, projection, view, { 1.0f, 1.0f });

        if (i == 0 || distanceToPoint < minDistanceToPoint)
        {
            minDistanceToPoint = distanceToPoint;
            minDepth = currentDepth;
            minIndex = i;
            minRayClosestPoint = currentClosest;
        }
    }

    auto& lastGesturePayload = data.m_lastGesturePayload;
    Vector3 lastClosestPoint = lastGesturePayload->rayClosestPoint;
    Float lastDistance = lastGesturePayload->distanceToPoint;

    lastGesturePayload->itemClosestPoint = Vector3{ transform * Vector4{ positions[minIndex], 1.0 } };
    lastGesturePayload->rayClosestPoint = minRayClosestPoint;
    lastGesturePayload->rayDistance = minDepth;
    lastGesturePayload->distanceToPoint = minDistanceToPoint;
    lastGesturePayload->closestPoint = static_cast<uint32_t>(minIndex);

    lastGesturePayload->moved = lastGesturePayload->rayClosestPoint - lastClosestPoint;

    // Copy
    *stateGesturePayload.get() = *lastGesturePayload.get();
}

const Points::PointsGesturePayload* Points::getGesturePayload() const
{
    return _getData<PointsData>().m_lastGesturePayload.get();
}

const Points::PointsGesturePayload* Points::getGesturePayload(GestureState state) const
{
    return _getData<PointsData>().m_itersections[static_cast<uint32_t>(state)].get();
}

Float Points::getIntersectionDistance() const
{
    auto& data = _getData<PointsData>();
    if (data.m_intersectionSizeExplicitlyChanged)
    {
        return this->getIntersectionSize();
    }

    if (!data.m_lastGesturePayload || this->getSizes().size() < 1)
    {
        return AbstractShape::getIntersectionDistance();
    }
    else if (this->getSizes().size() == 1)
    {
        return std::max(AbstractShape::getIntersectionDistance(), this->getSizes()[0] * 0.5);
    }

    return std::max(AbstractShape::getIntersectionDistance(), this->getSizes()[data.m_lastGesturePayload->closestPoint] * 0.5);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
