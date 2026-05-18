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
#include <omni/ui/scene/Scene.h>
#include <omni/ui/scene/ShapeGesture.h>

#include "AbstractShapeData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

AbstractShape::AbstractShapeData::AbstractShapeData()
{
}

AbstractShape::AbstractShapeData::~AbstractShapeData()
{
}

AbstractShape::AbstractShape(AbstractShapeData* dataPtr)
    : m_data(dataPtr ? dataPtr : new AbstractShapeData)
{
}

AbstractShape::~AbstractShape()
{
    this->destroy();
}

void AbstractShape::destroy()
{
    for (auto& gesture : getGestures())
    {
        if (gesture)
        {
            gesture->_dischargeItem(this);
        }
    }
    m_data->m_gestures.clear();

    AbstractItem::destroy();
}

void AbstractShape::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    m_data->m_gesturePayloadCached = false;
}

const std::vector<std::shared_ptr<ShapeGesture>>& AbstractShape::getGestures() const
{
    return m_data->m_gestures;
}

void AbstractShape::setGestures(std::vector<std::shared_ptr<ShapeGesture>> gestures)
{
    for (auto& gesture : getGestures())
    {
        if (gesture)
        {
            gesture->_dischargeItem(this);
        }
    }

    m_data->m_gestures = std::move(gestures);

    for (auto& gesture : getGestures())
    {
        if (gesture)
        {
            gesture->_assignItem(this);

            if (!gesture->getManager() && this->_getScene())
            {
                gesture->setManager(this->_getScene()->getDefaultGestureManager());
            }
        }
    }
}

void AbstractShape::addGesture(std::shared_ptr<ShapeGesture> gesture)
{
    if (!gesture)
    {
        return;
    }

    gesture->_assignItem(this);

    if (!gesture->getManager() && this->_getScene())
    {
        gesture->setManager(this->_getScene()->getDefaultGestureManager());
    }

    m_data->m_gestures.emplace_back(gesture);
}

Float AbstractShape::getIntersectionDistance() const
{
    return 1.0;
}

void AbstractShape::_collectManagers(std::unordered_set<GestureManager*>& managers) const
{
    for (auto& gesture : getGestures())
    {
        if (gesture)
        {
            managers.insert(gesture->getManager().get());
        }
    }
}

void AbstractShape::_cacheGesturePayload(const Vector3 origin,
                                         const Vector3 direction,
                                         const Vector2 mouse,
                                         const Matrix44& projection,
                                         const Matrix44& view,
                                         GestureState state)
{
    // Call only once a frame
    if (!m_data->m_gesturePayloadCached)
    {
        m_data->m_gesturePayloadCached = true;
        this->intersect(origin, direction, mouse, projection, view, state);
    }
}


void AbstractShape::_setParent(const AbstractContainer* const& parent)
{
    AbstractItem::_setParent(parent);
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
