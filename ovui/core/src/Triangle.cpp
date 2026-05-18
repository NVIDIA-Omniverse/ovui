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
#include <omni/ui/StyleContainer.h>
#include <omni/ui/Triangle.h>

#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The filling and alignment logic. It takes the canvas and returns the offset and the size of the new
 * canvas that contains aligned circle.
 *
 * @param alignment Input. The alighnment policy. this represent the position of the Tip of the triangle
 * @param canvasPosition Input. the current position of the cursor
 * @param canvasSize Input. The size of the canvas the triangle should be filled/aligned.
 * @param p1 Output. first point of the triangle
 * @param p2 Output. second point of the triangle
 * @param p3 Output. third point of the triangle
 */

static void alignTriangle(
    Alignment alignment, const ImVec2& canvasPosition, const ImVec2& canvasSize, ImVec2& p1, ImVec2& p2, ImVec2& p3)
{
    switch (alignment)
    {
    case Alignment::eCenterTop:
        p1.x = canvasPosition.x;
        p1.y = canvasPosition.y + canvasSize.y;

        p2.x = canvasPosition.x + canvasSize.x;
        p2.y = canvasPosition.y + canvasSize.y;

        p3.x = canvasPosition.x + canvasSize.x / 2;
        p3.y = canvasPosition.y;
        break;
    case Alignment::eCenterBottom:
        p1.x = canvasPosition.x;
        p1.y = canvasPosition.y;

        p2.x = canvasPosition.x + canvasSize.x;
        p2.y = canvasPosition.y;

        p3.x = canvasPosition.x + canvasSize.x / 2;
        p3.y = canvasPosition.y + canvasSize.y;
        break;
    case Alignment::eLeftCenter:
        p1.x = canvasPosition.x;
        p1.y = canvasPosition.y + canvasSize.y / 2;

        p2.x = canvasPosition.x + canvasSize.x;
        p2.y = canvasPosition.y + canvasSize.y;

        p3.x = canvasPosition.x + canvasSize.x;
        p3.y = canvasPosition.y;
        break;
    case Alignment::eRightCenter:
        p1.x = canvasPosition.x;
        p1.y = canvasPosition.y;

        p2.x = canvasPosition.x;
        p2.y = canvasPosition.y + canvasSize.y;

        p3.x = canvasPosition.x + canvasSize.x;
        p3.y = canvasPosition.y + canvasSize.y / 2;
        break;
    case Alignment::eLeftTop:
        p1.x = canvasPosition.x;
        p1.y = canvasPosition.y;

        p2.x = canvasPosition.x;
        p2.y = canvasPosition.y + canvasSize.y;

        p3.x = canvasPosition.x + canvasSize.x;
        p3.y = canvasPosition.y + canvasSize.y;
        break;
    case Alignment::eLeftBottom:
        p1.x = canvasPosition.x;
        p1.y = canvasPosition.y + canvasSize.y;

        p2.x = canvasPosition.x + canvasSize.x;
        p2.y = canvasPosition.y;

        p3.x = canvasPosition.x;
        p3.y = canvasPosition.y;
        break;
    case Alignment::eRightTop:
        p1.x = canvasPosition.x + canvasSize.x;
        p1.y = canvasPosition.y;

        p2.x = canvasPosition.x + canvasSize.x;
        p2.y = canvasPosition.y + canvasSize.y;

        p3.x = canvasPosition.x;
        p3.y = canvasPosition.y + canvasSize.y;
        break;
    case Alignment::eRightBottom:
        p1.x = canvasPosition.x + canvasSize.x;
        p1.y = canvasPosition.y + canvasSize.y;

        p2.x = canvasPosition.x + canvasSize.x;
        p2.y = canvasPosition.y;

        p3.x = canvasPosition.x;
        p3.y = canvasPosition.y;
        break;

    default:
        // right center is the default
        p1.x = canvasPosition.x;
        p1.y = canvasPosition.y;

        p2.x = canvasPosition.x;
        p2.y = canvasPosition.y + canvasSize.y;

        p3.x = canvasPosition.x + canvasSize.x;
        p3.y = canvasPosition.y + canvasSize.y / 2;
        break;
    }
}

Triangle::Triangle() = default;

Triangle::~Triangle() = default;

void Triangle::_drawShadow(
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
    ImVec2 canvasPosition{ x, y };
    ImVec2 canvasSize = ImVec2(width, height);

    // the points of the triangle
    ImVec2 p1, p2, p3;
    alignTriangle(this->getAlignment(), canvasPosition, canvasSize, p1, p2, p3);

    std::vector<ImVec2> points{ p1, p2, p3 };

    ImGui::GetWindowDrawList()->AddShadowConvexPoly(points.data(), 3, shadowColor, shadowThickness, shadowOffset, shadowFlag);
}


void Triangle::_drawShape(float elapsedTime, float x, float y, float width, float height)
{
    float dpiScale = this->getDpiScale();

    // The background color.
    uint32_t backgroundColor = 0x0;
    this->_resolveStyleProperty(this->getBackgroundColorProperty(), &backgroundColor);

    // Determine which border we need.
    uint32_t borderColor = 0x0;
    this->_resolveStyleProperty(this->getBorderColorProperty(), &borderColor);

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
    }

    ImVec2 canvasPosition{ x, y };
    ImVec2 canvasSize = ImVec2(width, height);

    // the points of the triangle
    ImVec2 p1, p2, p3;
    alignTriangle(this->getAlignment(), canvasPosition, canvasSize, p1, p2, p3);

    if (backgroundColor != 0x0)
    {
        ImGui::GetWindowDrawList()->AddTriangleFilled(p1, p2, p3, backgroundColor);
    }

    if (borderWidth > 0.0f && borderColor != 0x0)
    {
        ImGui::GetWindowDrawList()->AddTriangle(p1, p2, p3, borderColor, borderWidth);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
