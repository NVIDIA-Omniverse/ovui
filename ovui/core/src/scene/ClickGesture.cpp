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

#include <omni/ui/platform/IUiSettings.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/ClickGesture.h>
#include <omni/ui/scene/GestureManager.h>

#include "ShapeGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct ClickGesture::ClickGestureData : public ShapeGesture::ShapeGestureData
{
    ~ClickGestureData() override = default;

    Vector3 m_itemLastPoint = Vector3{ 0.0 };
    Vector3 m_rayLastPoint = Vector3{ 0.0 };

    // We need it because the gesture is triggered with a delay.
    std::chrono::steady_clock::time_point m_startedAt;

    // Flag that indicates the state when the gesture is about to ended.
    bool m_readyForEnd = false;
};

ClickGesture::ClickGesture(std::function<void(AbstractShape const*)> onEnded,
                           ClickGestureData* dataPtr)
    : ShapeGesture(dataPtr ? dataPtr : new ClickGestureData)
{
    if (onEnded)
    {
        this->setOnEndedFn(std::move(onEnded));
    }
}

ClickGesture::~ClickGesture() = default;

void ClickGesture::setState(GestureState state)
{
    if (state == GestureState::eEnded || state == GestureState::eCanceled)
    {
        this->getManager()->setMaxWait(0, true);
    }
    AbstractGesture::setState(state);
}


void ClickGesture::clickPreProcess(const Matrix44& projection, const Matrix44& view, uint32_t nClicks)
{
    auto& data = _getData<ClickGestureData>();
    const GestureButtons mouseButtons(m_mouseButtons);

    switch (this->getState())
    {
    case GestureState::ePossible:
        // Begin only happens if the mouse cursor is close to the item
        // TODO: Use the actual resolution instead on 0.02
        if (const auto gesturePayload = this->getGesturePayload())
        {
            if (mouseButtons.checkMouseButtons(data.m_input.clicked) &&
                (m_modifiers == UINT32_MAX || m_modifiers == data.m_input.modifiers) &&
                screenSpaceDistance(gesturePayload->itemClosestPoint, gesturePayload->rayClosestPoint, projection, view,
                                    data.m_frameSize) <= this->getSender()->getIntersectionDistance())
            {
                data.m_itemLastPoint = gesturePayload->itemClosestPoint;
                data.m_rayLastPoint = gesturePayload->rayClosestPoint;
                data.m_readyForEnd = false;
                this->setState(GestureState::eBegan);

                int64_t maxWaitInt = 0;
                auto* settings = PlatformRegistry::instance().settings();
                // Choose wait based on number of clicks that the gesture is triggered by
                if (nClicks <= 1)
                {
                    maxWaitInt = settings ? settings->getInt("/exts/omni.ui/clickGesture/singleClickWait", 10) : 10;
                }
                else
                {
                    maxWaitInt = settings ? settings->getInt("/exts/omni.ui/clickGesture/multiClickWait", 100) : 100;
                }
                // If maxWaitInt is less than or zero, default to 10 / 100
                this->getManager()->setMaxWait(static_cast<uint32_t>(maxWaitInt));
            }
        }
        break;

    case GestureState::eBegan:
        if (const auto gesturePayload = this->getGesturePayload())
        {
            if (!data.m_readyForEnd)
            {
                if (gesturePayload->itemClosestPoint != data.m_itemLastPoint ||
                    gesturePayload->rayClosestPoint != data.m_rayLastPoint)
                {
                    this->setState(GestureState::eCanceled);
                }
                else if (mouseButtons.checkMouseButtons(data.m_input.released, true))
                {
                    data.m_startedAt = std::chrono::steady_clock::now();
                    data.m_readyForEnd = true;
                }
            }
            else
            {
                if (mouseButtons.checkMouseButtons(data.m_input.doubleClicked))
                {
                    // Filter out double clicks
                    this->setState(GestureState::eCanceled);
                }
                else if (mouseButtons.checkMouseButtons(data.m_input.clicked))
                {
                    // Restart this gesture
                    this->setState(GestureState::ePossible);
                    this->preProcess(projection, view);
                }
                else
                {
                    auto now = std::chrono::steady_clock::now();
                    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - data.m_startedAt).count();
                    if (elapsed >= this->getManager()->getMaxWait())
                    {
                        // We need this delay to be able to finish double click if it exists.
                        this->setState(GestureState::eEnded);
                    }
                }
            }
        }
        break;

    default:
        this->setState(GestureState::ePossible);
        break;
    };
}

void ClickGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
    return clickPreProcess(projection, view, 1);
}

void ClickGesture::process()
{
    switch (this->getState())
    {
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

void ClickGesture::onEnded()
{
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
