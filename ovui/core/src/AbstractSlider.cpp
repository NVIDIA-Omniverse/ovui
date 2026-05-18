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
#include <omni/ui/AbstractSlider.h>
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/StyleContainer.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

AbstractSlider::AbstractSlider(std::shared_ptr<AbstractValueModel> model, WidgetData* data)
    : Widget(data)
    , ValueModelHelper(std::move(model))
{
    // All the child classes will use name "Slider" for styling. Because we have three of them and we suppose they
    // should look the same.
    this->setStyleTypeNameOverride("Slider");
}

AbstractSlider::~AbstractSlider() = default;

void AbstractSlider::setComputedContentHeight(float height)
{
    // The field can't be smaller than ImGui style.
    this->_pushFont(*this);

    uint32_t textColor = 0;
    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &textColor) && textColor == 0)
    {
        // Text color is transparent, use preset height but min=1
        height = std::max(this->getDpiScale(), height);
    }
    else
    {
        // Recalculate height when text color is not transparent
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
    }

    this->_popFont();

    Widget::setComputedContentHeight(height);
}

void AbstractSlider::onStyleUpdated()
{
    this->_updateFont(*this);
}

void AbstractSlider::_drawContent(float elapsedTime)
{
    int32_t popStyleCount = 0, popFloatCount = 0;
    bool enabled = this->isEnabled();
    ImGui::PushItemFlag(ImGuiItemFlags_Disabled, !enabled);

    float dpiScale = this->getDpiScale();

    uint32_t drawMode = static_cast<uint32_t>(DrawMode::eFilled);
    this->_resolveStyleProperty(StyleEnumProperty::eDrawMode, &drawMode);
    DrawMode styleMode = static_cast<DrawMode>(drawMode);
    if (styleMode == DrawMode::eFilled)
    {
        // in Filled Mode both Seconday and Background color are required
        // if they are not set we should find a way to warn the user
        // for now we modulate the background color to a darker version

        uint32_t backgroundColor = 0x0;
        this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &backgroundColor);

        uint32_t secondaryColor = 0x0;
        if (!this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &secondaryColor))
        {
            secondaryColor = static_cast<uint32_t>(backgroundColor / 2);
        }

        // if the background color is 0x0 and no secondary color was provided
        // what should we do ?
        if (secondaryColor && backgroundColor)
        {
            auto cursor = ImGui::GetCursorScreenPos();

            // draw Left side Fill
            float computedWidth = this->getComputedContentWidth();
            float computedHeight = this->getComputedContentHeight();
            ImVec2 rectMax{ cursor.x + computedWidth * this->_getValueRatio(), cursor.y + computedHeight };

            ImVec2 cursorFull{ rectMax.x, cursor.y };
            ImVec2 rectFull{ cursor.x + computedWidth, cursor.y + computedHeight };

            float cornerRadius = 0;
            this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &cornerRadius);
            cornerRadius *= dpiScale;

            auto drawList = ImGui::GetWindowDrawList();

            // When the clipping has the same boundaries as the rectangle, the border is jittering. To avoid it we
            // outline the clipping rect.
            constexpr float outline = 10.f;

            // Left rect
            drawList->PushClipRect(ImFloor(ImVec2{ cursor.x - outline, cursor.y - outline }),
                                   ImFloor(ImVec2{ rectMax.x, rectMax.y + outline }), true);
            drawList->AddRectFilled(ImFloor(cursor), ImFloor(rectFull), secondaryColor, cornerRadius);
            drawList->PopClipRect();

            // Right rect
            drawList->PushClipRect(ImFloor(ImVec2{ cursorFull.x, cursorFull.y - outline }),
                                   ImFloor(ImVec2{ rectFull.x + outline, rectFull.y + outline }), true);
            drawList->AddRectFilled(ImFloor(cursor), ImFloor(rectFull), backgroundColor, cornerRadius);
            drawList->PopClipRect();

            ImGui::PushStyleColor(ImGuiCol_FrameBg, 0x0);
            ImGui::PushStyleColor(ImGuiCol_FrameBgActive, 0x0);
            ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, 0x0);

            ImGui::PushStyleColor(ImGuiCol_SliderGrab, 0x0);
            ImGui::PushStyleColor(ImGuiCol_SliderGrabActive, 0x0);
            popStyleCount += 5;
        }
    }
    else // DrawMode::eHandle or DrawMode::eDrag
    {
        uint32_t backgroundColor;
        if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &backgroundColor))
        {
            // Put background color to everything possible.
            ImGui::PushStyleColor(ImGuiCol_FrameBg, backgroundColor);
            ImGui::PushStyleColor(ImGuiCol_FrameBgActive, backgroundColor);
            ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, backgroundColor);

            popStyleCount += 3;
        }

        uint32_t secondaryColor;
        if (this->_resolveStyleProperty(StyleColorProperty::eSecondaryColor, &secondaryColor))
        {
            ImGui::PushStyleColor(ImGuiCol_SliderGrab, secondaryColor);

            popStyleCount += 1;
        }

        uint32_t secondarySelectedColor;
        if (this->_resolveStyleProperty(StyleColorProperty::eSecondarySelectedColor, &secondarySelectedColor))
        {
            ImGui::PushStyleColor(ImGuiCol_SliderGrabActive, secondarySelectedColor);

            popStyleCount += 1;
        }
    }

    float cornerRadius = 0;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &cornerRadius))
    {
        cornerRadius *= dpiScale;
        ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, cornerRadius);
        popFloatCount += 1;
    }

    float borderWidth = 0;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
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

    uint32_t textColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &textColor))
    {
        ImGui::PushStyleColor(ImGuiCol_Text, textColor);

        popStyleCount += 1;
    }

    // Without this the field will not be able to change because the name should be unique. Otherwise we need to use
    // PushID
    ImGui::PushID(this);

    ImGui::SetNextItemWidth(this->getComputedContentWidth());
    // TODO: since we can't control height of this widget, we need to add vertical alignment.

    float padding;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= dpiScale;
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
        popFloatCount += 1;
    }

    this->_pushFont(*this);

    this->_drawUnderlyingItem();

    this->_popFont();

    ImGui::PopID();

    ImGui::PopStyleColor(popStyleCount);
    ImGui::PopStyleVar(popFloatCount);
    ImGui::PopItemFlag();
}

void AbstractSlider::_beginModelChange()
{
    if (!m_editActive && ImGui::IsItemActivated())
    {
        m_editActive = true;
        auto model = this->getModel();
        if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
        {
            OMNIUI_LOG_ERROR("AbstractSlider::_beginModelChange had no model");
            return;
        }

        model->processBeginEditCallbacks();
        this->forceRasterDirty(BakeDirtyReason::eEditBegan);
    }
}

void AbstractSlider::_endModelChange()
{
    if (m_editActive && !ImGui::IsItemActive())
    {
        // The user finished editing.
        m_editActive = false;

        auto model = this->getModel();
        if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
        {
            OMNIUI_LOG_ERROR("AbstractSlider::_beginModelChange had no model");
            return;
        }

        model->processEndEditCallbacks();
        this->forceRasterDirty(BakeDirtyReason::eEditEnded);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
