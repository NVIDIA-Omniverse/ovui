/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#define _USE_MATH_DEFINES
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Plot.h>
#include <omni/ui/StyleContainer.h>

#include "WidgetData.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iomanip>
#include <limits>
#include <sstream>

OMNIUI_NAMESPACE_OPEN_SCOPE


namespace
{

std::string formatPlotNumber(double value)
{
    if (!std::isfinite(value))
    {
        return "-";
    }

    const double magnitude = std::abs(value);
    int precision = 3;
    double displayValue = value;
    bool trimTrailingZeroes = true;
    if (magnitude > 0.0 && magnitude < 0.0001)
    {
        displayValue = value < 0.0 ? -0.0001 : 0.0001;
        precision = 4;
        trimTrailingZeroes = false;
    }
    else if (magnitude < 0.01)
    {
        displayValue = std::trunc(value * 10000.0) / 10000.0;
        precision = 4;
        trimTrailingZeroes = false;
    }
    else if (magnitude >= 10000.0)
    {
        precision = 0;
        trimTrailingZeroes = false;
    }

    std::ostringstream stream;
    stream << std::fixed << std::setprecision(precision) << displayValue;
    std::string text = stream.str();
    if (trimTrailingZeroes && text.find('.') != std::string::npos)
    {
        while (!text.empty() && text.back() == '0')
        {
            text.pop_back();
        }
        if (!text.empty() && text.back() == '.')
        {
            text.pop_back();
        }
    }
    return text;
}

// Keep all plot geometry in the current ovui window and draw list.
void validRange(double& minimum, double& maximum)
{
    if (!std::isfinite(minimum) || !std::isfinite(maximum))
    {
        minimum = 0.0;
        maximum = 1.0;
    }
    if (minimum > maximum)
        std::swap(minimum, maximum);
    if (maximum == minimum)
    {
        const double margin = std::max(std::abs(minimum) * 0.01, 0.5);
        minimum -= margin;
        maximum += margin;
    }
}

struct PlotTick
{
    double value;
    std::string label;
    bool major;
};

std::vector<PlotTick> plotTicks(double minimum, double maximum, float pixels, bool vertical,
                                const std::string& format = {})
{
    std::vector<PlotTick> ticks;
    const double span = maximum - minimum;
    if (!(span > 0.0) || !std::isfinite(span))
        return ticks;
    // Choose a decimal grid with enough room for the tick labels.
    // Round the span up to a decimal interval before choosing the grid step.
    // This also keeps a fixed value range on the same integer Y ticks.
    const double spanDecade = std::pow(10.0, std::floor(std::log10(span * 0.99)));
    const double spanFraction = span * 0.99 / spanDecade;
    const double roundedSpan = (spanFraction <= 1.0 ? 1.0 : spanFraction <= 2.0 ? 2.0 :
                                spanFraction <= 5.0 ? 5.0 : 10.0) * spanDecade;
    const double target = roundedSpan / std::max(1.0f, std::round(pixels / (vertical ? 300.0f : 400.0f)) - 1.0f);
    const double decade = std::pow(10.0, std::floor(std::log10(target)));
    const double fraction = target / decade;
    const double majorStep = (fraction < 1.5 ? 1.0 : fraction < 3.0 ? 2.0 : fraction < 7.0 ? 5.0 : 10.0) * decade;
    const double step = majorStep / 10.0;
    if (!(step > 0.0) || !std::isfinite(step))
        return ticks;
    const double first = std::ceil(minimum / step);
    const int count = std::min(200, int(std::ceil(span / step)) + 1);
    const int precision = std::clamp(int(-std::floor(std::log10(step))), 0, 10);
    float labelExtent = 0.0f;
    for (int index = 0; index < count; ++index)
    {
        const double value = (first + index) * step;
        if (value > maximum + step * 1.0e-6)
            break;
        char label[128];
        const double rounded = std::abs(value) < step * 1.0e-6 ? 0.0 : value;
        if (!format.empty())
            std::snprintf(label, sizeof(label), format.c_str(), rounded);
        else
            std::snprintf(label, sizeof(label), "%.*f", precision, rounded);
        if (format.empty() && precision > 0)
        {
            size_t length = std::char_traits<char>::length(label);
            while (length && label[length - 1] == '0')
                label[--length] = '\0';
            if (length && label[length - 1] == '.')
                label[--length] = '\0';
        }
        const ImVec2 extent = ImGui::CalcTextSize(label);
        labelExtent += vertical ? extent.y : extent.x;
        ticks.push_back({ value, label, std::abs(std::remainder(value, majorStep)) < step * 1.0e-6 });
    }
    // Hide alternate minor labels on small plots, but keep their grid lines.
    if (labelExtent > pixels * (vertical ? 1.0f : 0.8f))
        for (auto& tick : ticks)
            if (!tick.major && std::abs(std::remainder(tick.value, 2.0 * step)) > step * 0.5)
                tick.label.clear();
    // Measure the labels that remain. Keep grid ticks even when their text must
    // be hidden. Major labels have priority over minor labels.
    std::vector<std::pair<float, float>> occupied;
    for (bool major : { true, false })
        for (auto& tick : ticks)
        {
            if (tick.major != major || tick.label.empty())
                continue;
            const ImVec2 extent = ImGui::CalcTextSize(tick.label.c_str());
            const float center = float((tick.value - minimum) / span) * pixels;
            const float half = (vertical ? extent.y : extent.x) * 0.5f;
            const std::pair<float, float> interval(center - half, center + half);
            const float gap = ImGui::GetFontSize() * (vertical ? 0.2f : 0.5f);
            const bool overlaps = std::any_of(occupied.begin(), occupied.end(), [&](const auto& other) {
                return interval.first < other.second + gap && interval.second + gap > other.first;
            });
            if (overlaps)
                tick.label.clear();
            else
                occupied.push_back(interval);
        }
    return ticks;
}

struct PlotAxisOptions
{
    bool lockMin = false;
    bool lockMax = false;
    bool autoFit = false;
    bool invert = false;
    bool opposite = false;
    bool label = true;
    bool gridLines = true;
    bool tickMarks = true;
    bool tickLabels = true;
};

bool plotAxisMenu(PlotAxisOptions& axis, double& minimum, double& maximum, bool fixed, bool hasLabel)
{
    const double speed = std::max((maximum - minimum) * 0.01, std::numeric_limits<double>::epsilon());
    bool rangeChanged = false;
    const double lower = -std::numeric_limits<double>::max();
    const double upper = std::numeric_limits<double>::max();
    const double minUpper = std::nextafter(maximum, lower);
    const double maxLower = std::nextafter(minimum, upper);
    ImGui::PushItemWidth(75.0f);
    for (int endpoint = 0; endpoint < 2; ++endpoint)
    {
        bool& lock = endpoint ? axis.lockMax : axis.lockMin;
        ImGui::PushID(endpoint);
        ImGui::BeginDisabled(fixed || axis.autoFit);
        ImGui::Checkbox("##lock", &lock);
        ImGui::EndDisabled();
        ImGui::SameLine();
        ImGui::BeginDisabled(fixed || axis.autoFit || lock);
        rangeChanged |= ImGui::DragScalar(endpoint ? "Max" : "Min", ImGuiDataType_Double,
                          endpoint ? &maximum : &minimum, float(speed),
                          endpoint ? &maxLower : &lower, endpoint ? &upper : &minUpper,
                          "%.3g", ImGuiSliderFlags_AlwaysClamp);
        ImGui::EndDisabled();
        ImGui::PopID();
    }
    ImGui::PopItemWidth();
    ImGui::Separator();
    ImGui::Checkbox("Auto-Fit", &axis.autoFit);
    ImGui::Separator();
    ImGui::Checkbox("Invert", &axis.invert);
    ImGui::Checkbox("Opposite", &axis.opposite);
    ImGui::Separator();
    ImGui::BeginDisabled(!hasLabel);
    ImGui::Checkbox("Label", &axis.label);
    ImGui::EndDisabled();
    ImGui::Checkbox("Grid Lines", &axis.gridLines);
    ImGui::Checkbox("Tick Marks", &axis.tickMarks);
    ImGui::Checkbox("Tick Labels", &axis.tickLabels);
    return rangeChanged;
}

ImU32 plotAlpha(ImU32 color, float alpha)
{
    ImVec4 value = ImGui::ColorConvertU32ToFloat4(color);
    value.w *= alpha;
    return ImGui::ColorConvertFloat4ToU32(value);
}

void verticalPlotText(ImDrawList* drawList, ImVec2 position, ImU32 color, const char* text)
{
    const float width = ImGui::CalcTextSize(text).x;
    const int firstVertex = drawList->VtxBuffer.Size;
    drawList->AddText(position, color, text);
    for (int index = firstVertex; index < drawList->VtxBuffer.Size; ++index)
    {
        ImVec2& vertex = drawList->VtxBuffer[index].pos;
        const ImVec2 offset(vertex.x - position.x, vertex.y - position.y);
        vertex = ImVec2(position.x + offset.y, position.y + width - offset.x);
    }
}

} // namespace

