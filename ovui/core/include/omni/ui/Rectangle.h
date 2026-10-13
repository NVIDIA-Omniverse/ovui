/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Shape.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct RectangleStyleSnapshot;

/**
 * @brief The Rectangle widget provides a colored rectangle to display.
 */
class OMNIUI_CLASS_API Rectangle : public Shape
{
    OMNIUI_OBJECT(Rectangle)

public:
    OMNIUI_API
    ~Rectangle() override;

protected:
    /**
     * @brief Constructs Rectangle
     */
    OMNIUI_API
    Rectangle();

    /**
     * @brief Reimplemented the rendering code of the widget.
     */
    OMNIUI_API
    void _drawShape(float elapsedTime, float x, float y, float width, float height) override;

    /**
     * @brief Reimplemented the draw shadow of the shape.
     */
    OMNIUI_API
    void _drawShadow(
        float elapsedTime,
        float x,
        float y,
        float width,
        float height,
        uint32_t shadowColor,
        float dpiScale,
        ImVec2 shadowOffset,
        float shadowThickness,
        uint32_t shadowFlag) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
