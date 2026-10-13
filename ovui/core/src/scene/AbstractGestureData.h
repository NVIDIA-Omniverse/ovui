/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once
#include <omni/ui/scene/AbstractGesture.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct AbstractGesture::AbstractGestureData
{
    virtual ~AbstractGestureData();

    std::shared_ptr<GestureManager> m_manager = nullptr;

    GestureState m_previousState = GestureState::eNone;
    GestureState m_state = GestureState::eNone;
    bool m_stateChanged = false;
    bool m_cachedCanBePrevented = false;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