struct Plot::PlotData : public Widget::WidgetData
{
    PlotData(Plot::PlotData1D valueList) : m_plotData(std::move(valueList))
    {
        m_yValues.assign(m_plotData.begin(), m_plotData.end());
    }
    PlotData(Plot::PlotData2D valueList) : m_plotXYData(std::move(valueList))
    {
        for (const auto& value : m_plotXYData)
        {
            m_xValues.push_back(value.first);
            m_yValues.push_back(value.second);
        }
    }
    PlotData(Samples1D valueList) : m_yValues(std::move(valueList))
    {
        m_plotData.assign(m_yValues.begin(), m_yValues.end());
    }
    ~PlotData() override = default;

    Plot::PlotData1D m_plotData;
    Plot::PlotData2D m_plotXYData;
    float m_prevWidth = 0;

    Samples1D m_xValues;
    Samples1D m_yValues;
    bool m_fitNext = true;
    bool m_hasAxisLimits = false;
    double m_xMin = 0.0;
    double m_xMax = 1.0;
    double m_yMin = 0.0;
    double m_yMax = 1.0;
    bool m_showSeries = true;
    PlotAxisOptions m_xAxis;
    PlotAxisOptions m_yAxis;
    bool m_previousAutoFit = false;
    bool m_dragX = false;
    bool m_dragY = false;
    bool m_boxSelect = true;
    bool m_equal = false;
    bool m_legendOutside = false;
    bool m_legendHorizontal = false;
    int m_legendLocation = 0; // NW, N, NE, W, E, SW, S, SE
    bool m_selecting = false;
    ImVec2 m_selectionStart;
    bool m_histogramDirty = true;
    Samples2D m_histogram;
    double m_binWidth = 1.0;
};


Plot::Plot(Type type, float scaleMin, float scaleMax, PlotData1D valueList)
    : Widget(new PlotData(std::move(valueList)))
{
    this->setType(type);
    this->setScaleMin(scaleMin);
    this->setScaleMax(scaleMax);

    this->setStyleTypeNameOverride("Plot");
}

Plot::Plot(Type type, float scaleMin, float scaleMax, PlotData2D valueList)
    : Widget(new PlotData(std::move(valueList)))
{
    this->setType(type);
    this->setScaleMin(scaleMin);
    this->setScaleMax(scaleMax);

    this->setStyleTypeNameOverride("Plot");
}


Plot::Plot(Type type, Mode mode, Samples1D valueList, float scaleMin, float scaleMax)
    : Widget(new PlotData(std::move(valueList)))
{
    this->setType(type);
    this->setMode(mode);
    this->setScaleMin(scaleMin);
    this->setScaleMax(scaleMax);
    this->setStyleTypeNameOverride("Plot");
}

Plot::~Plot() = default;

void Plot::setComputedContentHeight(float height)
{
    Widget::setComputedContentHeight(std::max(height, 0.0f));
}

