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

#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/ShapeGesture.h>

#include "ShapeGestureData.h"

#include <limits>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

ShapeGesture::ShapeGestureData::~ShapeGestureData()
{
}

ShapeGesture::ShapeGesture(ShapeGestureData* dataPtr)
    : AbstractGesture(dataPtr ? dataPtr : new ShapeGestureData)
{
}

ShapeGesture::~ShapeGesture() = default;

void ShapeGesture::dispatchInput(const MouseInput& input,
                                 const Matrix44& projection,
                                 const Matrix44& view,
                                 const Vector2& frameSize)
{
    auto& data = _getData<ShapeGestureData>();
    data.m_input = input;
    data.m_frameSize = frameSize;

    if (data.m_currentShape && data.m_currentShape->computeVisibility())
    {
        if (this->getState() == GestureState::eBegan || this->getState() == GestureState::eChanged)
        {
            // Early exit, we don't switch the shape in the middle of the gesture.
            data.m_currentShape->_cacheGesturePayload(
                input.mouseOrigin, input.mouseDirection, input.mouse, projection, view, this->getState());
            return;
        }
    }

    // TODO: Check the depth
    Float minDistance = std::numeric_limits<Float>::max();
    AbstractShape* closestShape = nullptr;
    bool first = true;

    // Do the gesturePayload and pick the closest shape
    for (auto* item : data.m_items)
    {
        if (!item->computeVisibility())
        {
            continue;
        }

        item->_cacheGesturePayload(
            input.mouseOrigin, input.mouseDirection, input.mouse, projection, view, this->getState());
        const auto* gesturePayload = item->getGesturePayload();
        if (!gesturePayload || gesturePayload->rayDistance == 0.0)
        {
            continue;
        }

        Float s = screenSpaceDistance(
            gesturePayload->itemClosestPoint, gesturePayload->rayClosestPoint, projection, view, data.m_frameSize);

        if (first || s < minDistance)
        {
            minDistance = s;
            closestShape = item;
            first = false;
        }
    }

    data.m_currentShape = closestShape;
}

const AbstractShape* ShapeGesture::getSender() const
{
    auto& data = _getData<ShapeGestureData>();
    return data.m_currentShape;
}

const AbstractGesture::GesturePayload* ShapeGesture::getGesturePayload() const
{
    auto sender = this->getSender();
    return sender ? sender->getGesturePayload() : nullptr;
}

const AbstractGesture::GesturePayload* ShapeGesture::getGesturePayload(GestureState state) const
{
    auto sender = this->getSender();
    return sender ? sender->getGesturePayload(state) : nullptr;
}

const MouseInput& ShapeGesture::getRawInput() const
{
    auto& data = _getData<ShapeGestureData>();
    return data.m_input;
}

void ShapeGesture::_assignItem(AbstractShape* item)
{
    auto& data = _getData<ShapeGestureData>();
    data.m_items.insert(item);
}

void ShapeGesture::_dischargeItem(AbstractShape* item)
{
    auto& data = _getData<ShapeGestureData>();
    if (item == data.m_currentShape)
    {
        data.m_currentShape = nullptr;
    }

    data.m_items.erase(item);
}

const MouseInput& ShapeGesture::_getInput() const
{
    return _getData<ShapeGestureData>().m_input;
}

Vector2 ShapeGesture::_getFrameSize() const
{
    return _getData<ShapeGestureData>().m_frameSize;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
