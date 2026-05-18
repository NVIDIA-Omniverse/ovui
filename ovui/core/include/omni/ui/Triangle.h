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

#include "Alignment.h"
#include "Shape.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct TriangleStyleSnapshot;

/**
 * @brief The Triangle widget provides a colored triangle to display.
 */
class OMNIUI_CLASS_API Triangle : public Shape
{
    OMNIUI_OBJECT(Triangle)

public:
    OMNIUI_API
    ~Triangle() override;

    /**
     * @brief This property holds the alignment of the triangle when the fill policy is ePreserveAspectFit or
     * ePreserveAspectCrop.
     * By default, the triangle is centered.
     */
    OMNIUI_PROPERTY(Alignment, alignment, DEFAULT, Alignment::eRightCenter, READ, getAlignment, WRITE, setAlignment);

protected:
    /**
     * @brief Constructs Triangle
     */
    OMNIUI_API
    Triangle();

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
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
