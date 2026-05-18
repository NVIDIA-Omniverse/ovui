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

#include "platform/Assert.h"
#include <iostream>

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/BezierCurve.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/Frame.h>
#include <omni/ui/Spacer.h>

#include "ShapeData.h"

#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Computes one component of tangent.
 */
static float _getTangentLength(float width, float dpiScale, const Length& start, const Length& end)
{
    if (start.unit == UnitType::ePixel)
    {
        return start.value * dpiScale;
    }
    else if (start.unit == UnitType::ePercent)
    {
        return 0.01f * start.value * width;
    }

    // It's fraction. We need to find the available width and the total number of fractions.
    float availableWidth = width;
    float totalFractions = 0.0f;

    for (auto&& i : { start, end })
    {
        if (i.unit == UnitType::ePixel)
        {
            availableWidth -= fabsf(i.value) * dpiScale;
        }
        else if (i.unit == UnitType::ePercent)
        {
            availableWidth -= fabsf(0.01f * i.value * width);
        }
        else // if (currentWidth.unit == UnitType::eFraction)
        {
            totalFractions += fabsf(i.value);
        }
    }

    if (totalFractions == 0.0f)
    {
        return 0.0f;
    }

    return availableWidth * start.value / totalFractions;
}

void BezierCurve::setComputedContentWidth(float width)
{
    ShapeAnchorHelper::shapeAnchorHelperSetComputedContentWidth(width);
    Shape::setComputedContentWidth(width);
}

void BezierCurve::setComputedContentHeight(float height)
{
    ShapeAnchorHelper::shapeAnchorHelperSetComputedContentHeight(height);
    Shape::setComputedContentHeight(height);
}

BezierCurve::BezierCurve()
{
    // We use a C++ hack to access protected member. It works because it calls a data member of base class only.
    static_cast<BezierCurve*>(static_cast<Widget*>(m_anchorFrame.get()))->Widget::setParent(this);
}

BezierCurve::~BezierCurve() = default;

void BezierCurve::setMouseHoveredFn(std::function<void(bool)> fn)
{
    m_mouseHoveredLineFn = std::move(fn);
}

void BezierCurve::setMousePressedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn)
{
    m_mousePressedLineFn = std::move(fn);
}

void BezierCurve::setMouseReleasedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn)
{
    m_mouseReleasedLineFn = std::move(fn);
}

void BezierCurve::setMouseDoubleClickedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn)
{
    m_mouseDoubleClickedLineFn = std::move(fn);
}

void BezierCurve::_drawShadow(
    float elapsedTime,
    float x,
    float y,
    float width,
    float height,
    uint32_t shadowColor,
    float dpiScale,
    ImVec2 shadowOffset,
    float shadowThickness,
    uint32_t shadowFlag)
{
    // float lineWidth = 0.0f;
    // if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &lineWidth))
    // {
    //     lineWidth *= dpiScale;
    // }
    // else
    // {
    //     lineWidth = dpiScale;
    // }

    // // Curve ends
    // ImVec2 p1{ x, y };
    // ImVec2 p4{ x + width, y + height };

    // // Tangents
    // ImVec2 p2;
    // ImVec2 p3;

    // this->_evaluateTangents(fabsf(p1.x - p4.x), fabsf(p1.y - p4.y), p2.x, p2.y, p3.x, p3.y);

    // p2.x += p1.x;
    // p2.y += p1.y;
    // p3.x += p4.x;
    // p3.y += p4.y;

    // p1 = ImFloor(p1);
    // p4 = ImFloor(p4);

    // // Compute the tesselation number depending on the length of line (p1, p4). It's not the precise length of the
    // // curve, but it's fast to compute.
    // ImVec2 size1{ p4.x - p3.x, p4.y - p3.y };
    // ImVec2 size2{ p3.x - p2.x, p3.y - p2.y };
    // ImVec2 size3{ p2.x - p1.x, p2.y - p1.y };
    // float length =
    //     sqrtf(size1.x * size1.x + size1.y * size1.y) +
    //     sqrtf(size2.x * size2.x + size2.y * size2.y) +
    //     sqrtf(size3.x * size3.x + size3.y * size3.y);

    // // A segment for every 10 pixels. Not more than a thousand.
    // int32_t numSegments = std::min(std::max(static_cast<int32_t>(length * 0.1f), 1), 1000);

    // ImVec2 previous = p1;

    // int32_t size = (numSegments + 1) * 2;
    // std::vector<ImVec2> points(size);

    // float dist = lineWidth * 0.5f;

    // float t_step = 1.0f / (float)numSegments;
    // for (int32_t i_step = 1; i_step <= numSegments; i_step++)
    // {
    //     ImVec2 next = ImBezierCubicCalc(p1, p2, p3, p4, t_step * i_step);
    //     _calculteNormalPoints(previous, next, dist, i_step, size, points);
    //     previous = next;
    // }

    // debug purpose to check the points positions
    // for (int i = 0; i < size; i++)
    // {
    //     ImGui::GetWindowDrawList()->AddShadowCircle(points[i], 3, shadowColor, shadowThickness, shadowOffset, shadowFlag, 40);
    // }

    // Curve 1: just one poly, but it is conves poly, so it doesn't really work for curve
    // ImGui::GetWindowDrawList()->AddShadowConvexPoly(points.data(), size, shadowColor, shadowThickness, shadowOffset, shadowFlag);

    // Curve 2: numSegments of polys, but there is overlapped shadows between polys, still have artefacts.
    // for (int i = 0; i<numSegments; i++)
    // {
    //     std::vector<ImVec2> selected_points = {points[i], points[i+1], points[size-2-i], points[size-1-i]};
    //     ImGui::GetWindowDrawList()->AddShadowConvexPoly(selected_points.data(), 4, shadowColor, shadowThickness, shadowOffset, shadowFlag);
    // }
}

