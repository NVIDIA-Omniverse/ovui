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
#include "ArrowHelper.h"
#include "Shape.h"
#include "ShapeAnchorHelper.h"

#include <cstdint>
#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct LineStyleSnapshot;

/**
 * @brief The Line widget provides a colored line to display.
 */
class OMNIUI_CLASS_API Line : public Shape, public ArrowHelper, public ShapeAnchorHelper
{
    OMNIUI_OBJECT(Line)

public:
    OMNIUI_API
    ~Line() override;

    /**
     * @brief Function that returns the closest parametric T value to a given x,y position.
     */
    OMNIUI_API
    float closestParametricPosition(const float p_x, const float p_y) override;

    /**
     * @brief Sets the function that will be called when the user use mouse enter/leave on the line. It's the override
     * to prevent Widget from the bounding box logic.
     * The function specification is:
     *     void onMouseHovered(bool hovered)
     */
    OMNIUI_API
    void setMouseHoveredFn(std::function<void(bool)> fn) override;

    /**
     * @brief Sets the function that will be called when the user presses the mouse button inside the widget. The
     * function should be like this:
     *     void onMousePressed(float x, float y, int32_t button, KeyboardModifierFlags modifier)
     *
     * It's the override to prevent the bounding box logic.
     */
    OMNIUI_API
    void setMousePressedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn) override;

    /**
     * @brief Sets the function that will be called when the user releases the mouse button if this button was pressed
     * inside the widget.
     *     void onMouseReleased(float x, float y, int32_t button, KeyboardModifierFlags modifier)
     */
    OMNIUI_API
    void setMouseReleasedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn) override;

    /**
     * @brief Sets the function that will be called when the user presses the mouse button twice inside the widget. The
     * function specification is the same as in setMousePressedFn.
     *     void onMouseDoubleClicked(float x, float y, int32_t button, KeyboardModifierFlags modifier)
     */
    OMNIUI_API
    void setMouseDoubleClickedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn) override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than 1 pixel
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than 1 pixel
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief This property holds the alignment of the Line can only LEFT, RIGHT, VCENTER, HCENTER , BOTTOM, TOP.
     * By default, the Line is HCenter.
     */
    OMNIUI_PROPERTY(Alignment, alignment, DEFAULT, Alignment::eVCenter, READ, getAlignment, WRITE, setAlignment);

protected:
    /**
     * @brief Constructs Line
     */
    OMNIUI_API
    Line();

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
    // Don't use m_mouseHoveredFn and m_isHovered to prevent the bbox logic of Widget.
    std::function<void(bool)> m_mouseHoveredLineFn;
    std::function<void(float, float, int32_t, KeyboardModifierFlags)> m_mousePressedLineFn;
    std::function<void(float, float, int32_t, KeyboardModifierFlags)> m_mouseReleasedLineFn;
    std::function<void(float, float, int32_t, KeyboardModifierFlags)> m_mouseDoubleClickedLineFn;
    bool m_isHoveredLine = false;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
