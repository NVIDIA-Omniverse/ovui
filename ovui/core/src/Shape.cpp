/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "platform/Log.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Shape.h>
#include <omni/ui/StyleContainer.h>

#include "ShapeData.h"

#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

Shape::ShapeData::~ShapeData()
{
}

Shape::FreeShapeData::~FreeShapeData()
{
}

Shape::Shape(ShapeData* shapeData)
    : Widget(shapeData ? shapeData : new ShapeData)
{
}

Shape::~Shape() = default;

void Shape::_drawShapeShadow(float elapsedTime, float x, float y, float width, float height)
{
    // Get shadow style attribute
    uint32_t shadowColor = 0x0;
    this->_resolveStyleProperty(this->getShadowColorProperty(), &shadowColor);
    if (shadowColor == 0x0)
        return;

    float dpiScale = this->getDpiScale();

    float shadowOffsetX = 0.0f;
    this->_resolveStyleProperty(StyleFloatProperty::eShadowOffsetX, &shadowOffsetX);
    shadowOffsetX *= dpiScale;

    float shadowOffsetY = 0.0f;
    this->_resolveStyleProperty(StyleFloatProperty::eShadowOffsetY, &shadowOffsetY);
    shadowOffsetY *= dpiScale;

    ImVec2 shadowOffset{ shadowOffsetX, shadowOffsetY };

    float shadowThickness = 0.0f;
    this->_resolveStyleProperty(StyleFloatProperty::eShadowThickness, &shadowThickness);
    shadowThickness *= dpiScale;

    // ImDrawShadowFlags
    uint32_t shadowFlag = 0;
    this->_resolveStyleProperty(StyleEnumProperty::eShadowFlag, &shadowFlag);

    // omni.ui ShadowFlag::eCutOutShapeBackground == 1 matched old ImGui
    // ImDrawShadowFlags_CutOutShapeBackground (1<<0). In ImGui 1.92.7 the flag
    // moved into ImDrawFlags as ImDrawFlags_ShadowCutOutShapeBackground (1<<9),
    // so styles that set shadow_flag=1 must be remapped or the shadow would be
    // filled solid instead of hollow.
    constexpr uint32_t kLegacyCutOut = 1u;
    if (shadowFlag & kLegacyCutOut)
        shadowFlag = (shadowFlag & ~kLegacyCutOut) | ImDrawFlags_ShadowCutOutShapeBackground;

    this->_drawShadow(elapsedTime, x, y, width, height, shadowColor, dpiScale, shadowOffset, shadowThickness, shadowFlag);
}

void Shape::_drawContent(float elapsedTime)
{
    auto cursor = ImGui::GetCursorScreenPos();

    // Draw a rect
    float computedWidth = this->getComputedContentWidth();
    float computedHeight = this->getComputedContentHeight();

    // Cache these for use in other methods
    auto& data = _getData<ShapeData>();
    data.m_startPoint = { cursor.x, cursor.y };
    data.m_shapeSize = { computedWidth, computedHeight };

    this->_drawShapeShadow(elapsedTime, cursor.x, cursor.y, computedWidth, computedHeight);
    this->_drawShape(elapsedTime, cursor.x, cursor.y, computedWidth, computedHeight);
}

bool Shape::_intersects(float p1X, float p1Y, float p2X, float p2Y, float centerX, float centerY, float r)
{
    // Direction vector of ray, from start to end
    float dx = p2X - p1X;
    float dy = p2Y - p1Y;

    // Vector from center sphere to ray start
    float fx = p1X - centerX;
    float fy = p1Y - centerY;

    float a = dx * dx + dy * dy;
    float b = 2.0f * (fx * dx + fy * dy);
    float c = (fx * fx + fy * fy) - r * r;

    float discriminant = b * b - 4 * a * c;
    if (discriminant < 0.0f)
    {
        return false;
    }

    // ray didn't totally miss circle, so there is a solution to the equation.
    discriminant = sqrtf(discriminant);

    // either solution may be on or off the ray so need to test both t1 is always the smaller value, because BOTH
    // discriminant and a are nonnegative.
    float t1 = (-b - discriminant) / (2.0f * a);
    float t2 = (-b + discriminant) / (2.0f * a);

    if (t1 >= 0.0f && t1 <= 1.0f)
    {
        return true;
    }

    if (t2 >= 0.0f && t2 <= 1.0f)
    {
        return true;
    }

    return false;
}

void Shape::_makeFreeShape(std::shared_ptr<Widget> start, std::shared_ptr<Widget> end)
{
    if (!start || !end)
    {
        OMNIUI_LOG_ERROR("FreeShape bound to empty widgets, start: %p, end: %p", start.get(), end.get());
    }
    if (m_data)
    {
        m_data.reset(new FreeShapeData(_getData<ShapeData>(), std::move(start), std::move(end)));
    }
    else
    {
        m_data.reset(new FreeShapeData(std::move(start), std::move(end)));
    }
}

bool Shape::_getFreeShapeInfo(ImVec2& start,
                              ImVec2& size)
{
    auto& data = _getData<FreeShapeData>();
    auto startPointWidget = data.m_startPointWidget.lock();
    auto endPointWidget = data.m_endPointWidget.lock();
    if (!startPointWidget || !endPointWidget)
    {
        return false;
    }

    // Shape bound corners. 0.5 to have the point in the middle of the widget.
    float startX = startPointWidget->getScreenPositionX() + startPointWidget->getComputedWidth() * 0.5f;
    float startY = startPointWidget->getScreenPositionY() + startPointWidget->getComputedHeight() * 0.5f;
    float endX = endPointWidget->getScreenPositionX() + endPointWidget->getComputedWidth() * 0.5f;
    float endY = endPointWidget->getScreenPositionY() + endPointWidget->getComputedHeight() * 0.5f;

    data.m_bbox.min[0] = std::min(startX, endX) - this->getScreenPositionX();
    data.m_bbox.min[1] = std::min(startY, endY) - this->getScreenPositionY();
    data.m_bbox.max[0] = std::max(startX, endX) - this->getScreenPositionX();
    data.m_bbox.max[1] = std::max(startY, endY) - this->getScreenPositionY();

    // Cache these for use in other methods
    data.m_startPoint = { startX, startY };
    data.m_shapeSize = { endX - startX, endY - startY };

    start = data.m_startPoint;
    size = data.m_shapeSize;
    return true;
}

Widget::BoundingBox Shape::_getFreeShapeInteractionBBox() const
{
    return _getData<FreeShapeData>().m_bbox;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
