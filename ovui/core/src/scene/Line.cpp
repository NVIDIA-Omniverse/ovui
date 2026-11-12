/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/platform/Assert.h>

#include <omni/ui/Profile.h>

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Line.h>
#include <omni/ui/scene/Math.h>

#include "AbstractShapeData.h"
#include "DragFollow.h"

#include <utility>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

struct Line::LineData : public AbstractShape::AbstractShapeData
{
    ~LineData() override = default;

    LineGesturePayload m_lastGesturePayload;
    std::array<std::unique_ptr<LineGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;

    bool m_intersectionThicknessExplicitlyChanged = false;
};

Line::Line(const Vector3& start, const Vector3& end)
    : AbstractShape(new LineData)
{
    this->_setChangedFn();
    this->_setIntersectionThicknessChangedFn([this](const auto&) {
        _getData<LineData>().m_intersectionThicknessExplicitlyChanged = true;
    });

    this->setStart(start);
    this->setEnd(end);
}

Line::Line()
    : Line({ 0, 0, 0 }, { 0, 0, 1 })
{
}

// The ends are written by hand, not by the property macro, so that a gesture that is running its callback is told what an
// end was and what it is (see DragGesture).
void Line::setStart(Vector3 const& value)
{
    if (checkIfEqual(m_start, value))
    {
        return;
    }
    DragFollow::Write write(this);
    write.noteLineEnd(this, true, m_start, value);
    m_start = value;
    m__setStartChangedFnCallbacks(value);
}

void Line::setEnd(Vector3 const& value)
{
    if (checkIfEqual(m_end, value))
    {
        return;
    }
    DragFollow::Write write(this);
    write.noteLineEnd(this, false, m_end, value);
    m_end = value;
    m__setEndChangedFnCallbacks(value);
}

void Line::_setChangedFn()
{
    this->_setStartChangedFn(std::bind(&This::_dirty, this));
    this->_setEndChangedFn(std::bind(&This::_dirty, this));
    this->_setColorChangedFn(std::bind(&This::_dirtyAppearance, this));
    this->_setThicknessChangedFn(std::bind(&This::_dirtyAppearance, this));
}

Line::~Line() = default;

void Line::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        drawList->addLine(this->getStart(), this->getEnd(), this->getColor(), this->getThickness());
    }
}

void Line::_dirty()
{
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void Line::intersect(const Vector3 origin,
                     const Vector3 direction,
                     const Vector2 mouse,
                     const Matrix44& projection,
                     const Matrix44& view,
                     GestureState state)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& data = _getData<LineData>();
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<LineGesturePayload>();
    }

    auto& gesturePayload = data.m_lastGesturePayload;
    auto transform = this->getParent()->getAccumulatedTransform();
    Vector4 start = transform * Vector4{ this->getStart(), 1.0 };
    Vector4 end = transform * Vector4{ this->getEnd(), 1.0 };
    const bool held = std::exchange(data.m_baselineHeld, false);
    Vector3 lastClosestPoint = held ? data.m_baselinePoint : gesturePayload.lineClosestPoint;
    Float lastDistance = held ? data.m_baselineA : gesturePayload.lineDistance;

    // Get two points, one on the line, another on the ray
    raySegFindClosestPoints(origin, direction, { start.x, start.y, start.z }, { end.x, end.y, end.z },
                            &gesturePayload.rayClosestPoint, &gesturePayload.itemClosestPoint,
                            &gesturePayload.rayDistance, &gesturePayload.lineDistance);

    // lineClosestPoint is not limited with [0,1] of the line
    // TODO: it can be simpler
    lineLineFindClosestPoints(origin, origin + direction, { start.x, start.y, start.z }, { end.x, end.y, end.z },
                              nullptr, &gesturePayload.lineClosestPoint, nullptr, nullptr);

    gesturePayload.moved = gesturePayload.lineClosestPoint - lastClosestPoint;

    // Copy
    *stateGesturePayload = gesturePayload;
}

bool Line::_getFollowReport(Vector3& moved) const
{
    const auto& payload = _getData<LineData>().m_lastGesturePayload;
    moved = payload.moved;
    return true;
}

void Line::_captureBaseline() const
{
    auto& data = _getData<LineData>();
    data.m_baselinePoint = data.m_lastGesturePayload.lineClosestPoint;
    data.m_baselineA = data.m_lastGesturePayload.lineDistance;
}

const Line::LineGesturePayload* Line::getGesturePayload() const
{
    auto& data = _getData<LineData>();
    return &data.m_lastGesturePayload;
}

const Line::LineGesturePayload* Line::getGesturePayload(GestureState state) const
{
    auto& data = _getData<LineData>();
    return data.m_itersections[static_cast<uint32_t>(state)].get();
}

Float Line::getIntersectionDistance() const
{
    auto& data = _getData<LineData>();
    if (data.m_intersectionThicknessExplicitlyChanged)
    {
        return this->getIntersectionThickness();
    }

    return std::max(AbstractShape::getIntersectionDistance(), this->getThickness() * 0.5);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