// void BezierCurve::_calculteNormalPoints(const ImVec2& p1, const ImVec2& p2, float dist, int id, int size, std::vector<ImVec2>& points)
// {
//     float c = 0;
//     float b = dist;
//     if (p2.y != p1.y)
//     {
//         float k = (p1.x - p2.x) / (p2.y - p1.y);
//         c =  dist / std::sqrt(k*k + 1);
//         b = k * c;
//     }
//     // push the first points
//     if (id == 1)
//     {
//         points[0] = ImVec2{c + p1.x, b + p1.y};
//         points[size-1] = ImVec2{-c + p1.x, -b + p1.y};
//     }
//     points[id] = ImVec2{c + p2.x, b + p2.y};
//     points[size-1-id] = ImVec2{-c + p2.x, -b + p2.y};
// }

void BezierCurve::_drawShape(float elapsedTime, float x, float y, float width, float height)
{
    // Curve ends
    ImVec2 p1{ x, y };
    ImVec2 p4{ x + width, y + height };

    ImGuiContext* ctx = ImGui::GetCurrentContext();
    OMNIUI_ASSERT(ctx);
    const auto& clipRect = ctx->CurrentWindow->ClipRect;

    // Tangents
    ImVec2 p2;
    ImVec2 p3;

    this->_evaluateTangents(fabsf(p1.x - p4.x), fabsf(p1.y - p4.y), p2.x, p2.y, p3.x, p3.y);

    p2.x += p1.x;
    p2.y += p1.y;
    p3.x += p4.x;
    p3.y += p4.y;

    p1 = ImFloor(p1);
    p4 = ImFloor(p4);

    // Check if bounding rect of all 4 points is visible
    {
        ImVec2 min{ std::min(std::min(p1.x, p2.x), std::min(p3.x, p4.x)), std::min(std::min(p1.y, p2.y), std::min(p3.y, p4.y)) };
        ImVec2 max{ std::max(std::max(p1.x, p2.x), std::max(p3.x, p4.x)), std::max(std::max(p1.y, p2.y), std::max(p3.y, p4.y)) };

        if (!clipRect.Overlaps(ImRect(min, max)))
        {
            return;
        }
    }

    // Compute the tesselation number depending on the length of line (p1, p4). It's not the precise length of the
    // curve, but it's fast to compute.
    ImVec2 size1{ p4.x - p3.x, p4.y - p3.y };
    ImVec2 size2{ p3.x - p2.x, p3.y - p2.y };
    ImVec2 size3{ p2.x - p1.x, p2.y - p1.y };
    float length =
        sqrtf(size1.x * size1.x + size1.y * size1.y) +
        sqrtf(size2.x * size2.x + size2.y * size2.y) +
        sqrtf(size3.x * size3.x + size3.y * size3.y);

    // A segment for every 10 pixels. Not more than a thousand.
    int32_t numSegments = std::min(std::max(static_cast<int32_t>(length * 0.1f), 1), 1000);

    auto drawList = ImGui::GetWindowDrawList();
    const ImGuiIO& io = ImGui::GetIO();
    auto mousePos = ImGui::GetMousePos();
    float dpiScale = this->getDpiScale();
    float intersectionThreshold = std::max(1.0f, 5.0f * dpiScale);
    bool isHovered = false;

    ImVec2 previous = p1;
    bool visible = false;
    bool previous_visible = false;

    float t_step = 1.0f / (float)numSegments;
    for (int32_t i_step = 1; i_step <= numSegments; i_step++)
    {
        // AddBezierCurve is also using ImBezierCubicCalc and PathLineTo
        ImVec2 next = ImBezierCubicCalc(p1, p2, p3, p4, t_step * i_step);

        ImVec2 min{ std::min(previous.x, next.x), std::min(previous.y, next.y) };
        ImVec2 max{ std::max(previous.x, next.x), std::max(previous.y, next.y) };

        if (clipRect.Overlaps(ImRect(min, max)))
        {
            if (!previous_visible)
            {
                // First vertex of the curve
                drawList->PathLineTo(previous);
            }
            drawList->PathLineTo(next);
            visible = true;
            previous_visible = true;

            if (!isHovered && _intersects(min.x, min.y, max.x, max.y, mousePos.x, mousePos.y, intersectionThreshold))
            {
                isHovered = true;
            }

            // TODO: Check if mouse is pressed
            // TODO: Check if mouse is released
        }
        else
        {
            previous_visible = false;
        }

        previous = next;
    }

    if (!visible)
    {
        // Early exit
        drawList->PathClear();
        return;
    }

    // Hovering of the widget uses bounding boxes. With the bezier line it's better to call callbacks when the line is
    // hovered.
    setHovered(isHovered);
    if (isHovered != m_isHoveredLine)
    {
        if (m_mouseHoveredLineFn)
        {
            m_mouseHoveredLineFn(isHovered);
        }
        m_isHoveredLine = isHovered;
    }

    if (m_isHoveredLine)
    {
        KeyboardModifierFlags modifiers = 0;
        float mouseX = 0.0f;
        float mouseY = 0.0f;
        if (m_mousePressedLineFn || m_mouseReleasedLineFn || m_mouseDoubleClickedLineFn)
        {
            float dpiScaleInv = 1.0f / dpiScale;
            KeyboardModifierFlags modifiers = (io.KeyAlt ? kKeyModAlt : 0) |
                                                           (io.KeyShift ? kKeyModShift : 0) |
                                                           (io.KeyCtrl ? kKeyModCtrl : 0) |
                                                           (io.KeySuper ? kKeyModSuper : 0);
            mouseX = mousePos.x * dpiScaleInv;
            mouseY = mousePos.y * dpiScaleInv;
        }

        if (m_mousePressedLineFn)
        {
            for (int32_t button = 0; button < 3; ++button)
            {
                if (ImGui::IsMouseClicked(button, false))
                {
                    m_mousePressedLineFn(mouseX, mouseY, button, modifiers);
                }
            }
        }

        if (m_mouseReleasedLineFn)
        {
            for (int32_t button = 0; button < 3; ++button)
            {
                if (ImGui::IsMouseReleased(button))
                {
                    m_mouseReleasedLineFn(mouseX, mouseY, button, modifiers);
                }
            }
        }

        if (m_mouseDoubleClickedLineFn)
        {
            for (int32_t button = 0; button < 3; ++button)
            {
                if (ImGui::IsMouseDoubleClicked(button))
                {
                    m_mouseDoubleClickedLineFn(mouseX, mouseY, button, modifiers);
                }
            }
        }
    }

    // Determine which line color and width we need.
    uint32_t lineColor = 0xff000000;
    this->_resolveStyleProperty(StyleColorProperty::eColor, &lineColor);

    float lineWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &lineWidth))
    {
        lineWidth *= dpiScale;
    }
    else
    {
        lineWidth = dpiScale;
    }

    drawList->PathStroke(lineColor, false, lineWidth);

    // Draw arrow at the beginning of the line
    ArrowHelper::ArrowType beginArrowType = this->getBeginArrowType();
    float arrowWidth = this->getBeginArrowWidth();
    float arrowHeight = this->getBeginArrowHeight();
    switch (beginArrowType)
    {
    case ArrowType::eArrow:
        this->drawArrow(p2.x, p2.y, p1.x - p2.x, p1.y - p2.y, dpiScale, lineWidth, arrowWidth, arrowHeight, lineColor);
        break;
    default:
        break;
    }

    // Draw arrow at the end of the line
    ArrowHelper::ArrowType endArrowType = this->getEndArrowType();
    arrowWidth = this->getBeginArrowWidth();
    arrowHeight = this->getEndArrowHeight();
    switch (endArrowType)
    {
    case ArrowType::eArrow:
        this->drawArrow(p3.x, p3.y, p4.x - p3.x, p4.y - p3.y, dpiScale, lineWidth, arrowWidth, arrowHeight, lineColor);
        break;
    default:
        break;
    }

    // Draw curve anchor
    if (this->hasAnchorFn())
    {
        ImVec2 anchor = ImBezierCubicCalc(p1, p2, p3, p4, this->getAnchorPosition());

        // save the current cursor
        auto cursor = ImGui::GetCursorScreenPos();

        float content_width  = m_anchorFrame->getComputedWidth();
        float content_height = m_anchorFrame->getComputedHeight();

        // setup alignment
        float offset_x = this->_alignmentHOffset(this->getAnchorAlignment(), content_width);
        float offset_y = this->_alignmentVOffset(this->getAnchorAlignment(), content_height);
        ImVec2 anchorAligned = { anchor.x + offset_x, anchor.y + offset_y };

        ImGui::SetCursorScreenPos(anchorAligned);

        m_anchorFrame->draw(elapsedTime);

        // Restore the cursor
        ImGui::SetCursorScreenPos(cursor);

    }
}

