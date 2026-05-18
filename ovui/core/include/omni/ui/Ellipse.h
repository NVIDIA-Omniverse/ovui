/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#include "Shape.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct EllipseStyleSnapshot;

/**
 * @brief The Ellipse widget provides a colored ellipse to display.
 */
class OMNIUI_CLASS_API Ellipse : public Shape
{
    OMNIUI_OBJECT(Ellipse)

public:
    OMNIUI_API
    ~Ellipse() override;

protected:
    /**
     * @brief Constructs Ellipse
     */
    OMNIUI_API
    Ellipse();

    /**
     * @brief Reimplemented the rendering code of the shape.
     *
     * @see Widget::_drawContent
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

private:
    // this need to become a property, stylable ?
    int32_t m_numSegments = 40;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
