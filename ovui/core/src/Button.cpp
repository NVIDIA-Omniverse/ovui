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

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Alignment.h>
#include <omni/ui/Button.h>
#include <omni/ui/HStack.h>
#include <omni/ui/Image.h>
#include <omni/ui/Label.h>
#include <omni/ui/Rectangle.h>
#include <omni/ui/Spacer.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/VStack.h>
#include <omni/ui/ZStack.h>

#include "ButtonData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

Button::ButtonData::~ButtonData()
{
}

Button::Button(const std::string& text, ButtonData* dataPtr)
    : InvisibleButton(dataPtr ? dataPtr : new ButtonData)
{
    auto& data = _getData<ButtonData>();

    this->setText(text);
    // Don't push created object to any container
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        data.m_rectangleWidget = Rectangle::create();
        data.m_rectangleWidget->useMarginFromStyle(false);

        data.m_labelImageLayout = Stack::create(Stack::Direction::eTopToBottom);
        data.m_labelImageLayout->useMarginFromStyle(false);
    }

    data.m_rectangleWidget->setParent(this);
    data.m_labelImageLayout->setParent(this);

    OMNIKIT_WITH_CONTAINER(data.m_labelImageLayout)
    {
        data.m_imageWidget = Image::create();
        data.m_imageWidget->setVisible(false);
        data.m_imageWidget->setAlignment(Alignment::eCenter);

        data.m_labelWidget = Label::create(text);
        data.m_labelWidget->setVisible(!text.empty());
        data.m_labelWidget->setAlignment(Alignment::eCenter);
    }

    // The sub-widgets should query the button style.
    this->setTextChangedFn([this](const auto& s) {
        auto& data = _getData<ButtonData>();
        data.m_labelWidget->setVisible(!s.empty());
        data.m_labelWidget->setText(s);
        data.m_minimalContentSizeComputed = false;
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
    });

    // Property redirection for image
    this->setImageUrlChangedFn([this](const std::string& url) {
        auto& data = _getData<ButtonData>();
        data.m_imageWidget->setSourceUrl(url);
        data.m_imageWidget->setVisible(data.m_imageWidget->hasSourceUrl());
    });
    this->setImageWidthChangedFn([this](const Length& width) {
        auto& data = _getData<ButtonData>();
        data.m_imageWidget->setWidth(width);
    });
    this->setImageHeightChangedFn([this](const Length& height) {
        auto& data = _getData<ButtonData>();
        data.m_imageWidget->setHeight(height);
    });

    this->setSpacingChangedFn([this](const float& spacing) {
        auto& data = _getData<ButtonData>();
        data.m_labelImageLayout->setSpacing(spacing);
    });

    this->setSelectedChangedFn([this](const auto& selected) {
        auto& data = _getData<ButtonData>();
        data.m_rectangleWidget->setSelected(selected);
        data.m_labelImageLayout->setSelected(selected);
    });
    this->setCheckedChangedFn([this](const auto& checked) {
        auto& data = _getData<ButtonData>();
        data.m_rectangleWidget->setChecked(checked);
        data.m_labelImageLayout->setChecked(checked);
    });
    this->setEnabledChangedFn([this](const auto& enabled) {
        auto& data = _getData<ButtonData>();
        data.m_rectangleWidget->setEnabled(enabled);
        data.m_labelImageLayout->setEnabled(enabled);
    });
    this->_setScaleChangedFn([this](const auto& scale) {
        auto& data = _getData<ButtonData>();
        data.m_rectangleWidget->setScale(scale);
        data.m_labelImageLayout->setScale(scale);
        data.m_minimalContentSizeComputed = false;
    });
    this->_setCanvasZoomChangedFn([this](const auto& zoom) {
        auto& data = _getData<ButtonData>();
        data.m_rectangleWidget->setCanvasZoom(zoom);
        data.m_labelImageLayout->setCanvasZoom(zoom);
        data.m_minimalContentSizeComputed = false;
    });
}

Button::~Button() = default;

void Button::destroy()
{
    auto& data = _getData<ButtonData>();

    data.m_rectangleWidget->destroy();
    data.m_rectangleWidget->setParent(nullptr);

    data.m_labelImageLayout->destroy();
    data.m_labelImageLayout->setParent(nullptr);

    Widget::destroy();
}

void Button::setComputedContentWidth(float width)
{
    // We follow the box model:
    // |---------------------------------|
    // |   Margin (applied in Widget)    |
    // |  |---------------------------|  |
    // |  |          Border           |  |
    // |  |  |---------------------|  |  |
    // |  |  |       Padding       |  |  |
    // |  |  |  |---------------|  |  |  |
    // |  |  |  |    Content    |  |  |  |
    // |  |  |  |---------------|  |  |  |
    // |  |  |---------------------|  |  |
    // |  |---------------------------|  |
    // |---------------------------------|

    this->_computeButtonSize();

    float dpiScale = this->getDpiScale();

    // Get padding.
    float padding;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= dpiScale;
    }
    else
    {
        auto& style = ImGui::GetStyle();
        padding = style.FramePadding.x;
    }

    auto& data = _getData<ButtonData>();
    data.m_labelImageLayout->forceWidthDirty(SizeDirtyReason::eParentDirty);
    data.m_rectangleWidget->forceWidthDirty(SizeDirtyReason::eParentDirty);

    // Apply padding to the size.
    width = std::max(width - padding * 2.0f, data.m_minimalContentWidth);
    data.m_labelImageLayout->setComputedWidth(width);
    width = data.m_labelImageLayout->getComputedWidth() + padding * 2.0f;

    data.m_rectangleWidget->setComputedWidth(width);

    InvisibleButton::setComputedContentWidth(width);
}