void Plot::_drawContent(float elapsedTime)
{
    if (this->getMode() == Mode::eInteractive)
    {
        _drawInteractiveContent();
        return;
    }

    auto& data = _getData< PlotData>();

    // If there is no data, do not draw anything
    // If the type is Line2D and there is no XY data, do not draw anything
    // If the type is Line or Histogram and there is no data, do not draw anything
    if ((data.m_plotData.empty() && data.m_plotXYData.empty())
        || (this->getType() == Type::eLine2D && data.m_plotXYData.empty())
        || ((this->getType() == Type::eLine || this->getType() == Type::eHistogram) && data.m_plotData.empty()))
    {
        return;
    }

    float dpiScale = this->getDpiScale();

    uint32_t popColorCount = 0;
    uint32_t pushedFloatCount = 0;
    uint32_t color;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_FrameBg, color);
        popColorCount++;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &color))
    {
        if (this->getType() == Type::eLine || this->getType() == Type::eLine2D)
        {
            ImGui::PushStyleColor(ImGuiCol_PlotLines, color);
        }
        else
        {
            ImGui::PushStyleColor(ImGuiCol_PlotHistogram, color);
        }
        popColorCount++;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eSelectedColor, &color))
    {
        if (this->getType() == Type::eLine || this->getType() == Type::eLine2D)
        {
            ImGui::PushStyleColor(ImGuiCol_PlotLinesHovered, color);
        }
        else
        {
            ImGui::PushStyleColor(ImGuiCol_PlotHistogramHovered, color);
        }
        popColorCount++;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &color))
    {
        // color for title and tooltip texts
        ImGui::PushStyleColor(ImGuiCol_Border, color);
        popColorCount++;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundSelectedColor, &color))
    {
        // color for tooltip background
        ImGui::PushStyleColor(ImGuiCol_PopupBg, color);
        popColorCount++;
    }

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
        ImGui::PushStyleVar(ImGuiStyleVar_FrameBorderSize, borderWidth);
        pushedFloatCount++;
    }

    float borderRadius = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &borderRadius))
    {
        borderRadius *= dpiScale;
        ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, borderRadius);
        pushedFloatCount++;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &color))
    {
        // color for title and tooltip texts
        ImGui::PushStyleColor(ImGuiCol_Text, color);
        popColorCount++;
    }

    float padding = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= this->getDpiScale();
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
        pushedFloatCount++;
    }

    ImVec2 canvasSize(this->getComputedContentWidth(), this->getComputedContentHeight());
    ImVec2 cursor = ImGui::GetCursorScreenPos();

    int stride = this->getValueStride() < 1 ? 1 : this->getValueStride();
    int valuesCount = static_cast<int>(data.m_plotData.size() / stride);
    if (this->getType() == Type::eLine2D)
    {
        float computedWidth = this->getComputedContentWidth();
        if (computedWidth != data.m_prevWidth)
        {
            data.m_prevWidth = computedWidth;
            data.m_plotData.clear();

            size_t width = (size_t)computedWidth;

            float dataMin = data.m_plotXYData.front().first;
            float dataMax = data.m_plotXYData.back().first;
            float stepWidth = (dataMax - dataMin) / (float)width;
            float dataCounter = dataMin;
            size_t dataIndex = 0;

            size_t counter = 0;
            while (counter < width)
            {
                while (dataCounter >= data.m_plotXYData[dataIndex + 1].first && dataIndex < (data.m_plotXYData.size() - 1))
                {
                    dataIndex++;
                }

                if (dataIndex > (data.m_plotXYData.size() - 1))
                {
                    break;
                }

                float valuePrev = data.m_plotXYData[dataIndex].second;
                float valueNext = data.m_plotXYData[dataIndex + 1].second;
                float posPrev = data.m_plotXYData[dataIndex].first;
                float posNext = data.m_plotXYData[dataIndex + 1].first;
                float weight = (dataCounter - posPrev) / (posNext - posPrev);

                data.m_plotData.push_back(valuePrev * (1.0f - weight) + valueNext * weight);

                counter++;
                dataCounter += stepWidth;
            }
        }

        ImGui::PlotLines("##hidelabel", &data.m_plotData[0], valuesCount, this->getValueOffset(), this->getTitle().c_str(),
                         this->getScaleMin(), this->getScaleMax(),
                         ImVec2(this->getComputedContentWidth(), this->getComputedContentHeight()),
                         sizeof(float) * stride);
    }
    else if (this->getType() == Type::eLine)
    {
        ImGui::PlotLines("##hidelabel", &data.m_plotData[0], valuesCount, this->getValueOffset(), this->getTitle().c_str(),
                         this->getScaleMin(), this->getScaleMax(),
                         ImVec2(this->getComputedContentWidth(), this->getComputedContentHeight()),
                         sizeof(float) * stride);
    }
    else if (this->getType() == Type::eHistogram)
    {
        ImGui::PlotHistogram("##hidelabel", &data.m_plotData[0], valuesCount, this->getValueOffset(),
                             this->getTitle().c_str(), this->getScaleMin(), this->getScaleMax(),
                             ImVec2(this->getComputedContentWidth(), this->getComputedContentHeight()),
                             sizeof(float) * stride);
    }

    ImGui::PopStyleColor(popColorCount);
    ImGui::PopStyleVar(pushedFloatCount);
}

void Plot::setDataProviderFn(std::function<float(int)> fn, int valuesCount)
{
    auto dataProviderFn = std::move(fn);
    std::vector<float> valueList;
    valueList.reserve(valuesCount);
    if (dataProviderFn)
    {
        for (int i = 0; i < valuesCount; i++)
        {
            valueList.push_back(dataProviderFn(i));
        }
    }
    setData(valueList);
}

