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
#include <omni/ui/CheckBox.h>
#include <omni/ui/SimpleNumericModel.h>
#include <omni/ui/StyleContainer.h>

#include "WidgetData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct CheckBox::CheckBoxData : public Widget::WidgetData
{
    ~CheckBoxData() override = default;

    // The state of the checkbox. We need to cache it anyway. Because we can't query the model every frame because the
    // model can be written in python and query filesystem or USD. Of course, it can be cached on the Model level, but
    // it means we ask the user to cache it, which is not preferable. Right now, we allow the model to do very expensive
    // operations.
    bool m_value = false;
};


CheckBox::CheckBox(std::shared_ptr<AbstractValueModel> model)
    : Widget(new CheckBoxData)
    , ValueModelHelper(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple one.
        this->setModel(SimpleBoolModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated();
    }
}

CheckBox::~CheckBox() = default;

void CheckBox::setComputedContentWidth(float width)
{
    // The field can't be smaller than ImGui style.
    this->_pushFont(*this);
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0, 0));
    width = std::max(ImGui::GetFrameHeight(), width);
    ImGui::PopStyleVar(1);
    this->_popFont();

    // TODO: We need to set the size from the style. We now take the checkbox size from ImGui.
    Widget::setComputedContentWidth(width);
}

void CheckBox::setComputedContentHeight(float height)
{
    // The field can't be smaller than ImGui style.
    this->_pushFont(*this);
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0, 0));
    height = std::max(ImGui::GetFrameHeight(), height);
    ImGui::PopStyleVar(1);
    this->_popFont();

    // TODO: We need to set the size from the style. We now take the checkbox size from ImGui.
    Widget::setComputedContentHeight(height);
}

void CheckBox::onStyleUpdated()
{
    this->_updateFont(*this);
}

void CheckBox::onModelUpdated()
{
    // Grab the value from the model.
    const auto& model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("CheckBox::onModelUpdated had no model");
        return;
    }

    _getData<CheckBoxData>().m_value = model->getValue<bool>();

    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void CheckBox::_drawContent(float elapsedTime)
{
    int32_t popStyleCount = 0;
    int32_t popStyleVarCount = 0;

    // Enter the checked state depending on the value of m_value
    // This enables custom styling for the :checked state selector
    this->setChecked(_getData<CheckBoxData>().m_value);

    uint32_t backgroundColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &backgroundColor))
    {
        // Put background color to everything possible.
        ImGui::PushStyleColor(ImGuiCol_FrameBg, backgroundColor);
        ImGui::PushStyleColor(ImGuiCol_FrameBgActive, backgroundColor);
        ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, backgroundColor);

        popStyleCount += 3;
    }

    uint32_t checkMarkColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &checkMarkColor))
    {
        ImGui::PushStyleColor(ImGuiCol_CheckMark, checkMarkColor);

        popStyleCount += 1;
    }

    float rounding;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &rounding))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, rounding);

        popStyleVarCount += 1;
    }

    // Map the secondary background color to the border color
    uint32_t borderColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eSecondaryBackgroundColor, &borderColor))
    {
        ImGui::PushStyleColor(ImGuiCol_Border, borderColor);
        popStyleCount += 1;
    }

    // Map the border width to the frame border size
    float borderWidth;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_FrameBorderSize, borderWidth);
        popStyleVarCount += 1;
    }


    // Without this the checkbox will not be able to change because the name should be unique. Otherwise we need to use
    // PushID
    ImGui::PushID(this);

    // We can't pass m_value to ImGui::Checkbox because it will change it. Only model can decide if the value is
    // changed. When it's changed, CheckBox::onModelUpdated is called.
    bool value = _getData<CheckBoxData>().m_value;

    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0, 0));
    popStyleVarCount += 1;

    this->_pushFont(*this);

    bool enabled = this->isEnabled();
    ImGui::PushItemFlag(ImGuiItemFlags_Disabled, !enabled);

    // TODO: Align it
    if (ImGui::Checkbox("##hidelabel", &value) && enabled)
    {
        auto model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            // Trying to set the value. If the model accepts it, it will call CheckBox::onModelUpdated.
            model->setValue(value);
        }
        else
        {
            OMNIUI_LOG_ERROR("CheckBox::_drawContent had no model");
        }
    }

    ImGui::PopItemFlag();

    this->_popFont();

    ImGui::PopID();
    ImGui::PopStyleColor(popStyleCount);
    ImGui::PopStyleVar(popStyleVarCount);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