void Button::setComputedContentHeight(float height)
{
    this->_computeButtonSize();

    float dpiScale = this->getDpiScale();

    // Get padding.
    float padding;
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &padding))
    {
        padding *= dpiScale;
    }
    else
    {
        auto& imGuiStyle = ImGui::GetStyle();
        padding = imGuiStyle.FramePadding.y;
    }

    auto& data = _getData<ButtonData>();
    data.m_labelImageLayout->forceHeightDirty(SizeDirtyReason::eParentDirty);
    data.m_rectangleWidget->forceHeightDirty(SizeDirtyReason::eParentDirty);

    // Apply padding to the size.
    height = std::max(height - padding * 2.0f, data.m_minimalContentHeight);
    data.m_labelImageLayout->setComputedHeight(height);
    height = data.m_labelImageLayout->getComputedHeight() + padding * 2.0f;

    data.m_rectangleWidget->setComputedHeight(height);

    InvisibleButton::setComputedContentHeight(height);
}

void Button::onStyleUpdated()
{
    auto& data = _getData<ButtonData>();

    // Propogate the type to the children.
    data.m_rectangleWidget->setStyleTypeNameOverride(this->_getStyleTypeName());
    data.m_labelWidget->setStyleTypeNameOverride(this->_childTypeName(data.m_labelWidget->getTypeName()));
    data.m_imageWidget->setStyleTypeNameOverride(this->_childTypeName(data.m_imageWidget->getTypeName()));

    // Propogate name to children
    data.m_labelImageLayout->setName(this->getName());
    data.m_rectangleWidget->setName(this->getName());
    data.m_labelWidget->setName(this->getName());
    data.m_imageWidget->setName(this->getName());

    // Recompute minimal size
    data.m_minimalContentSizeComputed = false;

    // Check the image visibility
    data.m_imageVisibilityUpdated = false;
}

void Button::cascadeStyle()
{
    Widget::cascadeStyle();

    auto& data = _getData<ButtonData>();
    data.m_rectangleWidget->cascadeStyle();
    data.m_labelImageLayout->cascadeStyle();
}

void Button::_drawContent(float elapsedTime)
{
    auto& data = _getData<ButtonData>();

    // Draw rectangle
    if (!isWindowHovered())
    {
        data.m_rectangleWidget->setExplicitHover(this->isExplicitHover());
    }
    else
    {
        data.m_rectangleWidget->setExplicitHover(false);
    }
    data.m_rectangleWidget->draw(elapsedTime);

    auto cursor = ImGui::GetCursorScreenPos();

    // Put layout with text and image to center
    auto cursorToCenterLayout = cursor;
    cursorToCenterLayout.x += (data.m_rectangleWidget->getComputedWidth() - data.m_labelImageLayout->getComputedWidth()) * 0.5f;
    cursorToCenterLayout.y += (data.m_rectangleWidget->getComputedHeight() - data.m_labelImageLayout->getComputedHeight()) * 0.5f;
    ImGui::SetCursorScreenPos(cursorToCenterLayout);

    // Draw label and image
    data.m_labelImageLayout->draw(elapsedTime);

    // Draw invisible button to have the same signals
    ImGui::SetCursorScreenPos(cursor);
    InvisibleButton::_drawContent(elapsedTime);
}

void Button::_computeButtonSize()
{
    auto& data = _getData<ButtonData>();
    if (data.m_minimalContentSizeComputed)
    {
        return;
    }

    if (!data.m_imageVisibilityUpdated)
    {
        // Set the image visibility depending on the content of this image.
        data.m_imageWidget->setVisible(data.m_imageWidget->hasSourceUrl());
        data.m_imageVisibilityUpdated = true;
    }

    // Set direction of the Label-Image layout
    auto stackDirectionStyle = static_cast<uint32_t>(Stack::Direction::eTopToBottom);
    this->_resolveStyleProperty(StyleEnumProperty::eStackDirection, &stackDirectionStyle);
    auto stackDirection = static_cast<Stack::Direction>(stackDirectionStyle);
    data.m_labelImageLayout->setDirection(stackDirection);

    // Computing minimal size of text label.
    data.m_labelImageLayout->setComputedContentWidth(0);
    data.m_labelImageLayout->setComputedContentHeight(0);
    data.m_minimalContentWidth = data.m_labelImageLayout->getComputedContentWidth();
    data.m_minimalContentHeight = data.m_labelImageLayout->getComputedContentHeight();

    data.m_minimalContentSizeComputed = true;
}

std::string Button::_childTypeName(const std::string& childType) const
{
    return this->_getStyleTypeName() + "." + childType;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
