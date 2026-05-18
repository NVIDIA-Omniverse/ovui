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
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/ComboBox.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/StyleContainer.h>

#include "WidgetData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct ComboBox::ComboBoxData : public Widget::WidgetData
{
    ~ComboBoxData() override = default;

    // The cached state of the ComboBox allows to query the model only if it's changed.
    int64_t m_currentIndex = 0;
    std::vector<std::string> m_items;
};


ComboBox::ComboBox(std::shared_ptr<AbstractItemModel> model)
    : Widget(new ComboBoxData)
    , ItemModelHelper(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple one.
        this->setModel(SimpleListModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated(nullptr);
    }
}

ComboBox::~ComboBox() = default;

void ComboBox::setComputedContentWidth(float width)
{
    // TODO: We need to set the size from the style. We now take the ComboBox size from ImGui. It's height because we
    // assume that the widget can't be smaller than the right square button with the arrow.
    int popStyleCount = 0;
    float padding;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= this->getDpiScale();
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
        popStyleCount++;
    }

    this->_pushFont(*this);
    width = std::max(ImGui::GetFrameHeight(), width);
    this->_popFont();

    ImGui::PopStyleVar(popStyleCount);

    Widget::setComputedContentWidth(width);
}

void ComboBox::setComputedContentHeight(float height)
{
    int popStyleCount = 0;
    float padding;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= this->getDpiScale();
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
        popStyleCount++;
    }

    this->_pushFont(*this);
    height = std::max(ImGui::GetFrameHeight(), height);
    this->_popFont();

    ImGui::PopStyleVar(popStyleCount);

    Widget::setComputedContentHeight(height);
}

void ComboBox::onStyleUpdated()
{
    this->_updateFont(*this);
}

void ComboBox::onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    // Keep a local reference to this model to keep it alive during the function.
    auto model = this->getModel();
    if (OMNIUI_UNLIKELY(!model))
    {
        OMNIUI_LOG_ERROR("ComboBox::onModelUpdated had no model");
        return;
    }
    auto currentIndexModel = model->getItemValueModel();
    if (OMNIUI_UNLIKELY(!currentIndexModel))
    {
        OMNIUI_LOG_ERROR("ComboBox::onModelUpdated getItemValueModel returned an invalid index model");
        return;
    }

    auto& data = _getData< ComboBoxData>();
    data.m_currentIndex = currentIndexModel->getValue<int64_t>();

    auto modelChildItems = model->getItemChildren();
    data.m_items.clear();
    // TODO: This number is not correct because there are empty items.
    data.m_items.reserve(modelChildItems.size());
    for (const auto& modelChildItem : modelChildItems)
    {
        auto valueModel = model->getItemValueModel(modelChildItem);
        if (OMNIUI_LIKELY(valueModel))
        {
            data.m_items.emplace_back(valueModel->getValue<std::string>());
        }
        else
        {
            OMNIUI_LOG_ERROR("ComboBox::onModelUpdated getItemValueModel returned an invalid model");
        }        
    }
}

