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
#include <omni/ui/Plot.h>
#include <omni/ui/StyleContainer.h>

#include "WidgetData.h"

#include <algorithm>
#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct Plot::PlotData : public Widget::WidgetData
{
    PlotData(Plot::PlotData1D valueList) : m_plotData(std::move(valueList))
    {
    }
    PlotData(Plot::PlotData2D valueList) : m_plotXYData(std::move(valueList))
    {
    }
    ~PlotData() override = default;

    Plot::PlotData1D m_plotData;
    Plot::PlotData2D m_plotXYData;
    float m_prevWidth = 0;
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


Plot::~Plot() = default;

void Plot::setComputedContentHeight(float height)
{
    Widget::setComputedContentHeight(std::max(height, 0.0f));
}

void Plot::_drawContent(float elapsedTime)
{
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
    _getData<PlotData>().m_plotData = std::move(valueList);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void Plot::setXYData(PlotData2D valueList)
{
    _getData<PlotData>().m_plotXYData = std::move(valueList);
    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
