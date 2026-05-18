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
#include <omni/ui/scene/DoubleClickGesture.h>
#include <omni/ui/scene/GestureManager.h>

#include "ClickGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct DoubleClickGesture::DoubleClickGestureData : public ClickGesture::ClickGestureData
{
    ~DoubleClickGestureData() override = default;
};

DoubleClickGesture::DoubleClickGesture(std::function<void(AbstractShape const*)> onEnded)
    : ClickGesture(std::move(onEnded), new DoubleClickGestureData)
{
}

DoubleClickGesture::~DoubleClickGesture() = default;

void DoubleClickGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
    auto& data = _getData<DoubleClickGestureData>();
    switch (this->getState())
    {
    case GestureState::eBegan:
        if (const auto gesturePayload = this->getGesturePayload())
        {
            uint32_t mouseButtonsValue = getMouseButton();
            GestureButtons mouseButtons(mouseButtonsValue);

            if (gesturePayload->itemClosestPoint != data.m_itemLastPoint || gesturePayload->rayClosestPoint != data.m_rayLastPoint)
            {
                this->setState(GestureState::eCanceled);
            }
            else if (mouseButtons.checkMouseButtons(data.m_input.doubleClicked))
            {
                this->setState(GestureState::eEnded);
            }
            else if (mouseButtons.checkMouseButtons(data.m_input.released, true))
            {
                data.m_startedAt = std::chrono::steady_clock::now();
                data.m_readyForEnd = true;
            }
            else if (data.m_readyForEnd)
            {
                auto now = std::chrono::steady_clock::now();
                auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - data.m_startedAt).count();
                if (elapsed >= this->getManager()->getMaxWait())
                {
                    // If we don't have the second click after delay, it's canceled
                    this->setState(GestureState::eCanceled);
                }
            }
        }
        break;

    default:
        ClickGesture::clickPreProcess(projection, view, 2);
        break;
    };
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