void ComboBox::_drawContent(float elapsedTime)
{
    int32_t popStyleColorCount = 0, popStyleVarCount = 0;
    bool enabled = this->isEnabled();
    ImGui::PushItemFlag(ImGuiItemFlags_Disabled, !enabled);

    ImGui::PushStyleColor(ImGuiCol_ScrollbarBg, 0x0);
    popStyleColorCount++;

    uint32_t backgroundColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &backgroundColor))
    {
        // Put background color to everything possible.
        ImGui::PushStyleColor(ImGuiCol_FrameBg, backgroundColor);
        ImGui::PushStyleColor(ImGuiCol_FrameBgActive, backgroundColor);
        ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, backgroundColor);

        // background color for arrow
        ImGui::PushStyleColor(ImGuiCol_Button, backgroundColor);
        ImGui::PushStyleColor(ImGuiCol_ButtonHovered, backgroundColor);

        // background color for droplist
        ImGui::PushStyleColor(ImGuiCol_PopupBg, backgroundColor);

        popStyleColorCount += 6;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eSecondaryBackgroundColor, &backgroundColor))
    {
        // background color for droplist
        ImGui::PushStyleColor(ImGuiCol_PopupBg, backgroundColor);

        popStyleColorCount += 1;
    }

    uint32_t selectedColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eSelectedColor, &selectedColor))
    {
        ImGui::PushStyleColor(ImGuiCol_HeaderActive, selectedColor);
        ImGui::PushStyleColor(ImGuiCol_HeaderHovered, selectedColor);
        ImGui::PushStyleColor(ImGuiCol_Header, selectedColor);

        popStyleColorCount += 3;
    }

    uint32_t color;
    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_Text, color);

        popStyleColorCount += 1;
    }

    uint32_t buttonColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &buttonColor))
    {
        ImGui::PushStyleColor(ImGuiCol_ButtonHovered, buttonColor);
        ImGui::PushStyleColor(ImGuiCol_Button, buttonColor);

        popStyleColorCount += 2;
    }

    uint32_t borderColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &borderColor))
    {
        ImGui::PushStyleColor(ImGuiCol_Border, borderColor);

        popStyleColorCount += 1;
    }

    float borderWidth;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= this->getDpiScale();
        ImGui::PushStyleVar(ImGuiStyleVar_FrameBorderSize, borderWidth);

        popStyleVarCount += 1;
    }

    float rounding;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &rounding))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, rounding);

        popStyleVarCount += 1;
    }

    ImGuiStyle& style = ImGui::GetStyle();
    float paddingX = style.FramePadding.x * this->_getScale();
    float paddingY = style.FramePadding.y * this->_getScale();
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &paddingX))
    {
        paddingX *= this->getDpiScale();
        paddingY = paddingX;
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(paddingX, paddingY));
        popStyleVarCount += 1;
    }
    else
    {
        bool paddingChanged = false;
        if (this->_resolveStyleProperty(StyleFloatProperty::ePaddingWidth, &paddingX))
        {
            paddingX *= this->getDpiScale();
            paddingChanged = true;
        }
        if (this->_resolveStyleProperty(StyleFloatProperty::ePaddingHeight, &paddingY))
        {
            paddingY *= this->getDpiScale();
            paddingChanged = true;
        }
        if (paddingChanged)
        {
            ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(paddingX, paddingY));
            popStyleVarCount += 1;
        }
    }

    float windowPaddingX = style.WindowPadding.x * this->_getScale();
    float windowPaddingY = style.WindowPadding.y * this->_getScale();
    if (this->_resolveStyleProperty(StyleFloatProperty::eSecondaryPadding, &windowPaddingX))
    {
        windowPaddingX *= this->getDpiScale();
        windowPaddingY = windowPaddingX;
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(windowPaddingX, windowPaddingY));
        popStyleVarCount += 1;
    }

    ImGui::PushItemWidth(this->getComputedContentWidth());

    ImGuiComboFlags flags = ImGuiComboFlags_None;
    if (this->isArrowOnly())
    {
        flags |= ImGuiComboFlags_NoPreview;
        flags |= ImGuiComboFlags_PopupAlignLeft;
    }
    else if (this->isNoArrowButton())
    {
        flags |= ImGuiComboFlags_NoArrowButton;
    }

    auto& data = _getData< ComboBoxData>();
    int64_t currentIndex = data.m_currentIndex;

    // Without this the ComboBox will not be able to change because the name should be unique. Otherwise we need to use
    // PushID
    ImGui::PushID(this);

    this->_pushFont(*this);

    const char* previewValue = data.m_currentIndex < 0 || data.m_currentIndex >= static_cast<int64_t>(data.m_items.size()) ?
                                   "" :
        data.m_items[data.m_currentIndex].c_str();

    if (ImGui::BeginCombo("##hidelabel", previewValue, flags))
    {
        uint32_t selectionTextColor;
        bool pushedSelectionTextColor = false;
        if (this->_resolveStyleProperty(StyleColorProperty::eSecondarySelectedColor, &selectionTextColor))
        {
            ImGui::PushStyleColor(ImGuiCol_Text, selectionTextColor);
            pushedSelectionTextColor = true;
        }

        for (int64_t i = 0, n = static_cast<int64_t>(data.m_items.size()); i < n; ++i)
        {
            bool is_selected = i == data.m_currentIndex;
            if (ImGui::Selectable(data.m_items[i].c_str(), is_selected))
            {
                currentIndex = i;
            }

            if (is_selected)
            {
                ImGui::SetItemDefaultFocus();
            }
        }

        if (pushedSelectionTextColor)
        {
            ImGui::PopStyleColor();
        }

        ImGui::EndCombo();
    }

    this->_popFont();

    if (currentIndex != data.m_currentIndex)
    {
        // Selection is changed.
        // Can keep a refernce to the model, as it is only used once below
        const auto& model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            const auto& currentIndexModel = model->getItemValueModel();
            if (OMNIUI_LIKELY(currentIndexModel))
            {
                currentIndexModel->setValue(currentIndex);
            }
            else
            {
                OMNIUI_LOG_ERROR("ComboBox::_drawContent getItemValueModel returned an invalid index model");
            }
        }
        else
        {
            OMNIUI_LOG_ERROR("ComboBox::_drawContent had no model");
        }
    }

    ImGui::PopID();
    ImGui::PopItemWidth();
    ImGui::PopStyleColor(popStyleColorCount);
    ImGui::PopStyleVar(popStyleVarCount);
    ImGui::PopItemFlag();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
