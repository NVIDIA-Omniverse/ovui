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

#include "ArrowHelper.h"
#include "Shape.h"
#include "ShapeAnchorHelper.h"

#include <cstdint>
#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Smooth curve that can be scaled infinitely.
 */
class OMNIUI_CLASS_API BezierCurve : public Shape, public ArrowHelper, public ShapeAnchorHelper
{
    OMNIUI_OBJECT(BezierCurve)

public:
    OMNIUI_API
    ~BezierCurve() override;

    /**
     * @brief Function that returns the closest parametric T value to a given x,y position.
     */
    OMNIUI_API
    float closestParametricPosition(const float pX, const float pY) override;

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
     *
     * Where:
     *  button is the number of the mouse button pressed
     *  modifier is the flag for the keyboard modifier key
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
     * @brief Sets the computed width of the content of the widget.
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Sets the computed height of the content of the widget.
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Sets the function that will be called when the user presses the mouse button twice inside the widget. The
     * function specification is the same as in setMousePressedFn.
     *     void onMouseDoubleClicked(float x, float y, int32_t button, KeyboardModifierFlags modifier)
     */
    OMNIUI_API
    void setMouseDoubleClickedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn) override;

    /**
     * @brief This property holds the X coordinate of the start of the curve relative to the width bound of the curve.
     */
    OMNIUI_PROPERTY(
        Length, startTangentWidth, DEFAULT, Fraction{ 1.0f }, READ, getStartTangentWidth, WRITE, setStartTangentWidth);

    /**
     * @brief This property holds the Y coordinate of the start of the curve relative to the width bound of the curve.
     */
    OMNIUI_PROPERTY(
        Length, startTangentHeight, DEFAULT, Pixel{ 0.0f }, READ, getStartTangentHeight, WRITE, setStartTangentHeight);

    /**
     * @brief This property holds the X coordinate of the end of the curve relative to the width bound of the curve.
     */
    OMNIUI_PROPERTY(Length, endTangentWidth, DEFAULT, Fraction{ -1.0f }, READ, getEndTangentWidth, WRITE, setEndTangentWidth);

    /**
     * @brief This property holds the Y coordinate of the end of the curve relative to the width bound of the curve.
     */
    OMNIUI_PROPERTY(Length, endTangentHeight, DEFAULT, Pixel{ 0.0f }, READ, getEndTangentHeight, WRITE, setEndTangentHeight);

protected:
    /**
     * @brief Initialize the curve.
     */
    OMNIUI_API
    BezierCurve();

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
    /**
     * @brief Finds closest parametric T value to the bezier curve, given 4 control points and the number of segments.
     */
    float _bezierClosestTPoint(const ImVec2& p1, const ImVec2& p2, const ImVec2& p3, const ImVec2& p4, const ImVec2& p, int numSegments);

    /**
     * @brief Return width/height of two tangents.
     */
    void _evaluateTangents(
        float width, float height, float& startWidth, float& startHeight, float& endWidth, float& endHeight) const;

    // void _calculteNormalPoints(
    //     const ImVec2& p1, const ImVec2& p2, float dist, int id, int size, std::vector<ImVec2>& points);

    // Don't use m_mouseHoveredFn and m_isHovered to prevent the bbox logic of Widget.
    std::function<void(bool)> m_mouseHoveredLineFn;
    bool m_isHoveredLine = false;

    // Don't use m_mousePressedFn to prevent the bbox logic of Widget.
    std::function<void(float, float, int32_t, KeyboardModifierFlags)> m_mousePressedLineFn;
    std::function<void(float, float, int32_t, KeyboardModifierFlags)> m_mouseReleasedLineFn;
    std::function<void(float, float, int32_t, KeyboardModifierFlags)> m_mouseDoubleClickedLineFn;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
