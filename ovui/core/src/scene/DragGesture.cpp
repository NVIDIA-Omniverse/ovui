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
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/GestureManager.h>

#include "ShapeGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct DragGesture::DragGestureData : public ShapeGesture::ShapeGestureData
{
    Vector3 m_itemLastPoint = Vector3{ 0.0 };
    Vector3 m_rayLastPoint = Vector3{ 0.0 };
    Vector2 m_mouseLast = Vector3{ 0.0 };
};

DragGesture::DragGesture()
    : ShapeGesture(new DragGestureData)
{
}

DragGesture::~DragGesture() = default;

void DragGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
    GestureButtonEditor mouseButtons(m_mouseButtons);

    auto& data = _getData<DragGestureData>();
    const auto gestureState = this->getState();
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
                    this->setState(GestureState::eChanged);
                }
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
