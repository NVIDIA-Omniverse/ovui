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

#include "platform/Assert.h"
#include "platform/Log.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/ProgressBar.h>
#include <omni/ui/SimpleNumericModel.h>

#include "WidgetData.h"

#include <algorithm>
#include <iomanip>
#include <sstream>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct ProgressBar::ProgressBarData : public Widget::WidgetData
{
    ~ProgressBarData() override = default;

    // The cached state.
    double m_valueCache = 0;
    std::string m_overlayCache;
};


// Customized float model to return empty string by default for progress bar
class CustomFloatModel : public SimpleNumericModel<double>
{
public:
    template <typename... Args>
    static std::shared_ptr<CustomFloatModel> create(Args&&... args)
    {
        return std::shared_ptr<CustomFloatModel>{ new CustomFloatModel{ std::forward<Args>(args)... } };
    }

protected:
    CustomFloatModel(double defaultValue = 0.0) : SimpleNumericModel<double>(defaultValue)
    {
    }

public:
    using SimpleNumericModel<double>::setValue;

    // Reimplemented because it's a special case for string.
    void setValue(std::string value) override
    {
        try
        {
            this->_setNumericValue(std::stof(value));
        }
        catch (const std::invalid_argument&)
        {
            this->_setNumericValue(0.0f);
        }
    }

    std::string getValueAsString() const override
    {
        return "";
    }
};

ProgressBar::ProgressBar(std::shared_ptr<AbstractValueModel> model)
    : Widget(new ProgressBarData)
    , ValueModelHelper(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(CustomFloatModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated();
    }
}

ProgressBar::~ProgressBar() = default;

void ProgressBar::setComputedContentHeight(float height)
{
    // The field can't be smaller than ImGui style.
    this->_pushFont(*this);

    int popStyleCount = 0;
    float padding;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= this->getDpiScale();
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
        popStyleCount++;
    }

    height = std::max(ImGui::GetFrameHeight(), height);

    ImGui::PopStyleVar(popStyleCount);

    this->_popFont();

    Widget::setComputedContentHeight(height);
}

void ProgressBar::onStyleUpdated()
{
    this->_updateFont(*this);
}

void ProgressBar::_drawContent(float elapsedTime)
{
    int32_t popStyleCount = 0, popFloatCount = 0;
    bool enabled = this->isEnabled();
    ImGui::PushItemFlag(ImGuiItemFlags_Disabled, !enabled);

    float cornerRadius = 0;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &cornerRadius))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, cornerRadius);
        popFloatCount += 1;
    }

    float borderWidth = 0;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_FrameBorderSize, borderWidth);
        popFloatCount += 1;
    }

    uint32_t borderColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &borderColor))
    {
        ImGui::PushStyleColor(ImGuiCol_Border, borderColor);
        // Fix the border issue
        ImGui::PushStyleColor(ImGuiCol_BorderShadow, 0x0);

        popStyleCount += 2;
    }

    uint32_t progressBarColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &progressBarColor))
    {
        ImGui::PushStyleColor(ImGuiCol_PlotHistogram, progressBarColor);

        popStyleCount += 1;
    }

    // Without this the field will not be able to change because the name should be unique. Otherwise we need to use
    // PushID
    ImGui::PushID(this);

    this->_pushFont(*this);

    float padding;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= this->getDpiScale();
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
        popFloatCount += 1;
    }

    uint32_t backgroundColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &backgroundColor))
    {
        // Put background color to everything possible.
        ImGui::PushStyleColor(ImGuiCol_FrameBg, backgroundColor);
        ImGui::PushStyleColor(ImGuiCol_FrameBgActive, backgroundColor);
        ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, backgroundColor);

        popStyleCount += 3;
    }

    uint32_t fontColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &fontColor))
    {
        ImGui::PushStyleColor(ImGuiCol_Text, fontColor);

        popStyleCount += 1;
    }

    this->_drawUnderlyingItem();

    this->_popFont();

    ImGui::PopID();

    ImGui::PopStyleColor(popStyleCount);
    ImGui::PopStyleVar(popFloatCount);
    ImGui::PopItemFlag();
}

void ProgressBar::onModelUpdated()
{
    const auto model = this->getModel();
    if (OMNIUI_UNLIKELY(!model))
    {
        OMNIUI_LOG_ERROR("ProgressBar::onModelUpdated had no model");
        return;
    }

    auto& data = _getData<ProgressBarData>();
    data.m_valueCache = model->getValueAsFloat();
    data.m_overlayCache = model->getValueAsString();
    if (data.m_overlayCache.empty())
    {
        std::ostringstream stream;
        stream << std::fixed << std::setprecision(2) << std::min(1., std::max(0., data.m_valueCache)) * 100. << "%";
        data.m_overlayCache = stream.str();
    }

    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void ProgressBar::_drawUnderlyingItem()
{
    auto& data = _getData<ProgressBarData>();
    ImGui::ProgressBar((float)data.m_valueCache, { this->getComputedContentWidth(), this->getComputedContentHeight() },
                       data.m_overlayCache.c_str());
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