void Plot::setData(PlotData1D valueList)
{
    auto& data = _getData<PlotData>();
    data.m_xValues.clear();
    data.m_yValues.assign(valueList.begin(), valueList.end());
    data.m_histogramDirty = true;
    data.m_plotData = std::move(valueList);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Plot::setXYData(PlotData2D valueList)
{
    auto& data = _getData<PlotData>();
    data.m_xValues.clear();
    data.m_yValues.clear();
    for (const auto& value : valueList)
    {
        data.m_xValues.push_back(value.first);
        data.m_yValues.push_back(value.second);
    }
    data.m_histogramDirty = true;
    data.m_plotXYData = std::move(valueList);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Plot::_drawInteractiveContent()
{
    auto& data = _getData<PlotData>();
    const ImVec2 origin = ImGui::GetCursorScreenPos();
    const ImVec2 size(this->getComputedContentWidth(), this->getComputedContentHeight());
    if (data.m_yValues.empty() || size.x <= 0.0f || size.y <= 0.0f)
        return;

    const bool histogram = this->getType() == Type::eHistogram;
    const bool bars = histogram || this->getType() == Type::eBars;
    const bool hasXValues = data.m_xValues.size() == data.m_yValues.size();
    if (histogram && data.m_histogramDirty)
    {
        double minimum = std::numeric_limits<double>::infinity();
        double maximum = -minimum;
        size_t count = 0;
        for (double value : data.m_yValues)
            if (std::isfinite(value))
            {
                minimum = std::min(minimum, value);
                maximum = std::max(maximum, value);
                ++count;
            }
        if (!count)
            minimum = maximum = 0.0;
        const size_t bins = maximum == minimum ? 1 : size_t(std::ceil(std::log2(double(count)))) + 1;
        data.m_binWidth = (maximum - minimum) / double(bins);
        data.m_histogram.resize(bins);
        for (size_t index = 0; index < bins; ++index)
            data.m_histogram[index] = { minimum + (double(index) + 0.5) * data.m_binWidth, 0.0 };
        for (double value : data.m_yValues)
            if (std::isfinite(value))
            {
                const size_t index = data.m_binWidth == 0.0 ? 0 :
                    std::min(bins - 1, size_t((value - minimum) / data.m_binWidth));
                data.m_histogram[index].second += 1.0;
            }
        data.m_histogramDirty = false;
    }
    const size_t count = histogram ? data.m_histogram.size() : data.m_yValues.size();
    const auto sample = [&](size_t index) {
        return histogram ? data.m_histogram[index] :
            std::make_pair(hasXValues ? data.m_xValues[index] : double(index), data.m_yValues[index]);
    };
    const double barWidth = histogram ? data.m_binWidth : 0.67;
    if (data.m_previousAutoFit != this->isAutoFit())
    {
        data.m_xAxis.autoFit = data.m_yAxis.autoFit = this->isAutoFit();
        data.m_previousAutoFit = this->isAutoFit();
    }
    const auto setRange = [&](PlotAxisOptions& axis, double& minimum, double& maximum, double a, double b) {
        if (data.m_hasAxisLimits)
            return;
        if (!axis.lockMin)
            minimum = std::min(a, std::nextafter(axis.lockMax ? maximum : b, -std::numeric_limits<double>::infinity()));
        if (!axis.lockMax)
            maximum = std::max(b, std::nextafter(minimum, std::numeric_limits<double>::infinity()));
    };
    const auto fitData = [&](bool fitX, bool fitY) {
        double xMin = std::numeric_limits<double>::infinity();
        double yMin = xMin;
        double xMax = -xMin;
        double yMax = -xMin;
        for (size_t index = 0; index < count; ++index)
        {
            const auto point = sample(index);
            if (!std::isfinite(point.first) || !std::isfinite(point.second))
                continue;
            xMin = std::min(xMin, point.first - (bars ? barWidth * 0.5 : 0.0));
            xMax = std::max(xMax, point.first + (bars ? barWidth * 0.5 : 0.0));
            yMin = std::min(yMin, bars ? std::min(0.0, point.second) : point.second);
            yMax = std::max(yMax, bars ? std::max(0.0, point.second) : point.second);
        }
        validRange(xMin, xMax);
        validRange(yMin, yMax);
        if (fitX)
            setRange(data.m_xAxis, data.m_xMin, data.m_xMax, xMin, xMax);
        if (fitY)
            setRange(data.m_yAxis, data.m_yMin, data.m_yMax, yMin, yMax);
        data.m_fitNext = false;
    };
    if (!data.m_hasAxisLimits && (data.m_fitNext || data.m_xAxis.autoFit || data.m_yAxis.autoFit))
        fitData(data.m_fitNext || data.m_xAxis.autoFit, data.m_fitNext || data.m_yAxis.autoFit);

    const float dpi = this->getDpiScale();
    const float textHeight = ImGui::GetFontSize();
    float padding = 10.0f;
    this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding);
    padding = std::max(padding, 0.0f) * dpi;
    float borderWidth = 1.0f;
    this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth);
    borderWidth = std::max(borderWidth, 0.0f) * dpi;
    ImU32 frameBackground = ImGui::GetColorU32(ImGuiCol_FrameBg);
    ImU32 background = ImGui::GetColorU32(ImGuiCol_WindowBg);
    ImU32 border = ImGui::GetColorU32(ImGuiCol_Border);
    ImU32 text = ImGui::GetColorU32(ImGuiCol_Text);
    ImU32 series = IM_COL32(76, 114, 176, 255);
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &background))
        frameBackground = background;
    this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &border);
    this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &text);
    this->_resolveStyleProperty(StyleColorProperty::eColor, &series);

    const bool decorated = !this->isSparkline();
    const char* title = this->getTitle().c_str();
    const char* titleEnd = ImGui::FindRenderedTextEnd(title);
    const bool showTitle = decorated && this->isShowTitle() && title != titleEnd;
    const float labelGap = 5.0f * dpi;
    auto yTicks = plotTicks(data.m_yMin, data.m_yMax, size.y - 2.0f * padding, true);
    float yTickWidth = 0.0f;
    for (const auto& tick : yTicks)
        yTickWidth = std::max(yTickWidth, ImGui::CalcTextSize(tick.label.c_str()).x);
    const auto& xAxis = data.m_xAxis;
    const auto& yAxis = data.m_yAxis;
    const float yMargin = decorated ? (yAxis.tickLabels ? yTickWidth + labelGap : 0.0f) +
        (yAxis.label && !this->getYLabel().empty() ? textHeight + labelGap : 0.0f) : 0.0f;
    const float xMargin = decorated ? (xAxis.tickLabels ? textHeight + labelGap : 0.0f) +
        (xAxis.label && !this->getXLabel().empty() ? textHeight + labelGap : 0.0f) : 0.0f;
    float left = yAxis.opposite ? 0.0f : yMargin;
    float right = yAxis.opposite ? yMargin : 0.0f;
    float bottom = xAxis.opposite ? 0.0f : xMargin;
    float top = (showTitle ? textHeight + labelGap : 0.0f) + (xAxis.opposite ? xMargin : 0.0f);
    const char* seriesLabel = this->getSeriesLabel().c_str();
    const char* seriesEnd = ImGui::FindRenderedTextEnd(seriesLabel);
    const bool showLegend = decorated && this->isShowLegend() && seriesLabel != seriesEnd;
    const ImVec2 legendSize(ImGui::CalcTextSize(seriesLabel, seriesEnd).x + textHeight + 10.0f * dpi,
                            textHeight + 10.0f * dpi);
    const int location = data.m_legendLocation;
    const bool west = location == 0 || location == 3 || location == 5;
    const bool east = location == 2 || location == 4 || location == 7;
    const bool north = location < 3;
    const bool south = location > 4;
    float legendTop = 0.0f;
    if (showLegend && data.m_legendOutside)
    {
        // Vertical corner legends use a side column; horizontal ones use a row.
        const bool side = !data.m_legendHorizontal || (!north && !south);
        const bool row = data.m_legendHorizontal || (!west && !east);
        const float legendGap = 10.0f * dpi;
        if (west && side) left += legendSize.x + legendGap;
        if (east && side) right += legendSize.x + legendGap;
        if (north && row) legendTop = legendSize.y + legendGap;
        if (south && row) bottom += legendSize.y + legendGap;
        top += legendTop;
    }
    const ImRect frame(origin, ImVec2(origin.x + size.x, origin.y + size.y));
    const ImRect plot(ImVec2(origin.x + padding + left, origin.y + padding + top),
                      ImVec2(frame.Max.x - padding - right, frame.Max.y - padding - bottom));
    if (plot.GetWidth() <= 1.0f || plot.GetHeight() <= 1.0f)
    {
        ImGui::Dummy(size);
        return;
    }
    const auto equalAxes = [&](bool referenceX) {
        if (!data.m_equal || data.m_hasAxisLimits)
            return;
        if (referenceX && !yAxis.autoFit && !yAxis.lockMin && !yAxis.lockMax)
        {
            const double half = (data.m_xMax - data.m_xMin) * plot.GetHeight() / plot.GetWidth() * 0.5;
            const double center = data.m_yMin + (data.m_yMax - data.m_yMin) * 0.5;
            data.m_yMin = center - half;
            data.m_yMax = center + half;
        }
        else if (!referenceX && !xAxis.autoFit && !xAxis.lockMin && !xAxis.lockMax)
        {
            const double half = (data.m_yMax - data.m_yMin) * plot.GetWidth() / plot.GetHeight() * 0.5;
            const double center = data.m_xMin + (data.m_xMax - data.m_xMin) * 0.5;
            data.m_xMin = center - half;
            data.m_xMax = center + half;
        }
    };
    equalAxes(true);
    const auto toPixels = [&](double x, double y) {
        double tx = std::clamp((x - data.m_xMin) / (data.m_xMax - data.m_xMin), -1.0e4, 1.0e4);
        double ty = std::clamp((y - data.m_yMin) / (data.m_yMax - data.m_yMin), -1.0e4, 1.0e4);
        if (xAxis.invert) tx = 1.0 - tx;
        if (yAxis.invert) ty = 1.0 - ty;
        return ImVec2(plot.Min.x + float(tx) * plot.GetWidth(), plot.Max.y - float(ty) * plot.GetHeight());
    };
    const auto fromPixels = [&](ImVec2 point) {
        double tx = double((point.x - plot.Min.x) / plot.GetWidth());
        double ty = double((plot.Max.y - point.y) / plot.GetHeight());
        if (xAxis.invert) tx = 1.0 - tx;
        if (yAxis.invert) ty = 1.0 - ty;
        return std::make_pair(data.m_xMin + tx * (data.m_xMax - data.m_xMin),
                              data.m_yMin + ty * (data.m_yMax - data.m_yMin));
    };
    ImGui::InvisibleButton("##plot", size, ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonRight | ImGuiButtonFlags_MouseButtonMiddle);
    const ImVec2 mouse = ImGui::GetMousePos();
    const bool windowHovered = ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows |
        ImGuiHoveredFlags_AllowWhenBlockedByActiveItem);
    const bool hovered = plot.Contains(mouse) && windowHovered;
    const ImRect xAxisRect(ImVec2(plot.Min.x, xAxis.opposite ? origin.y + padding : plot.Max.y),
                           ImVec2(plot.Max.x, xAxis.opposite ? plot.Min.y : frame.Max.y - padding));
    const ImRect yAxisRect(ImVec2(yAxis.opposite ? plot.Max.x : origin.x + padding, plot.Min.y),
                           ImVec2(yAxis.opposite ? frame.Max.x - padding : plot.Min.x, plot.Max.y));
    const bool xHovered = windowHovered && xAxisRect.Contains(mouse);
    const bool yHovered = windowHovered && yAxisRect.Contains(mouse);
    const bool interactive = this->isInteractive() && decorated;
    const bool xLocked = data.m_hasAxisLimits || xAxis.autoFit || (xAxis.lockMin && xAxis.lockMax);
    const bool yLocked = data.m_hasAxisLimits || yAxis.autoFit || (yAxis.lockMin && yAxis.lockMax);
    const bool locked = xLocked && yLocked;
    const ImRect legendBounds = data.m_legendOutside ? frame : plot;
    const float legendPadding = data.m_legendOutside ? padding : 10.0f * dpi;
    const ImVec2 legendMin(west ? legendBounds.Min.x + legendPadding :
                           east ? legendBounds.Max.x - legendSize.x - legendPadding :
                           legendBounds.GetCenter().x - legendSize.x * 0.5f,
                           north ? legendBounds.Min.y + legendPadding :
                           south ? legendBounds.Max.y - legendSize.y - legendPadding :
                           legendBounds.GetCenter().y - legendSize.y * 0.5f);
    const ImVec2 legendMax(legendMin.x + legendSize.x, legendMin.y + legendSize.y);
    const bool legendHovered = showLegend && windowHovered && ImRect(legendMin, legendMax).Contains(mouse);
    const auto legendMenu = [&] {
        bool show = this->isShowLegend();
        if (ImGui::Checkbox("Show", &show)) this->setShowLegend(show);
        ImGui::Checkbox("Outside", &data.m_legendOutside);
        if (ImGui::RadioButton("H", data.m_legendHorizontal)) data.m_legendHorizontal = true;
        ImGui::SameLine();
        if (ImGui::RadioButton("V", !data.m_legendHorizontal)) data.m_legendHorizontal = false;
        // A single series has the same size in either legend direction.
        ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(2, 2));
        const char* positions[] = { "NW", "N", "NE", "W", "", "E", "SW", "S", "SE" };
        const float height = ImGui::GetFrameHeight();
        for (int cell = 0; cell < 9; ++cell)
        {
            if (cell == 4) ImGui::Dummy(ImVec2(1.5f * height, height));
            else if (ImGui::Button(positions[cell], ImVec2(1.5f * height, height)))
                data.m_legendLocation = cell > 4 ? cell - 1 : cell;
            if (cell % 3 != 2) ImGui::SameLine();
        }
        ImGui::PopStyleVar();
    };
    if (interactive)
    {
        const bool affectX = (hovered || xHovered) && !legendHovered;
        const bool affectY = (hovered || yHovered) && !legendHovered;
        if ((affectX || affectY) && (ImGui::IsMouseDoubleClicked(ImGuiMouseButton_Left) ||
                                  ImGui::IsMouseClicked(ImGuiMouseButton_Middle)))
            fitData(affectX, affectY);
        if ((affectX || affectY) && ImGui::GetIO().MouseWheel != 0.0f)
        {
            ImGui::SetKeyOwner(ImGuiKey_MouseWheelY, ImGui::GetItemID());
            const auto anchor = fromPixels(mouse);
            const double scale = ImGui::GetIO().MouseWheel > 0.0f ? 1.0 - 0.1 / 1.2 : 1.1;
            if (affectX && !xLocked && !ImGui::GetIO().KeyAlt)
                setRange(data.m_xAxis, data.m_xMin, data.m_xMax,
                         anchor.first + (data.m_xMin - anchor.first) * scale,
                         anchor.first + (data.m_xMax - anchor.first) * scale);
            if (affectY && !yLocked && !ImGui::GetIO().KeyShift)
                setRange(data.m_yAxis, data.m_yMin, data.m_yMax,
                         anchor.second + (data.m_yMin - anchor.second) * scale,
                         anchor.second + (data.m_yMax - anchor.second) * scale);
            equalAxes(affectX);
        }
        if (ImGui::IsMouseClicked(ImGuiMouseButton_Left))
        {
            data.m_dragX = affectX && !data.m_selecting;
            data.m_dragY = affectY && !data.m_selecting;
            if (legendHovered) data.m_showSeries = !data.m_showSeries;
        }
        if (ImGui::IsItemActive() && ImGui::IsMouseDragging(ImGuiMouseButton_Left))
        {
            const ImVec2 delta = ImGui::GetIO().MouseDelta;
            const double x = double(delta.x / plot.GetWidth()) * (data.m_xMax - data.m_xMin) * (xAxis.invert ? -1.0 : 1.0);
            const double y = double(delta.y / plot.GetHeight()) * (data.m_yMax - data.m_yMin) * (yAxis.invert ? -1.0 : 1.0);
            if (data.m_dragX && !xLocked && !ImGui::GetIO().KeyAlt)
                setRange(data.m_xAxis, data.m_xMin, data.m_xMax, data.m_xMin - x, data.m_xMax - x);
            if (data.m_dragY && !yLocked && !ImGui::GetIO().KeyShift)
                setRange(data.m_yAxis, data.m_yMin, data.m_yMax, data.m_yMin + y, data.m_yMax + y);
        }
        if (hovered && !legendHovered && ImGui::IsMouseClicked(ImGuiMouseButton_Right))
        {
            data.m_selectionStart = mouse;
            data.m_selecting = true;
        }
        // Match the former input map: releasing Left cancels a Right-button box.
        if (ImGui::IsKeyPressed(ImGuiKey_Escape) || ImGui::IsMouseReleased(ImGuiMouseButton_Left))
            data.m_selecting = false;
        if (ImGui::IsMouseReleased(ImGuiMouseButton_Right))
        {
            const bool contextClick = !ImGui::IsMouseDragPastThreshold(ImGuiMouseButton_Right, 2.0f * dpi);
            if (legendHovered && contextClick) ImGui::OpenPopup("##legendMenu");
            else if (xHovered && contextClick) ImGui::OpenPopup("##xAxisMenu");
            else if (yHovered && contextClick) ImGui::OpenPopup("##yAxisMenu");
            else if (data.m_selecting)
            {
                const ImVec2 start = data.m_selectionStart;
                const ImVec2 end = mouse;
                const bool moved = std::abs(end.x - start.x) > 2.0f * dpi || std::abs(end.y - start.y) > 2.0f * dpi;
                const bool selectX = data.m_boxSelect && std::abs(end.x - start.x) > 2.0f * dpi && !ImGui::GetIO().KeyAlt;
                const bool selectY = data.m_boxSelect && std::abs(end.y - start.y) > 2.0f * dpi && !ImGui::GetIO().KeyShift;
                if (!moved) ImGui::OpenPopup("##plotMenu");
                else
                {
                    const auto a = fromPixels(start);
                    const auto b = fromPixels(end);
                    if (selectX && !xLocked)
                        setRange(data.m_xAxis, data.m_xMin, data.m_xMax, std::min(a.first, b.first), std::max(a.first, b.first));
                    if (selectY && !yLocked)
                        setRange(data.m_yAxis, data.m_yMin, data.m_yMax, std::min(a.second, b.second), std::max(a.second, b.second));
                    equalAxes(selectX);
                }
            }
            data.m_selecting = false;
        }
        if (ImGui::BeginPopup("##xAxisMenu"))
        {
            ImGui::TextUnformatted(xAxis.label && !this->getXLabel().empty() ? this->getXLabel().c_str() : "X-Axis");
            ImGui::Separator();
            plotAxisMenu(data.m_xAxis, data.m_xMin, data.m_xMax, data.m_hasAxisLimits, !this->getXLabel().empty());
            ImGui::EndPopup();
        }
        if (ImGui::BeginPopup("##yAxisMenu"))
        {
            ImGui::TextUnformatted(yAxis.label && !this->getYLabel().empty() ? this->getYLabel().c_str() : "Y-Axis");
            ImGui::Separator();
            if (plotAxisMenu(data.m_yAxis, data.m_yMin, data.m_yMax, data.m_hasAxisLimits, !this->getYLabel().empty()))
                equalAxes(false);
            ImGui::EndPopup();
        }
        if (ImGui::BeginPopup("##legendMenu"))
        {
            legendMenu();
            ImGui::EndPopup();
        }
        if (ImGui::BeginPopup("##plotMenu"))
        {
            ImGui::PushID("x");
            if (ImGui::BeginMenu(xAxis.label && !this->getXLabel().empty() ? this->getXLabel().c_str() : "X-Axis"))
            {
                plotAxisMenu(data.m_xAxis, data.m_xMin, data.m_xMax, data.m_hasAxisLimits, !this->getXLabel().empty());
                ImGui::EndMenu();
            }
            ImGui::PopID();
            ImGui::PushID("y");
            if (ImGui::BeginMenu(yAxis.label && !this->getYLabel().empty() ? this->getYLabel().c_str() : "Y-Axis"))
            {
                if (plotAxisMenu(data.m_yAxis, data.m_yMin, data.m_yMax, data.m_hasAxisLimits, !this->getYLabel().empty()))
                    equalAxes(false);
                ImGui::EndMenu();
            }
            ImGui::PopID();
            ImGui::Separator();
            if (ImGui::BeginMenu("Legend")) { legendMenu(); ImGui::EndMenu(); }
            if (ImGui::BeginMenu("Settings"))
            {
                ImGui::MenuItem("Equal", nullptr, &data.m_equal);
                ImGui::MenuItem("Box Select", nullptr, &data.m_boxSelect);
                bool show = this->isShowTitle();
                if (ImGui::MenuItem("Title", nullptr, &show, title != titleEnd)) this->setShowTitle(show);
                show = this->isShowMousePosition();
                if (ImGui::MenuItem("Mouse Position", nullptr, &show)) this->setShowMousePosition(show);
                show = this->isCrosshairs();
                if (ImGui::MenuItem("Crosshairs", nullptr, &show)) this->setCrosshairs(show);
                ImGui::EndMenu();
            }
            ImGui::EndPopup();
        }
    }

    ImDrawList* drawList = ImGui::GetWindowDrawList();
    drawList->PushClipRect(frame.Min, frame.Max, true);
    drawList->AddRectFilled(frame.Min, frame.Max, frameBackground, ImGui::GetStyle().FrameRounding);
    drawList->AddRectFilled(plot.Min, plot.Max, background);
    const auto xTicks = plotTicks(data.m_xMin, data.m_xMax, plot.GetWidth(), false, this->getXAxisFormat());
    yTicks = plotTicks(data.m_yMin, data.m_yMax, plot.GetHeight(), true);
    if (decorated)
    {
        const float xAxisY = xAxis.opposite ? plot.Min.y : plot.Max.y;
        const float yAxisX = yAxis.opposite ? plot.Max.x : plot.Min.x;
        drawList->PushClipRect(plot.Min, plot.Max, true);
        for (const auto& tick : xTicks)
        {
            const float x = toPixels(tick.value, data.m_yMin).x;
            if (xAxis.gridLines)
                drawList->AddLine(ImVec2(x, plot.Min.y), ImVec2(x, plot.Max.y), plotAlpha(text, tick.major ? 0.25f : 0.0625f));
            if (xAxis.tickMarks)
                drawList->AddLine(ImVec2(x, xAxisY), ImVec2(x, xAxisY + (xAxis.opposite ? 1.0f : -1.0f) *
                    (tick.major ? 10.0f : 5.0f) * dpi), plotAlpha(text, 0.25f));
        }
        for (const auto& tick : yTicks)
        {
            const float y = toPixels(data.m_xMin, tick.value).y;
            if (yAxis.gridLines)
                drawList->AddLine(ImVec2(plot.Min.x, y), ImVec2(plot.Max.x, y), plotAlpha(text, tick.major ? 0.25f : 0.0625f));
            if (yAxis.tickMarks)
                drawList->AddLine(ImVec2(yAxisX, y), ImVec2(yAxisX + (yAxis.opposite ? -1.0f : 1.0f) *
                    (tick.major ? 10.0f : 5.0f) * dpi, y), text);
        }
        drawList->PopClipRect();
        const ImU32 axisColor = plotAlpha(text, 0.25f);
        drawList->AddLine(ImVec2(yAxisX, plot.Min.y), ImVec2(yAxisX, plot.Max.y), axisColor);
        drawList->AddLine(ImVec2(plot.Min.x, xAxisY), ImVec2(plot.Max.x, xAxisY), axisColor);
        for (const auto& tick : xTicks)
        {
            const float x = toPixels(tick.value, data.m_yMin).x;
            if (xAxis.tickLabels)
                drawList->AddText(ImVec2(x - ImGui::CalcTextSize(tick.label.c_str()).x * 0.5f,
                    xAxisY + (xAxis.opposite ? -labelGap - textHeight : labelGap)), text, tick.label.c_str());
        }
        for (const auto& tick : yTicks)
        {
            const float y = toPixels(data.m_xMin, tick.value).y;
            if (yAxis.tickLabels)
                drawList->AddText(ImVec2(yAxisX + (yAxis.opposite ? labelGap : -labelGap - ImGui::CalcTextSize(tick.label.c_str()).x),
                    y - textHeight * 0.5f), text, tick.label.c_str());
        }
        if (showTitle)
            drawList->AddText(ImVec2(plot.GetCenter().x - ImGui::CalcTextSize(title, titleEnd).x * 0.5f, origin.y + padding + legendTop), text, title, titleEnd);
        const char* xLabel = this->getXLabel().c_str();
        if (xAxis.label)
            drawList->AddText(ImVec2(plot.GetCenter().x - ImGui::CalcTextSize(xLabel).x * 0.5f,
                xAxis.opposite ? plot.Min.y - xMargin : plot.Max.y + xMargin - textHeight), text, xLabel);
        const char* yLabel = this->getYLabel().c_str();
        if (yAxis.label)
            verticalPlotText(drawList, ImVec2(yAxis.opposite ? plot.Max.x + yMargin - textHeight : plot.Min.x - yMargin,
                plot.GetCenter().y - ImGui::CalcTextSize(yLabel).x * 0.5f), text, yLabel);
    }
    drawList->PushClipRect(plot.Min, plot.Max, true);
    const float lineWeight = std::max(this->getLineWeight(), 0.0f) * dpi;
    const float markerSize = std::max(this->getMarkerSize(), 1.0f) * dpi;
    if (data.m_showSeries)
    {
        bool previousValid = false;
        ImVec2 previous;
        for (size_t index = 0; index < count; ++index)
        {
            const auto value = sample(index);
            if (!std::isfinite(value.first) || !std::isfinite(value.second))
            {
                previousValid = false;
                continue;
            }
            const ImVec2 point = toPixels(value.first, value.second);
            if (bars)
            {
                const ImVec2 a = toPixels(value.first - barWidth * 0.5, std::max(0.0, value.second));
                const ImVec2 b = toPixels(value.first + barWidth * 0.5, std::min(0.0, value.second));
                if (barWidth == 0.0)
                    drawList->AddLine(a, b, series, dpi);
                else
                    drawList->AddRectFilled(ImVec2(std::min(a.x, b.x), std::min(a.y, b.y)),
                                            ImVec2(std::max(a.x, b.x), std::max(a.y, b.y)), series);
            }
            else
            {
                if ((this->getType() == Type::eLine || this->getType() == Type::eLine2D) && previousValid && lineWeight > 0.0f)
                    drawList->AddLine(previous, point, series, lineWeight);
                if (this->isShowMarkers() || this->getType() == Type::eScatter)
                    drawList->AddCircleFilled(point, markerSize, series, 12);
            }
            previous = point;
            previousValid = true;
        }
    }
    if (data.m_selecting && data.m_boxSelect && !locked && ImGui::IsMouseDragging(ImGuiMouseButton_Right))
    {
        const ImVec2 a(ImGui::GetIO().KeyAlt ? plot.Min.x : std::min(data.m_selectionStart.x, mouse.x),
                       ImGui::GetIO().KeyShift ? plot.Min.y : std::min(data.m_selectionStart.y, mouse.y));
        const ImVec2 b(ImGui::GetIO().KeyAlt ? plot.Max.x : std::max(data.m_selectionStart.x, mouse.x),
                       ImGui::GetIO().KeyShift ? plot.Max.y : std::max(data.m_selectionStart.y, mouse.y));
        const ImU32 selection = ImGui::GetColorU32(ImGuiCol_PlotHistogram);
        drawList->AddRectFilled(a, b, plotAlpha(selection, 0.25f));
        drawList->AddRect(a, b, selection);
    }
    if (hovered && this->isCrosshairs() && !this->isSparkline())
    {
        ImGui::SetMouseCursor(ImGuiMouseCursor_None);
        drawList->AddLine(ImVec2(mouse.x, plot.Min.y), ImVec2(mouse.x, plot.Max.y), border);
        drawList->AddLine(ImVec2(plot.Min.x, mouse.y), ImVec2(plot.Max.x, mouse.y), border);
    }
    if (hovered && this->isShowMousePosition() && decorated)
    {
        const auto value = fromPixels(mouse);
        const std::string position = formatPlotNumber(value.first) + ", " + formatPlotNumber(value.second);
        drawList->AddText(ImVec2(plot.Max.x - ImGui::CalcTextSize(position.c_str()).x - 10.0f * dpi,
                                plot.Max.y - textHeight - 10.0f * dpi), text, position.c_str());
    }
    if (hovered && this->isShowSampleTooltip() && data.m_showSeries)
    {
        size_t nearest = data.m_yValues.size();
        float distance = std::numeric_limits<float>::max();
        for (size_t index = 0; index < data.m_yValues.size(); ++index)
        {
            const double x = hasXValues ? data.m_xValues[index] : double(index);
            if (!std::isfinite(x) || !std::isfinite(data.m_yValues[index]))
                continue;
            const ImVec2 point = toPixels(x, data.m_yValues[index]);
            const float dx = point.x - mouse.x;
            const float dy = point.y - mouse.y;
            const float candidate = this->isShowMarkers() ? dx * dx + dy * dy : std::abs(dx);
            if (candidate < distance) { distance = candidate; nearest = index; }
        }
        const float radius = markerSize + 4.0f * dpi;
        if (nearest < data.m_yValues.size() && (!this->isShowMarkers() || distance <= radius * radius))
        {
            const double x = hasXValues ? data.m_xValues[nearest] : double(nearest);
            const double previousX = nearest > 0 ? (hasXValues ? data.m_xValues[nearest - 1] : double(nearest - 1)) : x;
            drawList->AddCircle(toPixels(x, data.m_yValues[nearest]), radius, ImGui::GetColorU32(ImGuiCol_Text), 12, dpi);
            ImGui::BeginTooltip();
            if (!this->getSeriesLabel().empty())
                ImGui::TextUnformatted(this->getSeriesLabel().c_str());
            if (!this->getSampleTooltipValueLabel().empty())
                ImGui::Text("%s: %s%s%s", this->getSampleTooltipValueLabel().c_str(), formatPlotNumber(data.m_yValues[nearest]).c_str(),
                            this->getYLabel().empty() ? "" : " ", this->getYLabel().c_str());
            if (!this->getSampleTooltipXLabel().empty())
                ImGui::Text("%s: %s", this->getSampleTooltipXLabel().c_str(), formatPlotNumber(x).c_str());
            if (!this->getSampleTooltipDeltaXLabel().empty())
                ImGui::Text("%s: %s", this->getSampleTooltipDeltaXLabel().c_str(), formatPlotNumber(x - previousX).c_str());
            ImGui::EndTooltip();
        }
    }
    drawList->PopClipRect();
    if (borderWidth > 0.0f)
        drawList->AddRect(plot.Min, plot.Max, border, 0.0f, 0, borderWidth);
    if (showLegend)
    {
        drawList->AddRectFilled(legendMin, legendMax, ImGui::GetColorU32(ImGuiCol_PopupBg));
        drawList->AddRect(legendMin, legendMax, border);
        const ImU32 legendColor = data.m_showSeries ? series : ImGui::GetColorU32(ImGuiCol_TextDisabled);
        drawList->AddRectFilled(ImVec2(legendMin.x + 7.0f * dpi, legendMin.y + 7.0f * dpi),
                                ImVec2(legendMin.x + textHeight - 2.0f * dpi, legendMax.y - 7.0f * dpi), legendColor);
        drawList->AddText(ImVec2(legendMin.x + textHeight + 5.0f * dpi, legendMin.y + 5.0f * dpi),
                          data.m_showSeries ? text : ImGui::GetColorU32(ImGuiCol_TextDisabled), seriesLabel, seriesEnd);
    }
    drawList->PopClipRect();
}

