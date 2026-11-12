/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/GestureManager.h>

#include "DragFollow.h"
#include "ShapeGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct DragGesture::DragGestureData : public ShapeGesture::ShapeGestureData
{
    Vector3 m_itemLastPoint = Vector3{ 0.0 };
    Vector3 m_rayLastPoint = Vector3{ 0.0 };
    Vector2 m_mouseLast = Vector3{ 0.0 };

    // What the callbacks of the drag wrote: see DragFollow. A callback can destroy the gesture, so the window keeps it alive.
    std::shared_ptr<DragFollow::Tracker> m_follow = std::make_shared<DragFollow::Tracker>();
};

namespace
{
DragFollow::Report getReport(const AbstractShape* shape)
{
    DragFollow::Report report;
    report.valid = shape && shape->_getFollowReport(report.moved);
    return report;
}

// Runs a callback of the gesture as a window of the tracker, also when the callback throws.
class FollowWindow
{
public:
    FollowWindow(std::shared_ptr<DragFollow::Tracker> tracker, const AbstractShape* sender, bool callback)
        : m_tracker(std::move(tracker))
    {
        m_tracker->enter(sender, getReport(sender), callback);
    }

    ~FollowWindow()
    {
        m_tracker->leave();
    }

    FollowWindow(const FollowWindow&) = delete;
    FollowWindow& operator=(const FollowWindow&) = delete;

private:
    std::shared_ptr<DragFollow::Tracker> m_tracker;
};
} // namespace

DragGesture::DragGesture()
    : ShapeGesture(new DragGestureData)
{
}

DragGesture::~DragGesture() = default;

void DragGesture::beginFollowing()
{
    _getData<DragGestureData>().m_follow->enterDeclared();
}

void DragGesture::endFollowing()
{
    _getData<DragGestureData>().m_follow->leaveDeclared();
}

void DragGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
    GestureButtonEditor mouseButtons(m_mouseButtons);

    auto& data = _getData<DragGestureData>();
    const auto gestureState = this->getState();

    // The pointer and the camera of this frame.
    auto getPointer = [&]() {
        DragFollow::Pointer pointer;
        pointer.mouse = data.m_input.mouse;
        pointer.origin = data.m_input.mouseOrigin;
        pointer.direction = data.m_input.mouseDirection;
        pointer.projection = projection;
        pointer.view = view;
        pointer.frameSize = data.m_frameSize;
        return pointer;
    };
    switch (gestureState)
    {
    case GestureState::ePossible:
        // Begin only happens if the mouse cursor is close to the item
        // TODO: Use the actual resolution instead on 0.02
        if (const auto gesturePayload = this->getGesturePayload())
        {
            bool isInteresting = false;
            if (data.m_input.clicked)
            {
                if (mouseButtons.isMultiButton())
                {
                    bool allClicked = mouseButtons.checkMouseButtons(data.m_input.clicked);
                    isInteresting = allClicked || mouseButtons.checkMouseButtons(data.m_input.down);
                    const bool readyToStartDrag = allClicked || (isInteresting && mouseButtons.getStateBit());
                    if (!readyToStartDrag)
                    {
                        mouseButtons.setStateBit(true);
                        isInteresting = false;
                        return;
                    }
                }
                else
                {
                    isInteresting = mouseButtons.checkMouseButtons(data.m_input.clicked) && mouseButtons.checkMouseButtons(data.m_input.down);
                }
            }
            else if (data.m_input.down && mouseButtons.isMultiButton() && mouseButtons.checkAnyMouseButtons(data.m_input.down) && mouseButtons.getStateBit())
            {
                return;
            }

            if (isInteresting && (m_modifiers == UINT32_MAX || m_modifiers == data.m_input.modifiers) &&
                screenSpaceDistance(gesturePayload->itemClosestPoint, gesturePayload->rayClosestPoint, projection, view,
                                    data.m_frameSize) <= this->getSender()->getIntersectionDistance())
            {
                data.m_itemLastPoint = gesturePayload->itemClosestPoint;
                data.m_rayLastPoint = gesturePayload->rayClosestPoint;
                data.m_mouseLast = data.m_input.mouse;
                mouseButtons.setStateBit(false);
                // The first call is measured from the payload of this frame.
                const AbstractShape* sender = this->getSender();
                data.m_follow->reset();
                data.m_follow->setPointer(getPointer());
                sender->_captureBaseline();
                this->setState(GestureState::eBegan);
                return;
            }
        }
        break;

    case GestureState::eBegan:
    case GestureState::eChanged: {
        bool wasReleased = mouseButtons.checkMouseButtons(data.m_input.released, true);
        bool isInteresting = wasReleased ? false : mouseButtons.checkMouseButtons(data.m_input.down);
        if (isInteresting && data.m_input.clicked && !mouseButtons.checkMouseButtons(data.m_input.clicked))
        {
            isInteresting = false;
            wasReleased = false;
        }
        if (const auto gesturePayload = isInteresting ? this->getGesturePayload() : nullptr)
        {
            // Once began, changed happens no matter the distance to the item
            if (gesturePayload->itemClosestPoint != data.m_itemLastPoint || gesturePayload->rayClosestPoint != data.m_rayLastPoint)
            {
                if (!this->isCheckMouseMoved() || data.m_mouseLast != data.m_input.mouse)
                {
                    data.m_itemLastPoint = gesturePayload->itemClosestPoint;
                    data.m_rayLastPoint = gesturePayload->rayClosestPoint;
                    data.m_mouseLast = data.m_input.mouse;
                    const AbstractShape* sender = this->getSender();
                    const auto pointer = getPointer();
                    if (data.m_follow->isFollow(sender, pointer))
                    {
                        // Under the same pointer and camera, the shape changed only by what the callback of the last call
                        // wrote: this is the movement that was already reported. Its own movement stays in the next call.
                        data.m_follow->setBaselinePending(true);
                    }
                    else
                    {
                        data.m_follow->setPointer(pointer);
                        data.m_follow->setBaselinePending(false);
                        sender->_captureBaseline();
                        this->setState(GestureState::eChanged);
                    }
                }
            }
            if (data.m_follow->isBaselinePending())
            {
                this->getSender()->_holdPayloadBaseline();
            }
        }
        else
        {
            // eBegan -> eCanceled; eChanged -> eEnded
            this->setState(gestureState == GestureState::eChanged && wasReleased ? GestureState::eEnded : GestureState::eCanceled);
        }
        break;
    }

    default:
        this->setState(GestureState::ePossible);
        break;
    };

    mouseButtons.setStateBit(false);
}

void DragGesture::process()
{
    switch (this->getState())
    {
    case GestureState::eBegan: {
        FollowWindow window(_getData<DragGestureData>().m_follow, this->getSender(), true);
        if (this->hasOnBeganFn())
        {
            this->callOnBeganFn(this->getSender());
        }
        else
        {
            this->onBegan();
        }
        break;
    }

    case GestureState::eChanged: {
        auto follow = _getData<DragGestureData>().m_follow;
        FollowWindow window(follow, this->getSender(), true);
        if (this->hasOnChangedFn())
        {
            this->callOnChangedFn(this->getSender());
        }
        else
        {
            this->onChanged();
        }
        break;
    }

    case GestureState::ePrevented:
    case GestureState::eCanceled:
        // Make sure we terminate Began state
        if (this->getPreviousState() != GestureState::eBegan && this->getPreviousState() != GestureState::eChanged)
        {
            break;
        }

    case GestureState::eEnded: {
        // The callback can destroy the gesture and the shape: what is used after it is kept alive here.
        auto follow = _getData<DragGestureData>().m_follow;
        const AbstractShape* sender = this->getSender();
        const std::shared_ptr<const AbstractItem> keepSender = sender ? sender->weak_from_this().lock() : nullptr;
        if (this->hasOnEndedFn())
        {
            this->callOnEndedFn(sender);
        }
        else
        {
            this->onEnded();
        }
        follow->reset();
        if (keepSender)
        {
            // A frame that was held back must not leave its baseline for the next drag.
            sender->_holdPayloadBaseline(false);
        }
        break;
    }

    default:
        break;
    };
}

void DragGesture::onBegan()
{
}

void DragGesture::onChanged()
{
}

void DragGesture::onEnded()
{
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
