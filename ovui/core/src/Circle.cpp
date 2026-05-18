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
#include <omni/ui/Circle.h>
#include <omni/ui/StyleContainer.h>

#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The filling and alignment logic. It takes the canvas and returns the offset and the size of the new
 * canvas that contains aligned circle.
 *
 * @param alignment Input. The alighnment policy.
 * @param sizePolicy Input. The sizing policy.
 * @param radius Input. The radius of the circle
 * @param canvasSize Input/Output. The size of the canvas the circle should be filled/aligned. It will have the new size
 *                   of the canvas that contains the aligned image.
 * @param centerOffset Output. The offset the cicle should be moved to contain aligned circle.
 */
static void alignCircle(
    Alignment alignment, Circle::SizePolicy sizePolicy, const float radius, float canvasSize[2], float cursorOffset[2])
{
    // first we calculate the aligment of the circle center

    // by default center is at the center of the canvas
    cursorOffset[0] = canvasSize[0] / 2;
    cursorOffset[1] = canvasSize[1] / 2;

    switch (alignment)
    {
    case Alignment::eCenter:
        // default no offset
        break;
    case Alignment::eCenterTop:
        cursorOffset[1] -= canvasSize[1] / 2;
        break;
    case Alignment::eCenterBottom:
        cursorOffset[1] += canvasSize[1] / 2;
        break;
    case Alignment::eLeftCenter:
        cursorOffset[0] -= canvasSize[0] / 2;
        break;
    case Alignment::eRightCenter:
        cursorOffset[0] += canvasSize[0] / 2;
        break;
    case Alignment::eLeftTop:
        cursorOffset[0] = 0;
        cursorOffset[1] = 0;
        break;
    case Alignment::eLeftBottom:
        cursorOffset[0] = 0;
        cursorOffset[1] = canvasSize[1];
        break;
    case Alignment::eRightBottom:
        cursorOffset[0] = canvasSize[0];
        cursorOffset[1] = canvasSize[1];
        break;
    case Alignment::eRightTop:
        cursorOffset[0] = canvasSize[0];
        cursorOffset[1] = 0;
        break;

    // TODO :: Support the corner
    default:
        break;
    }

    // now we calculate the canvas size, for now only uniform radius (ie no elipse)
    if (sizePolicy == Circle::SizePolicy::eStretch)
    {
        float canvasAspect = canvasSize[0] / canvasSize[1];
        if (canvasAspect > 1)
        {
            // the radius of the circle will match the width
            float radius = canvasSize[1] / 2;

            // we will eventually support oval but not yet
            canvasSize[0] = radius;
            canvasSize[1] = radius;
        }
        else
        {
            // the radius of the circle will match the Height
            float radius = canvasSize[0] / 2;

            // we will eventually support oval but not yet
            canvasSize[0] = radius;
            canvasSize[1] = radius;
        }
    }
    else if (sizePolicy == Circle::SizePolicy::eFixed)
    {
        canvasSize[0] = radius;
        canvasSize[1] = radius;
    }
}

Circle::Circle() = default;

Circle::~Circle() = default;

void Circle::setComputedContentWidth(float width)
{
    if (this->getSizePolicy() == Circle::SizePolicy::eFixed)
    {
        float diameter = this->getAlignment() & Alignment::eHCenter ? 2.0f : 1.0f;
        float scaledRadius = diameter * this->getRadius() * this->getDpiScale();
        width = std::max(scaledRadius, width);
    }

    Widget::setComputedContentWidth(width);
}

void Circle::setComputedContentHeight(float height)
{
    if (this->getSizePolicy() == Circle::SizePolicy::eFixed)
    {
        float diameter = this->getAlignment() & Alignment::eVCenter ? 2.0f : 1.0f;
        float scaledRadius = diameter * this->getRadius() * this->getDpiScale();
        height = std::max(scaledRadius, height);
    }

    Widget::setComputedContentHeight(height);
}

void Circle::_drawShadow(
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
    ImVec2 center{ x, y };
    float radius = 0.0f;
    _calCentreAndRadius(width, height, dpiScale, center, radius);

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
        if (borderWidth > 0.0f)
        {
            radius +=  0.5f * borderWidth;
        }
    }

    ImGui::GetWindowDrawList()->AddShadowCircle(center, radius, shadowColor, shadowThickness, shadowOffset, shadowFlag, m_segments);
}

void Circle::_calCentreAndRadius(float width, float height, float dpiScale, ImVec2& center, float& radius)
{
    float canvasSize[2] = { fabsf(width), fabsf(height) };
    float cursorOffset[2] = { 0.0f, 0.0f };

    alignCircle(this->getAlignment(), this->getSizePolicy(), this->getRadius() * dpiScale, canvasSize, cursorOffset);

    center.x += cursorOffset[0];
    center.y += cursorOffset[1];

    if (width < 0)
    {
        center.x += width;
    }
    if (height < 0)
    {
        center.y += height;
    }
    // here we will deal with scaled circle for now we only suport circle
    radius = canvasSize[0];
}

void Circle::_drawShape(float elapsedTime, float x, float y, float width, float height)
{
    float dpiScale = this->getDpiScale();

    // The background color.
    uint32_t backgroundColor = 0xff000000;
    this->_resolveStyleProperty(this->getBackgroundColorProperty(), &backgroundColor);

    // Determine which border we need.
    uint32_t borderColor = 0x0;
    this->_resolveStyleProperty(this->getBorderColorProperty(), &borderColor);

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
    }

    ImVec2 center{ x, y };
    float radius = 0.0f;
    _calCentreAndRadius(width, height, dpiScale, center, radius);

    auto arc = this->getArc();
    bool clip = arc & (Alignment::eLeft | Alignment::eRight | Alignment::eTop | Alignment::eBottom);
    if (clip)
    {
        // Cut the circle
        ImVec2 min{ center.x - radius - borderWidth - 1.f, center.y - radius - borderWidth - 1.f };
        ImVec2 max{ center.x + radius + borderWidth + 1.f, center.y + radius + borderWidth + 1.f };
        if (arc & Alignment::eLeft)
        {
            max.x = center.x;
        }
        else if (arc & Alignment::eRight)
        {
            min.x = center.x;
        }
        if (arc & Alignment::eTop)
        {
            max.y = center.y;
        }
        else if (arc & Alignment::eBottom)
        {
            min.y = center.y;
        }

        ImGui::GetWindowDrawList()->PushClipRect(min, max, true);
    }

    if (backgroundColor != 0x0)
    {
        ImGui::GetWindowDrawList()->AddCircleFilled(center, radius, backgroundColor, m_segments);
    }

    if (borderWidth > 0.0f && borderColor != 0x0)
    {
        ImGui::GetWindowDrawList()->AddCircle(center, radius, borderColor, m_segments, borderWidth);
    }

    if (clip)
    {
        ImGui::GetWindowDrawList()->PopClipRect();
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
