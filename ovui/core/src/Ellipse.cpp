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
#include <omni/ui/Ellipse.h>
#include <omni/ui/StyleContainer.h>

#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

Ellipse::Ellipse() = default;

Ellipse::~Ellipse() = default;

void Ellipse::_drawShadow(
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
    float canvasSize[2] = { fabsf(width), fabsf(height) };
    ImVec2 center{ x + width / 2, y + height / 2 };

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
        if (borderWidth > 0.0f)
        {
            canvasSize[0] += borderWidth;
            canvasSize[1] += borderWidth;
        }
    }

    // here we will deal with scaled circle for now we only suport circle
    float radiusA = canvasSize[0] / 2;
    float radiusB = canvasSize[1] / 2;

    // this need to become a property, stylable ?
    const float aMax = (IM_PI * 2.0f) * ((float)m_numSegments - 1.0f) / (float)m_numSegments;

    std::vector<ImVec2> points;
    for (int i = 0; i <= m_numSegments; i++)
    {
        const float a = ((float)i / (float)m_numSegments - 1.0f) * aMax;
        points.push_back(ImVec2(center.x + ImCos(a) * radiusA, center.y + ImSin(a) * radiusB));
    }

    ImGui::GetWindowDrawList()->AddShadowConvexPoly(points.data(), m_numSegments, shadowColor, shadowThickness, shadowOffset, shadowFlag);
}

void Ellipse::_drawShape(float elapsedTime, float x, float y, float width, float height)
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

    float canvasSize[2] = { fabsf(width), fabsf(height) };

    ImVec2 center{ x + width / 2, y + height / 2 };

    // here we will deal with scaled circle for now we only suport circle
    float radiusA = canvasSize[0] / 2;
    float radiusB = canvasSize[1] / 2;

    const float aMax = (IM_PI * 2.0f) * ((float)m_numSegments - 1.0f) / (float)m_numSegments;
    if (backgroundColor != 0x0)
    {
        for (int i = 0; i <= m_numSegments; i++)
        {
            const float a = ((float)i / (float)m_numSegments - 1.0f) * aMax;
            ImGui::GetWindowDrawList()->PathLineTo(ImVec2(center.x + ImCos(a) * radiusA, center.y + ImSin(a) * radiusB));
        }
        ImGui::GetWindowDrawList()->PathFillConvex(backgroundColor);
    }

    if (borderWidth > 0.0f && borderColor != 0x0)
    {
        for (int i = 0; i <= m_numSegments; i++)
        {
            const float a = ((float)i / (float)m_numSegments - 1.0f) * aMax;
            ImGui::GetWindowDrawList()->PathLineTo(
                ImVec2(center.x + ImCos(a) * (radiusA - 0.5f), center.y + ImSin(a) * (radiusB - 0.5f)));
        }
        ImGui::GetWindowDrawList()->PathStroke(borderColor, true, borderWidth);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