void BezierCurve::_evaluateTangents(
    float width, float height, float& startWidth, float& startHeight, float& endWidth, float& endHeight) const
{
    auto startTangentWidth = this->getStartTangentWidth();
    auto startTangentHeight = this->getStartTangentHeight();
    auto endTangentWidth = this->getEndTangentWidth();
    auto endTangentHeight = this->getEndTangentHeight();

    float dpiScale = this->getDpiScale();

    startWidth = _getTangentLength(width, dpiScale, startTangentWidth, endTangentWidth);
    startHeight = _getTangentLength(height, dpiScale, startTangentHeight, endTangentHeight);
    endWidth = _getTangentLength(width, dpiScale, endTangentWidth, startTangentWidth);
    endHeight = _getTangentLength(height, dpiScale, endTangentHeight, startTangentHeight);
}

float BezierCurve::_bezierClosestTPoint(const ImVec2& p1, const ImVec2& p2, const ImVec2& p3, const ImVec2& p4, const ImVec2& p, int numSegments)
{
    //Mostly the same as ImBezierClosestPoint, just returning the T value instead
    ImVec2 p_last = p1;
    ImVec2 p_closest;
    float p_closest_dist2 = FLT_MAX;
    float t_closest = 0;
    float t_step = 1.0f / (float)numSegments;
    for (int i_step = 1; i_step <= numSegments; i_step++)
    {
        ImVec2 p_current = ImBezierCubicCalc(p1, p2, p3, p4, t_step * i_step);
        ImVec2 p_line = ImLineClosestPoint(p_last, p_current, p);
        ImVec2 dist_vec = { p.x - p_line.x, p.y - p_line.y };
        float dist2 = ImLengthSqr(dist_vec);
        if (dist2 < p_closest_dist2)
        {
            p_closest_dist2 = dist2;
            t_closest = t_step * i_step;
        }
        p_last = p_current;
    }
    return t_closest;
}

