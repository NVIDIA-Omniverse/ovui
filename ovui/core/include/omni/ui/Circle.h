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

struct CircleStyleSnapshot;

/**
 * @brief The Circle widget provides a colored circle to display.
 */
class OMNIUI_CLASS_API Circle : public Shape
{
    OMNIUI_OBJECT(Circle)

public:
    // TODO: this need to be moved to be a Header like Alignment
    enum class SizePolicy : uint8_t
    {
        eStretch = 0,
        eFixed
    };

    OMNIUI_API
    ~Circle() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     * when the circle is in fixed mode it can't be smaller than the radius
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * when the circle is in fixed mode it can't be smaller than the radius
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief This property holds the radius of the circle when the fill policy is eFixed or
     * eFixedCrop.
     * By default, the circle radius is 0.
     */
    OMNIUI_PROPERTY(float, radius, DEFAULT, 0, READ, getRadius, WRITE, setRadius, NOTIFY, setRadiusChangeFn);

    /**
     * @brief This property holds the alignment of the circle when the fill policy is ePreserveAspectFit or
     * ePreserveAspectCrop.
     * By default, the circle is centered.
     */
    OMNIUI_PROPERTY(Alignment, alignment, DEFAULT, Alignment::eCenter, READ, getAlignment, WRITE, setAlignment);

    /**
     * @brief This property is the way to draw a half or a quarter of the circle. When it's eLeft, only left side of the
     * circle is rendered. When it's eLeftTop, only left top quarter is rendered.
     */
    OMNIUI_PROPERTY(Alignment, arc, DEFAULT, Alignment::eCenter, READ, getArc, WRITE, setArc);

    /**
     * @brief Define what happens when the source image has a different size than the item.
     */
    OMNIUI_PROPERTY(SizePolicy,
                    sizePolicy,
                    DEFAULT,
                    SizePolicy::eStretch,
                    READ,
                    getSizePolicy,
                    WRITE,
                    setSizePolicy,
                    NOTIFY,
                    setSizePolicyChangedFn);

    /**
     * @brief This property holds the number of segments the circle will be drawn with (tesselation)
     * By default, the circle is 40 segments.
     */
    OMNIUI_PROPERTY(int, segments, DEFAULT, 40, READ, getSegments, WRITE, setSegments);

protected:
    /**
     * @brief Constructs Circle
     */
    OMNIUI_API
    Circle();

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
    void _calCentreAndRadius(float width, float height, float dpiScale, ImVec2& center, float& radius);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
