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

#define _USE_MATH_DEFINES
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/ArrowHelper.h>
#include <omni/ui/Line.h>
#include <omni/ui/Spacer.h>
#include <omni/ui/StyleContainer.h>

#include "ShapeData.h"

#include <algorithm>
#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The filling and alignment logic. It takes the canvas and returns the offset and the size of the new
 * canvas that contains the aligned line.
 *
 * @param alignment Input. The alignment policy. This represents the position of the line
 * @param cursor Input. the current position of the cursor
 * @param canvasSize Input. The size of the canvas the line should be filled/aligned to.
 * @param p1 Output. first point of the line
 * @param p2 Output. second point of the line
 */

static void alignLine(Alignment alignment, const ImVec2& cursor, const ImVec2& canvasSize, ImVec2& p1, ImVec2& p2)
{
    switch (alignment)
    {
    case Alignment::eUndefined:
        p1.x = cursor.x;
        p1.y = cursor.y;
        p2.x = cursor.x + canvasSize.x;
        p2.y = cursor.y + canvasSize.y;
        break;

    case Alignment::eLeft:
        p1.x = cursor.x;
        p1.y = cursor.y;

        p2.x = cursor.x;
        p2.y = cursor.y + canvasSize.y;
        break;
    case Alignment::eRight:
        p1.x = cursor.x + canvasSize.x;
        p1.y = cursor.y;

        p2.x = cursor.x + canvasSize.x;
        p2.y = cursor.y + canvasSize.y;
        break;
    case Alignment::eHCenter:
        p1.x = cursor.x + canvasSize.x / 2;
        p1.y = cursor.y;

        p2.x = cursor.x + canvasSize.x / 2;
        p2.y = cursor.y + canvasSize.y;
        break;
    case Alignment::eTop:
        p1.x = cursor.x;
        p1.y = cursor.y;

        p2.x = cursor.x + canvasSize.x;
        p2.y = cursor.y;
        break;
    case Alignment::eBottom:
        p1.x = cursor.x;
        p1.y = cursor.y + canvasSize.y;

        p2.x = cursor.x + canvasSize.x;
        p2.y = cursor.y + canvasSize.y;
        break;
    case Alignment::eVCenter:
        p1.x = cursor.x;
        p1.y = cursor.y + canvasSize.y / 2;

        p2.x = cursor.x + canvasSize.x;
        p2.y = cursor.y + canvasSize.y / 2;
        break;

    default:
        // center vertically
        p1.x = cursor.x;
        p1.y = cursor.y + canvasSize.y / 2;

        p2.x = cursor.x + canvasSize.x;
        p2.y = cursor.y + canvasSize.y / 2;
        break;
    }
}

Line::Line()
{
    // We use a C++ hack to access protected member. It works because it calls a data member of base class only.
    static_cast<Line*>(static_cast<Widget*>(m_anchorFrame.get()))->Widget::setParent(this);
}

Line::~Line() = default;

void Line::setMouseHoveredFn(std::function<void(bool)> fn)
{
    m_mouseHoveredLineFn = std::move(fn);
}

void Line::setMousePressedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn)
{
    m_mousePressedLineFn = std::move(fn);
}

void Line::setMouseReleasedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn)
{
    m_mouseReleasedLineFn = std::move(fn);
}

void Line::setMouseDoubleClickedFn(std::function<void(float, float, int32_t, KeyboardModifierFlags)> fn)
{
    m_mouseDoubleClickedLineFn = std::move(fn);
}

void Line::setComputedContentWidth(float width)
{
    ShapeAnchorHelper::shapeAnchorHelperSetComputedContentWidth(width);
    Shape::setComputedContentWidth(width);
}

void Line::setComputedContentHeight(float height)
{
    ShapeAnchorHelper::shapeAnchorHelperSetComputedContentHeight(height);
    Shape::setComputedContentHeight(height);
}

