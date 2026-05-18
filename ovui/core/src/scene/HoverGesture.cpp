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

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/HoverGesture.h>

#include "ShapeGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct HoverGesture::HoverGestureData : public ShapeGesture::ShapeGestureData
{
    ~HoverGestureData() override = default;

    Vector3 m_itemLastPoint = Vector3{ 0.0 };
    Vector3 m_rayLastPoint = Vector3{ 0.0 };

    // We need it because the gesture is triggered with a delay.
    std::chrono::steady_clock::time_point m_startedAt;

    // Flag that indicates the state when the gesture is about to ended.
    bool m_readyForEnd = false;
};

/**
 * @brief HoverGesture is a special case gesture, it can't interact with
 * Clicked/Dragged etc and it doesn't prevent anything. So by default it's using
 * a special gesture manager.
 */
class HoverGestureManager : public GestureManager
{
public:
    bool canBePrevented(AbstractGesture* gesture) const override
    {
        return false;
    }

    bool shouldPrevent(AbstractGesture* gesture, const AbstractGesture* gesturePreventer) const override
    {
        return false;
    }
};

class HoverGestureManagerAlternative : public GestureManager
{
public:
    bool canBePrevented(AbstractGesture* gesture) const override
    {
        return true;
    }

    bool shouldPrevent(AbstractGesture* gesture, const AbstractGesture* gesturePreventer) const override
    {
        auto hoverGesture = dynamic_cast<HoverGesture*>(gesture);
        if (hoverGesture)
        {
            const auto hoverGesturePreventer = dynamic_cast<const HoverGesture*>(gesturePreventer);
            if (hoverGesturePreventer)
            {
                auto statePreventer = gesturePreventer->getState();
                bool shouldPrevent = statePreventer == GestureState::eBegan ||
                                     statePreventer == GestureState::eChanged || statePreventer == GestureState::eEnded;
                if (shouldPrevent)
                {
                    shouldPrevent =
                        gesturePreventer->getGesturePayload()->rayDistance <= gesture->getGesturePayload()->rayDistance;
                }

                return shouldPrevent;
            }
            else
            {
                return true;
            }
        }

        return GestureManager::shouldPrevent(gesture, gesturePreventer);
    }
};

HoverGesture::HoverGesture(std::function<void(AbstractShape const*)> onEnded)
    : ShapeGesture(new HoverGestureData)
{
    this->setManager(std::make_shared<HoverGestureManager>());

    if (onEnded)
    {
        this->setOnEndedFn(std::move(onEnded));
    }
}

HoverGesture::~HoverGesture() = default;

void HoverGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
    auto& data = _getData<HoverGestureData>();
    switch (this->getState())
    {
    case GestureState::ePossible:
        // Begin only happens if the mouse cursor is close to the item
        // TODO: Use the actual resolution instead on 0.02
        if (const auto gesturePayload = this->getGesturePayload())
        {
            if ((m_modifiers == UINT32_MAX || m_modifiers == data.m_input.modifiers) &&
                screenSpaceDistance(gesturePayload->itemClosestPoint, gesturePayload->rayClosestPoint, projection, view,
                                    data.m_frameSize) <= this->getSender()->getIntersectionDistance())
            {
                data.m_itemLastPoint = gesturePayload->itemClosestPoint;
                data.m_rayLastPoint = gesturePayload->rayClosestPoint;
                data.m_readyForEnd = false;
                this->setState(GestureState::eBegan);
            }
        }
        break;

    case GestureState::eBegan:
    case GestureState::eChanged:
        if (const auto gesturePayload = this->getGesturePayload())
        {
            if ((m_modifiers == UINT32_MAX || m_modifiers == data.m_input.modifiers) &&
                screenSpaceDistance(gesturePayload->itemClosestPoint, gesturePayload->rayClosestPoint, projection, view,
                                    data.m_frameSize) <= this->getSender()->getIntersectionDistance())
            {
                if (data.m_itemLastPoint != gesturePayload->itemClosestPoint ||
                    data.m_rayLastPoint != gesturePayload->rayClosestPoint || this->getState() == GestureState::eBegan)
                {
                    // Regarding GestureState::eBegan: It should immediatley
                    // switch to changed otherwise it's possible that it's
                    // "began" several frames.
                    data.m_itemLastPoint = gesturePayload->itemClosestPoint;
                    data.m_rayLastPoint = gesturePayload->rayClosestPoint;
                    this->setState(GestureState::eChanged);
                }
            }
            else
            {
                this->setState(GestureState::eEnded);
            }
        }
        break;

    default:
        this->setState(GestureState::ePossible);
        break;
    };
}

void HoverGesture::process()
{
    switch (this->getState())
    {
    case GestureState::eBegan:
        if (this->hasOnBeganFn())
        {
            this->callOnBeganFn(this->getSender());
        }
        else
        {
            this->onBegan();
        }
        break;

    case GestureState::eChanged:
        if (this->hasOnChangedFn())
        {
            this->callOnChangedFn(this->getSender());
        }
        else
        {
            this->onChanged();
        }
        break;

    case GestureState::ePrevented:
    case GestureState::eCanceled:
        // Make sure we terminate Began state
        if (this->getPreviousState() != GestureState::eBegan && this->getPreviousState() != GestureState::eChanged)
        {
            break;
        }

    case GestureState::eEnded:
        if (this->hasOnEndedFn())
        {
            this->callOnEndedFn(this->getSender());
        }
        else
        {
            this->onEnded();
        }
        break;

    default:
        break;
    };
}

void HoverGesture::onBegan()
{
}

void HoverGesture::onChanged()
{
}

void HoverGesture::onEnded()
{
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
