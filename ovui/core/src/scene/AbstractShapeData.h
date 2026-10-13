/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/scene/AbstractShape.h>


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct AbstractShape::AbstractShapeData
{
    AbstractShapeData();
    virtual ~AbstractShapeData();

    std::vector<std::shared_ptr<ShapeGesture>> m_gestures;

    bool m_gesturePayloadCached = false;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
