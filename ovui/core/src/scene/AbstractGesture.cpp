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

#include <omni/ui/scene/AbstractGesture.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/GestureManager.h>

#include "AbstractGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

AbstractGesture::AbstractGestureData::~AbstractGestureData()
{
}

AbstractGesture::AbstractGesture(AbstractGestureData* dataPtr)
    : m_data(dataPtr ? dataPtr : new AbstractGestureData)
{
}

AbstractGesture::~AbstractGesture()
{
    auto& data = *m_data;
    if (data.m_manager)
    {
        data.m_manager->_loseGesture(this);
    }
    this->destroyCallbacks();
}

void AbstractGesture::setManager(const std::shared_ptr<GestureManager>& manager)
{
    auto& data = *m_data;
    if (data.m_manager)
    {
        data.m_manager->_loseGesture(this);
    }

    data.m_manager = manager;
    if (data.m_manager)
    {
        data.m_manager->_trackGesture(this);
    }
}

const std::shared_ptr<GestureManager>& AbstractGesture::getManager() const
{
    return m_data->m_manager;
}

void AbstractGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
}

void AbstractGesture::process()
{
}

void AbstractGesture::postProcess()
{
    m_data->m_stateChanged = false;
}

GestureState AbstractGesture::getPreviousState() const
{
    return m_data->m_previousState;
}

GestureState AbstractGesture::getState() const
{
    return m_data->m_state;
}

void AbstractGesture::setState(GestureState state)
{
    auto& data = *m_data;
    data.m_previousState = data.m_state;
    data.m_state = state;
    data.m_stateChanged = true;
}

bool AbstractGesture::isStateChanged() const
{
    return m_data->m_stateChanged;
}

void AbstractGesture::_setCanBePrevented(bool canBe)
{
    m_data->m_cachedCanBePrevented = canBe;
}

bool AbstractGesture::_getCanBePrevented() const
{
    return m_data->m_cachedCanBePrevented;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