float BezierCurve::closestParametricPosition(const float pX, const float pY)
{

    const ImVec2 p = { pX, pY };

    // Curve ends
    const auto& data = _getData<ShapeData>();
    ImVec2 p1 = data.m_startPoint;
    ImVec2 p4{ p1.x + data.m_shapeSize.x, p1.y + data.m_shapeSize.y };

    // Tangents
    ImVec2 p2;
    ImVec2 p3;

    this->_evaluateTangents(fabsf(p1.x - p4.x), fabsf(p1.y - p4.y), p2.x, p2.y, p3.x, p3.y);

    p2.x += p1.x;
    p2.y += p1.y;
    p3.x += p4.x;
    p3.y += p4.y;

    p1 = ImFloor(p1);
    p4 = ImFloor(p4);

    // Compute the tesselation number depending on the length of line (p1, p4). It's not the precise length of the
    // curve, but it's fast to compute.
    ImVec2 size1{ p4.x - p3.x, p4.y - p3.y };
    ImVec2 size2{ p3.x - p2.x, p3.y - p2.y };
    ImVec2 size3{ p2.x - p1.x, p2.y - p1.y };
    float length =
        sqrtf(size1.x * size1.x + size1.y * size1.y) +
        sqrtf(size2.x * size2.x + size2.y * size2.y) +
        sqrtf(size3.x * size3.x + size3.y * size3.y);

    // A segment for every 10 pixels. Not more than a thousand.
    int32_t numSegments = std::min(std::max(static_cast<int32_t>(length * 0.1f), 1), 1000);

    return this->_bezierClosestTPoint(p1, p2, p3, p4, p, numSegments);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
