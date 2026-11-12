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

    // After a frame that DragGesture did not report, the next intersection measures ``moved`` and the other ``moved_*``
    // values from these values (the payload of the last call), not from the payload of the previous frame, and clears
    // the flag.
    bool m_baselineHeld = false;
    Vector3 m_baselinePoint = Vector3{ 0.0 };
    Float m_baselineA = 0.0;
    Float m_baselineB = 0.0;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
