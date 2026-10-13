/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>

#include <omni/ui/TimelinePlot.h>
#include <omni/ui/BoundedText.h>

#include "WidgetData.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

constexpr float kGoldenRatioConjugate = 0.61803398875f;
constexpr float kMinimumDurationLabelWidth = 40.0f;
using boundedtext::StaticString64;
using boundedtext::StaticString256;

ImU32 timelineColor(uint32_t colorIndex)
{
    const float hue = std::fmod(static_cast<float>(colorIndex) * kGoldenRatioConjugate, 1.0f);
    float red = 0.0f;
    float green = 0.0f;
    float blue = 0.0f;
    ImGui::ColorConvertHSVtoRGB(hue, 0.65f, 0.95f, red, green, blue);
    return ImGui::ColorConvertFloat4ToU32(ImVec4(red, green, blue, 1.0f));
}

ImU32 timelineTextColor(ImU32 background)
{
    const ImVec4 color = ImGui::ColorConvertU32ToFloat4(background);
    const float luminance = color.x * 0.299f + color.y * 0.587f + color.z * 0.114f;
    return luminance >= 0.55f ? IM_COL32(24, 24, 24, 255) : IM_COL32(245, 245, 245, 255);
}

void drawCenteredTooltipLine(const char* text, size_t textLength, float contentWidth)
{
    const char* textEnd = text + textLength;
    const float lineWidth = ImGui::CalcTextSize(text, textEnd).x;
    ImGui::SetCursorPosX(ImGui::GetCursorPosX() + std::max((contentWidth - lineWidth) * 0.5f, 0.0f));
    ImGui::TextUnformatted(text, textEnd);
}

StaticString64 formatTimelineNumber(double value, bool appendMilliseconds = false)
{
    StaticString64 result;
    if (!std::isfinite(value))
    {
        result.addText("-", 1);
        return result;
    }
    char valueText[boundedtext::kSmallStringMaxSize]{};
    const int written = std::snprintf(valueText, sizeof(valueText), "%.6f", value);
    result.addText(valueText, written > 0 ? static_cast<uint32_t>((std::min)(written, int(sizeof(valueText) - 1))) : 0U);
    while (!result.empty() && result.back() == '0')
        result.popBack();
    if (!result.empty() && result.back() == '.')
        result.popBack();
    if (result.empty() || (result.size() == 2 && result.text()[0] == '-' && result.text()[1] == '0'))
    {
        result.clear();
        result.addText("0", 1);
    }
    if (appendMilliseconds)
        result += " ms";
    return result;
}

} // namespace

struct TimelinePlot::TimelinePlotData : public Widget::WidgetData
{
    TimelinePlotDataView view;
    std::vector<StaticString256> ownedLabelText;
    std::vector<TimelineLabelView> ownedLabelViews;
    std::vector<uint32_t> ownedGroupRows;
    std::vector<TimelineInterval> ownedIntervals;
    double startSeconds = 0.0;
    double endSeconds = 1.0;
};

TimelinePlot::TimelinePlot() : Widget(new TimelinePlotData)
{
    this->setStyleTypeNameOverride("TimelinePlot");
}

TimelinePlot::~TimelinePlot() = default;