void Line::_drawShadow(
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
    ImVec2 canvasSize{ width, height };
    ImVec2 start{ x, y };

    ImVec2 p1, p2;
    alignLine(this->getAlignment(), start, canvasSize, p1, p2);

    float lineWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &lineWidth))
    {
        lineWidth *= dpiScale;
    }
    else
    {
        lineWidth = dpiScale;
    }

    float dist = lineWidth * 0.5f;
    std::vector<ImVec2> points(4);
    float c = 0;
    float b = dist;
    if (p2.y != p1.y)
    {
        c =  dist;
        b = 0;
    }

    points[0] = ImVec2{c + p1.x, b + p1.y};
    points[1] = ImVec2{c + p2.x, b + p2.y};
    points[2] = ImVec2{-c + p2.x, -b + p2.y};
    points[3] = ImVec2{-c + p1.x, -b + p1.y};

    ImGui::GetWindowDrawList()->AddShadowConvexPoly(points.data(), 4, shadowColor, shadowThickness, shadowOffset, shadowFlag);
}

void Line::_drawShape(float elapsedTime, float x, float y, float width, float height)
{
    float dpiScale = this->getDpiScale();

    // Determine which border we need.
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

    ImVec2 canvasSize{ width, height };
    ImVec2 start{ x, y };

    ImVec2 p1, p2;
    alignLine(this->getAlignment(), start, canvasSize, p1, p2);

    if (lineWidth > 0.0f)
    {
        ImGui::GetWindowDrawList()->AddLine(p1, p2, lineColor, lineWidth);
    }

    const ImGuiIO& io = ImGui::GetIO();
    auto mousePos = ImGui::GetMousePos();
    float intersectionThreshold = std::max(1.0f, 5.0f * dpiScale);

    // Hovering of the widget uses bounding boxes. With the besier line it's better to call callbacks when the line is
    // hovered.
    const bool isHovered = setHovered(_intersects(p1.x, p1.y, p2.x, p2.y, mousePos.x, mousePos.y, intersectionThreshold));
    if (isHovered != m_isHoveredLine)
    {
        if (m_mouseHoveredLineFn)
        {
            m_mouseHoveredLineFn(isHovered);
        }
        m_isHoveredLine = isHovered;
    }

    if (isHovered)
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

    // Draw arrow at the begin of the line (points from p2 toward p1)
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

    // Draw arrow at the end of the line (points from p1 toward p2)
    ArrowHelper::ArrowType endArrowType = this->getEndArrowType();
    arrowWidth = this->getEndArrowWidth();
    arrowHeight = this->getEndArrowHeight();
    switch (endArrowType)
    {
    case ArrowType::eArrow:
        this->drawArrow(p1.x, p1.y, p2.x - p1.x, p2.y - p1.y, dpiScale, lineWidth, arrowWidth, arrowHeight, lineColor);
        break;
    default:
        break;
    }

    // Draw line anchor
    if (this->hasAnchorFn())
    {
        ImVec2 anchor = ImLerp(p1, p2, this->getAnchorPosition());

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

float Line::closestParametricPosition(const float pX, const float pY)
{

    const ImVec2 p = { pX, pY };

    // Line ends
    const auto& data = _getData<ShapeData>();
    ImVec2 p1 = data.m_startPoint;
    ImVec2 p2{ p1.x + data.m_shapeSize.x, p1.y + data.m_shapeSize.y };

    p1 = ImFloor(p1);
    p2 = ImFloor(p2);

    ImVec2 p_on_line = ImLineClosestPoint(p1, p2, p);
    ImVec2 full_vec = { p2.x - p1.x, p2.y - p1.y };
    ImVec2 partial_vec = { p_on_line.x - p1.x, p_on_line.y - p1.y };
    float full_length = ImMax(ImSqrt(ImLengthSqr(full_vec)), 0.001f);
    float partial_length = ImMax(ImSqrt(ImLengthSqr(partial_vec)), 0.001f);

    return partial_length / full_length;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