void Plot::setSamples(Samples1D valueList)
{
    auto& data = _getData<PlotData>();
    data.m_xValues.clear();
    data.m_yValues = std::move(valueList);
    data.m_plotXYData.clear();
    data.m_plotData.assign(data.m_yValues.begin(), data.m_yValues.end());
    data.m_histogramDirty = true;
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Plot::setSampleProviderFn(std::function<double(int)> fn, int valuesCount)
{
    Samples1D valueList;
    if (fn && valuesCount > 0)
    {
        valueList.reserve(static_cast<size_t>(valuesCount));
        for (int i = 0; i < valuesCount; ++i)
        {
            valueList.push_back(fn(i));
        }
    }
    this->setSamples(std::move(valueList));
}

void Plot::setXYSamples(Samples2D valueList)
{
    auto& data = _getData<PlotData>();
    data.m_xValues.clear();
    data.m_yValues.clear();
    data.m_plotXYData.clear();
    data.m_plotData.clear();
    data.m_prevWidth = 0.0f;
    data.m_xValues.reserve(valueList.size());
    data.m_yValues.reserve(valueList.size());
    data.m_histogramDirty = true;
    for (const auto& value : valueList)
    {
        data.m_plotXYData.emplace_back(value.first, value.second);
        data.m_xValues.push_back(value.first);
        data.m_yValues.push_back(value.second);
    }
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Plot::fit()
{
    auto& data = _getData<PlotData>();
    data.m_hasAxisLimits = false;
    data.m_fitNext = true;
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Plot::setAxisLimits(double xMin, double xMax, double yMin, double yMax)
{
    auto& data = _getData<PlotData>();
    data.m_xMin = xMin;
    data.m_xMax = xMax;
    data.m_yMin = yMin;
    data.m_yMax = yMax;
    validRange(data.m_xMin, data.m_xMax);
    validRange(data.m_yMin, data.m_yMax);
    data.m_hasAxisLimits = true;
    data.m_fitNext = false;
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Plot::clearAxisLimits()
{
    auto& data = _getData<PlotData>();
    data.m_hasAxisLimits = false;
    data.m_fitNext = true;
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
