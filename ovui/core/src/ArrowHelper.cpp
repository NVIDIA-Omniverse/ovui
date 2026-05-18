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
#include <omni/ui/StyleContainer.h>

#include <algorithm>
#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The filling and alignment logic. It takes the canvas and returns the offset and the size of the new
 * canvas that contains aligned circle.
 *
 * @param dpiScale Input. The dpi scale
 * @param arrowWidth Input. Width of the arrow
 * @param arrowHeight Input. Height of the arrow
 * @param start Input. Input point of the arrow
 * @param end Input. Input point of the arrow
 * @param p1 Output. left point of the arrow's triangle
 * @param p2 Output. right point of the arrow's triangle
 */

static void alignArrow(float lineWidth,
                       float dpiScale,
                       float arrowWidth,
                       float arrowHeight,
                       const ImVec2& start,
                       const ImVec2& end,
                       ImVec2& p1,
                       ImVec2& p2,
                       ImVec2& p3)
{
    float w = end.x - start.x;
    float h = end.y - start.y;
    if (std::fabs(w) < 0.01f && std::fabs(h) < 0.01f)
    {
        p1.x = start.x;
        p1.y = start.y;

        p2.x = start.x;
        p2.y = start.y;

        p3.x = end.x;
        p3.y = end.y;
        return;
    }

    float len = sqrt(w * w + h * h);
    float lenRecip = 1 / len;
    float mx = end.x - std::min(len, dpiScale * arrowHeight) * w * lenRecip;
    float my = end.y - std::min(len, dpiScale * arrowHeight) * h * lenRecip;
    float dx = std::min(len / 2, dpiScale * arrowWidth / 2) * h * lenRecip;
    float dy = std::min(len / 2, dpiScale * arrowWidth / 2) * w * lenRecip;

    p1.x = mx + dx;
    p1.y = my - dy;

    p2.x = mx - dx;
    p2.y = my + dy;
    p3.x = end.x + lineWidth * w * lenRecip;
    p3.y = end.y + lineWidth * h * lenRecip;
}

ArrowHelper::ArrowHelper() = default;

ArrowHelper::~ArrowHelper() = default;

void ArrowHelper::drawArrow(float x,
                            float y,
                            float width,
                            float height,
                            float dpi,
                            float lineWidth,
                            float arrowWidth,
                            float arrowHeight,
                            uint32_t color)
{
    ImVec2 start{ x, y };
    ImVec2 end{ x + width, y + height };
    ImVec2 p3, p4, p5;
    alignArrow(lineWidth, dpi, arrowWidth, arrowHeight, start, end, p3, p4, p5);

    if (lineWidth > 0.0f && color != 0x0)
    {
        ImGui::GetWindowDrawList()->AddTriangleFilled(p3, p4, p5, color);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
