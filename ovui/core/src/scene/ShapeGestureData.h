/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/scene/ShapeGesture.h>

#include "AbstractGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct ShapeGesture::ShapeGestureData : public AbstractGestureData
{
    virtual ~ShapeGestureData();

    // Last mouse event.
    MouseInput m_input;

    // Last frame size
    Vector2 m_frameSize;

    AbstractShape* m_currentShape = nullptr;
    std::unordered_set<AbstractShape*> m_items;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
