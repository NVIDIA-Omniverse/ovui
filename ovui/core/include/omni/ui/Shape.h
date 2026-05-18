/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <imgui/imgui.h>

#include "StyleProperties.h"
#include "Frame.h"
#include "Widget.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct ShapeStyleSnapshot;

/**
 * @brief The Shape widget provides a base class for all the Shape Widget
 * currently implemented are Rectangle, Circle, Triangle, Line
 * TODO: those need to have a special draw override to deal with intersection better
 */
class OMNIUI_CLASS_API Shape : public Widget
{
    OMNIUI_OBJECT_ABSTRACT(Shape)

public:
    OMNIUI_API
    ~Shape() override;

    /**
     * @brief Determines which style entry the shape should use for the background. It's very useful when we need to use
     * a custom color. For example, when we draw the triangle for a collapsable frame, we use "color" instead of
     * "background_color".
     */
    OMNIUI_PROPERTY(StyleColorProperty,
                    backgroundColorProperty,
                    DEFAULT,
                    StyleColorProperty::eBackgroundColor,
                    READ,
                    getBackgroundColorProperty,
                    WRITE,
                    setBackgroundColorProperty);

    /**
     * @brief Determines which style entry the shape should use for the border color.
     */
    OMNIUI_PROPERTY(StyleColorProperty,
                    borderColorProperty,
                    DEFAULT,
                    StyleColorProperty::eBorderColor,
                    READ,
                    getBorderColorProperty,
                    WRITE,
                    setBorderColorProperty);

    /**
     * @brief Determines which style entry the shape should use for the shadow color.
     */
    OMNIUI_PROPERTY(StyleColorProperty,
                    shadowColorProperty,
                    DEFAULT,
                    StyleColorProperty::eShadowColor,
                    READ,
                    getShadowColorProperty,
                    WRITE,
                    setShadowColorProperty);

protected:
    struct ShapeData;
    struct FreeShapeData;
    friend class FreeShapeBase;

    OMNIUI_API
    Shape(ShapeData* data = nullptr);

    OMNIUI_API
    void _drawContent(float elapsedTime) override;

    OMNIUI_API
    void _drawShapeShadow(float elapsedTime, float x, float y, float width, float height);

    OMNIUI_API
    virtual void _drawShape(float elapsedTime, float x, float y, float width, float height) = 0;

    OMNIUI_API
    virtual void _drawShadow(
        float elapsedTime,
        float x,
        float y,
        float width,
        float height,
        uint32_t shadowColor,
        float dpiScale,
        ImVec2 shadowOffset,
        float shadowThickness,
        uint32_t shadowFlag) = 0;

    OMNIUI_API
    bool _getFreeShapeInfo(ImVec2& start, ImVec2& size);

    OMNIUI_API
    Widget::BoundingBox _getFreeShapeInteractionBBox() const;

    // FreeShape.h exports implementation in header file, so this must be exported
    OMNIUI_API
    virtual void _makeFreeShape(std::shared_ptr<Widget> start, std::shared_ptr<Widget> end);

    /**
     * @brief Segment-circle intersection.
     * Follows closely https://stackoverflow.com/questions/1073336/circle-line-segment-collision-detection-algorithm
     *
     * @param p1 start of line
     * @param p2 end of line
     * @param center center of circle
     * @param r radius
     * @return true intersects
     * @return false doesn't intersect
     */
    static bool _intersects(float p1X, float p1Y, float p2X, float p2Y, float centerX, float centerY, float r);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
