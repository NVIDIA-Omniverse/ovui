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
#include <omni/ui/scene/ScrollGesture.h>
#include <omni/ui/scene/GestureManager.h>

#include "ShapeGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct ScrollGesture::ScrollGestureData : public ShapeGesture::ShapeGestureData
{
    ~ScrollGestureData() override = default;

    Vector2 m_mouseWheel = { 0, 0 };
};

ScrollGesture::ScrollGesture(std::function<void(AbstractShape const*)> onEnded)
    : ShapeGesture(new ScrollGestureData)
{
    if (onEnded)
    {
        this->setOnEndedFn(std::move(onEnded));
    }
}

ScrollGesture::~ScrollGesture() = default;

void ScrollGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
    auto& data = _getData<ScrollGestureData>();
    switch (this->getState())
    {
    case GestureState::ePossible:
        // Begin only happens if the mouse cursor is close to the item
        // TODO: Use the actual resolution instead on 0.02
        if (const auto gesturePayload = this->getGesturePayload())
        {
            if ((data.m_input.mouseWheel.x != (Float)0.0 || data.m_input.mouseWheel.y != (Float)0.0))
            {
                GestureButtons mouseButtons(m_mouseButtons);
                const bool mouseMatch = mouseButtons.empty() ? (data.m_input.clicked == 0 && data.m_input.down == 0) :
                    (mouseButtons.checkMouseButtons(data.m_input.down) || mouseButtons.checkMouseButtons(data.m_input.clicked));

                if (mouseMatch && (m_modifiers == UINT32_MAX || m_modifiers == data.m_input.modifiers) &&
                    screenSpaceDistance(gesturePayload->itemClosestPoint, gesturePayload->rayClosestPoint, projection, view,
                        data.m_frameSize) <= this->getSender()->getIntersectionDistance())
                {
                    data.m_mouseWheel = data.m_input.mouseWheel;
                    this->setState(GestureState::eEnded);
                }
            }


        }
        break;

    default:
        data.m_mouseWheel = Vector2{ (Float)0.0 };
        this->setState(GestureState::ePossible);
        break;
    };
}

void ScrollGesture::process()
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

void ScrollGesture::onEnded()
{
}

Vector2 ScrollGesture::getScroll() const
{
    return _getData<ScrollGestureData>().m_mouseWheel;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