void TimelinePlot::setData(const TimelinePlotDataView& view)
{
    auto& data = _getData<TimelinePlotData>();
    data.view = view;
    if (!data.view.laneLabels)
        data.view.laneLabelCount = 0;
    if (!data.view.groupRows)
        data.view.groupRowCount = 0;
    if (!data.view.intervals)
        data.view.intervalCount = 0;
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void TimelinePlot::setDataCopy(const TimelinePlotDataView& view)
{
    auto& data = _getData<TimelinePlotData>();
    const size_t labelCount = view.laneLabels ? view.laneLabelCount : 0;
    const size_t groupCount = view.groupRows ? view.groupRowCount : 0;
    const size_t intervalCount = view.intervals ? view.intervalCount : 0;

    if (data.ownedLabelText.capacity() < labelCount)
        data.ownedLabelText.reserve(labelCount);
    if (data.ownedLabelViews.capacity() < labelCount)
        data.ownedLabelViews.reserve(labelCount);
    data.ownedLabelText.resize(labelCount);
    data.ownedLabelViews.resize(labelCount);
    for (size_t index = 0; index < labelCount; ++index)
    {
        data.ownedLabelText[index].clear();
        const size_t labelLength = (std::min)(view.laneLabels[index].length,
                                               size_t{ boundedtext::kRegularStringMaxSize - 1 });
        data.ownedLabelText[index].addText(view.laneLabels[index].text, static_cast<uint32_t>(labelLength));
        data.ownedLabelViews[index] = {
            data.ownedLabelText[index].text(),
            data.ownedLabelText[index].size(),
        };
    }
    if (data.ownedGroupRows.capacity() < groupCount)
        data.ownedGroupRows.reserve(groupCount);
    if (groupCount)
        data.ownedGroupRows.assign(view.groupRows, view.groupRows + groupCount);
    else
        data.ownedGroupRows.clear();
    if (data.ownedIntervals.capacity() < intervalCount)
        data.ownedIntervals.reserve(intervalCount);
    if (intervalCount)
        data.ownedIntervals.assign(view.intervals, view.intervals + intervalCount);
    else
        data.ownedIntervals.clear();
    data.view = {
        data.ownedLabelViews.data(),
        data.ownedLabelViews.size(),
        data.ownedGroupRows.data(),
        data.ownedGroupRows.size(),
        data.ownedIntervals.data(),
        data.ownedIntervals.size(),
    };
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void TimelinePlot::setTimeRange(double startSeconds, double endSeconds)
{
    auto& data = _getData<TimelinePlotData>();
    data.startSeconds = std::isfinite(startSeconds) ? startSeconds : 0.0;
    data.endSeconds = std::isfinite(endSeconds) ? endSeconds : data.startSeconds + 1.0;
    if (data.endSeconds <= data.startSeconds)
    {
        data.endSeconds = data.startSeconds + 1.0e-6;
    }
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void TimelinePlot::setComputedContentWidth(float width)
{
    Widget::setComputedContentWidth(std::max(width, 1.0f));
}

void TimelinePlot::setComputedContentHeight(float height)
{
    Widget::setComputedContentHeight(std::max(height, 1.0f));
}

void TimelinePlot::_drawContent(float)
{
    auto& data = _getData<TimelinePlotData>();
    const ImVec2 cursor = ImGui::GetCursorScreenPos();
    const ImVec2 size(this->getComputedContentWidth(), this->getComputedContentHeight());
    if (size.x <= 0.0f || size.y <= 0.0f)
    {
        return;
    }

    const float dpiScale = this->getDpiScale();
    const float laneHeight = std::max(this->getLaneHeight(), 1.0f) * dpiScale;
    const double visibleDuration = data.endSeconds - data.startSeconds;
    ImDrawList* drawList = ImGui::GetWindowDrawList();
    const ImVec2 bottomRight(cursor.x + size.x, cursor.y + size.y);
    drawList->PushClipRect(cursor, bottomRight, true);

    for (size_t laneIndex = 0; laneIndex < data.view.laneLabelCount; ++laneIndex)
    {
        const float y0 = cursor.y + static_cast<float>(laneIndex) * laneHeight;
        const float y1 = std::min(y0 + laneHeight, bottomRight.y);
        const ImU32 background = laneIndex % 2 == 0 ? IM_COL32(32, 34, 37, 255) : IM_COL32(41, 43, 47, 255);
        drawList->AddRectFilled(ImVec2(cursor.x, y0), ImVec2(bottomRight.x, y1), background);
    }

    for (size_t groupIndex = 0; groupIndex < data.view.groupRowCount; ++groupIndex)
    {
        const uint32_t groupRow = data.view.groupRows[groupIndex];
        if (groupRow >= data.view.laneLabelCount)
        {
            continue;
        }
        const float y0 = cursor.y + static_cast<float>(groupRow) * laneHeight;
        const float y1 = std::min(y0 + laneHeight, bottomRight.y);
        drawList->AddRectFilled(ImVec2(cursor.x, y0), ImVec2(bottomRight.x, y1), IM_COL32(50, 52, 57, 255));
        drawList->AddLine(ImVec2(cursor.x, y0), ImVec2(bottomRight.x, y0), IM_COL32(118, 185, 0, 255), dpiScale);
    }

    for (uint32_t markerIndex = 0; markerIndex <= 4; ++markerIndex)
    {
        const float x = cursor.x + size.x * static_cast<float>(markerIndex) / 4.0f;
        drawList->AddLine(ImVec2(x, cursor.y), ImVec2(x, bottomRight.y), IM_COL32(80, 82, 86, 128), dpiScale);
    }

    const ImVec2 mousePosition = ImGui::GetMousePos();
    size_t hoveredInterval = std::numeric_limits<size_t>::max();
    for (size_t intervalIndex = 0; intervalIndex < data.view.intervalCount; ++intervalIndex)
    {
        const TimelineInterval& interval = data.view.intervals[intervalIndex];
        if (interval.laneIndex >= data.view.laneLabelCount || !std::isfinite(interval.startSeconds) ||
            !std::isfinite(interval.durationMilliseconds))
        {
            continue;
        }
        const double intervalEnd = interval.startSeconds + std::max(interval.durationMilliseconds, 0.0) * 0.001;
        if (intervalEnd < data.startSeconds || interval.startSeconds > data.endSeconds)
        {
            continue;
        }
        const double clippedStart = std::max(interval.startSeconds, data.startSeconds);
        const double clippedEnd = std::min(intervalEnd, data.endSeconds);
        float x0 = cursor.x + size.x * static_cast<float>((clippedStart - data.startSeconds) / visibleDuration);
        float x1 = cursor.x + size.x * static_cast<float>((clippedEnd - data.startSeconds) / visibleDuration);
        x0 = std::clamp(x0, cursor.x, bottomRight.x);
        x1 = std::clamp(x1, cursor.x, bottomRight.x);
        if (x1 <= x0 && x0 < bottomRight.x)
        {
            x1 = std::min(x0 + dpiScale, bottomRight.x);
        }
        const float laneTop = cursor.y + static_cast<float>(interval.laneIndex) * laneHeight;
        const float inset = std::min(4.0f * dpiScale, laneHeight * 0.25f);
        const ImVec2 rectangleMin(x0, laneTop + inset);
        const ImVec2 rectangleMax(x1, std::min(laneTop + laneHeight - inset, bottomRight.y));
        const ImU32 background = timelineColor(interval.colorIndex);
        drawList->AddRectFilled(rectangleMin, rectangleMax, background, 2.0f * dpiScale);
        if (rectangleMax.x - rectangleMin.x >= kMinimumDurationLabelWidth * dpiScale)
        {
            const StaticString64 durationText = formatTimelineNumber(interval.durationMilliseconds);
            const ImVec2 textSize = ImGui::CalcTextSize(durationText.text());
            const ImVec2 textPosition(
                rectangleMin.x + (rectangleMax.x - rectangleMin.x - textSize.x) * 0.5f,
                rectangleMin.y + (rectangleMax.y - rectangleMin.y - textSize.y) * 0.5f);
            drawList->PushClipRect(rectangleMin, rectangleMax, true);
            drawList->AddText(textPosition, timelineTextColor(background), durationText.text());
            drawList->PopClipRect();
        }
        if (ImRect(rectangleMin, rectangleMax).Contains(mousePosition))
        {
            hoveredInterval = intervalIndex;
        }
    }
    drawList->PopClipRect();

    if (hoveredInterval < data.view.intervalCount && ImRect(cursor, bottomRight).Contains(mousePosition) &&
        ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows | ImGuiHoveredFlags_AllowWhenBlockedByActiveItem))
    {
        const TimelineInterval& interval = data.view.intervals[hoveredInterval];
        const TimelineLabelView& label = data.view.laneLabels[interval.laneIndex];
        const char* functionName = label.text ? label.text : "";
        const size_t functionNameLength = label.text ? label.length : 0;
        const StaticString64 durationText = formatTimelineNumber(interval.durationMilliseconds, true);
        const float contentWidth = std::max(
            ImGui::CalcTextSize(functionName, functionName + functionNameLength).x,
            ImGui::CalcTextSize(durationText.text()).x);
        ImGui::BeginTooltip();
        drawCenteredTooltipLine(functionName, functionNameLength, contentWidth);
        drawCenteredTooltipLine(durationText.text(), durationText.size(), contentWidth);
        ImGui::EndTooltip();
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
