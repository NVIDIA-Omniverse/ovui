/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"
#include "Math.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class DrawBuffer;

/**
 * @brief The InvisibleButton widget provides a transparent command button.
 */
class OMNIUI_SCENE_CLASS_API AbstractDrawSystem
{
public:
    OMNIUI_SCENE_API
    virtual ~AbstractDrawSystem();

    virtual void setup() = 0;
    virtual void beginFrame() = 0;
    virtual void render(const DrawBuffer* const* buffers,
                        size_t bufferCount,
                        const Matrix44& projection,
                        const Matrix44& view,
                        float width,
                        float height,
                        float dpiScale) = 0;
    virtual void endFrame() = 0;
    virtual void destroy() = 0;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
