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
#include <omni/ui/Rectangle.h>
#include <omni/ui/StyleContainer.h>

#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

Rectangle::Rectangle() = default;

Rectangle::~Rectangle() = default;

void Rectangle::_drawShadow(
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
    float borderRadius = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &borderRadius))
    {
        borderRadius *= dpiScale;
    }

    // ImDrawCornerFlags
    uint32_t round_corner = ImDrawFlags_RoundCornersAll;
    this->_resolveStyleProperty(StyleEnumProperty::eCornerFlag, &round_corner);

    ImVec2 objMin{ x, y };
    ImVec2 objMax{ x + width, y + height };

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
        if (borderWidth > 0.0f)
        {
            float dist = 0.5f * borderWidth;
            objMin.x  -= dist;
            objMin.y  -= dist;
            objMax.x  += dist;
            objMax.y  += dist;
        }
    }
    // Pre-translate legacy CornerFlag bits (0x01..0x0F) to new ImDrawFlags_RoundCorners* layout
    // (bits 4..7). FixRectCornerFlags inside ImGui only applies the translation for flags values
    // in that legacy range, but we need to OR in ImDrawFlags_ShadowCutOutShapeBackground (0x200),
    // which would otherwise push the combined value out of range and silently lose the corner mask.
    if (round_corner >= 0x01 && round_corner <= 0x0F)
        round_corner <<= 4;
    ImGui::GetWindowDrawList()->AddShadowRect(objMin, objMax, shadowColor, shadowThickness, shadowOffset, shadowFlag | round_corner, borderRadius);
}

void Rectangle::_drawShape(float elapsedTime, float x, float y, float width, float height)
{
    float dpiScale = this->getDpiScale();

    // The background color.
    uint32_t backgroundColor = 0xff000000;
    this->_resolveStyleProperty(this->getBackgroundColorProperty(), &backgroundColor);

    uint32_t backgroundGradientColor = backgroundColor;
    this->_resolveStyleProperty(StyleColorProperty::eBackgroundGradientColor, &backgroundGradientColor);

    // Determine which border we need.
    uint32_t borderColor = 0x0;
    this->_resolveStyleProperty(this->getBorderColorProperty(), &borderColor);

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
    }

    float borderRadius = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &borderRadius))
    {
        borderRadius *= dpiScale;
    }

    // ImDrawCornerFlags
    uint32_t round_corner = ImDrawFlags_RoundCornersAll;
    this->_resolveStyleProperty(StyleEnumProperty::eCornerFlag, &round_corner);

    ImVec2 start{ x, y };

    // Draw a rect
    ImVec2 rectMax{ start.x + width, start.y + height };

    if (backgroundColor != 0x0 && backgroundGradientColor != 0x0)
    {
        if (backgroundColor == backgroundGradientColor)
        {
            ImGui::GetWindowDrawList()->AddRectFilled(start, rectMax, backgroundColor, borderRadius, round_corner);
        }
        else
        {
            // TODO: ImGui doesn't have a way to draw a rect with gradient and rounded corner. The way to do it is
            // PrimReserve, PrimWriteIdx, PrimWriteVtx. We don't support it now.
            ImGui::GetWindowDrawList()->AddRectFilledMultiColor(
                start, rectMax, backgroundGradientColor, backgroundGradientColor, backgroundColor, backgroundColor);
        }
    }

    if (borderWidth > 0.0f && borderColor != 0x0)
    {
        if (backgroundColor != backgroundGradientColor)
        {
            borderRadius = 0.0f;
        }

        // Draw a border on top of rectangle.
        ImGui::GetWindowDrawList()->AddRect(start, rectMax, borderColor, borderRadius, round_corner, borderWidth);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
