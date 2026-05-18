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
#include <limits>
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/AbstractField.h>
#include <omni/ui/Rectangle.h>
#include <omni/ui/SimpleStringModel.h>
#include <omni/ui/StyleContainer.h>

#include "AbstractFieldData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

AbstractField::AbstractField(std::shared_ptr<AbstractValueModel> model, AbstractFieldData* data)
    : Widget(data ? data : new AbstractFieldData)
    , ValueModelHelper(std::move(model))
{
    // Don't push created object to any container
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        // TODO: `create()` should have an option skip parenting.
        auto& data = _getData<AbstractFieldData>();
        data.m_backgroundRect = Rectangle::create();
        data.m_backgroundRect->useMarginFromStyle(false);
    }

    // All the child classes will use name "Field" for styling. Because we have three of them and we suppose they should
    // look the same.
    this->setStyleTypeNameOverride("Field");

    this->_setScaleChangedFn([this](const auto& scale) {
        _getData<AbstractFieldData>().m_backgroundRect->setScale(scale);
    });
    this->_setCanvasZoomChangedFn([this](const auto& zoom) {
        _getData<AbstractFieldData>().m_backgroundRect->setCanvasZoom(zoom);
    });
}

AbstractField::~AbstractField() = default;

void AbstractField::setComputedContentWidth(float width)
{
    // The field can't be smaller than the height. We use height because it would be strange to have single line field
    // with width less than height.
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

    _getData<AbstractFieldData>().m_backgroundRect->setComputedContentWidth(width);
    Widget::setComputedContentWidth(width);
}

void AbstractField::setComputedContentHeight(float height)
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

    _getData<AbstractFieldData>().m_backgroundRect->setComputedContentHeight(height);
    Widget::setComputedContentHeight(height);
}

void AbstractField::onStyleUpdated()
{
    this->_updateFont(*this);


    // setStyleTypeNameOverride is here because it's not possible to call methods of child class from constructor.
    auto& data = _getData<AbstractFieldData>();
    data.m_backgroundRect->setStyleTypeNameOverride(this->_getStyleTypeName());

    // Propogate the style to the children. No necessary to call updateStyle if setStyle is called.
    data.m_backgroundRect->setStyle(this->_getResolvedStyle());
    data.m_backgroundRect->setName(this->getName());
}

void AbstractField::onModelUpdated()
{
    auto& data = _getData<AbstractFieldData>();
    data.m_textModelCache = this->_generateTextForField();

    if (!data.m_isModelChangedInternally)
    {
        // Set the flag that we need to force set the content. We need it because ImGui::InputTextEx ignores the input
        // data when the keyboard cursor is in it. And when InputTextEx has the keyboard cursor, the only way to change
        // the content is ImGuiInputTextFlags_CallbackAlways.
        data.m_forceContentChange = true;
    }

    // We can't pass m_textModelCache to ImGui::InputText because it will change it. Only model can decide if the value
    // is changed. When it's changed, AbstractField::onModelUpdated is called.
    // IMPORTANT NOTE: We use a vector to keep the ImGui buffer `m_textBuffer` because ImGui can set zero to the string
    // to make it smaller. This behavior is OK when working with const char, but if working with string, it makes the
    // string invalid and behaves unexpectedly. For example, it can be a string of five symbols length, but the first
    // symbol is zero, `string::empty()` is false. In other words, writing directly to a string buffer is wrong despite
    // the example in misc/cpp/imgui_stdlib.cpp.

    const size_t textModelCacheLength = data.m_textModelCache.length() + 1;
    if (data.m_textBuffer.size() < textModelCacheLength)
    {
        data.m_textBuffer.resize(textModelCacheLength);
    }

    std::copy(data.m_textModelCache.begin(), data.m_textModelCache.end(), data.m_textBuffer.data());
    data.m_textBuffer[data.m_textModelCache.length()] = '\0';

    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void AbstractField::focusKeyboard(bool focus)
{
    auto& data = _getData<AbstractFieldData>();
    data.m_focusKeyboard = focus;
    if (!focus)
    {
        data.m_underlyingId++;
    }
    else
    {
        this->forceRasterDirty(BakeDirtyReason::eContentChanged);
    }
}

void AbstractField::_drawContent(float elapsedTime)
{
    auto& data = _getData<AbstractFieldData>();

    bool enabled = this->isEnabled();
    ImGui::PushItemFlag(ImGuiItemFlags_Disabled, !enabled);

    // Replace the backgound with the rectangle because it already has everything for correct styling including gradient
    // and borders.
    data.m_backgroundRect->draw(elapsedTime);

    int32_t popStyleCount = 3;
    int32_t popStyleVarCount = 0;

    ImGuiStyle& style = ImGui::GetStyle();

    // Put background color to everything possible.
    ImGui::PushStyleColor(ImGuiCol_FrameBg, 0x0);
    ImGui::PushStyleColor(ImGuiCol_FrameBgActive, 0x0);
    ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, 0x0);

    uint32_t textColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &textColor))
    {
        ImGui::PushStyleColor(ImGuiCol_Text, textColor);
        ImGui::PushStyleColor(ImGuiCol_InputTextCursor, textColor);

        popStyleCount += 2;
    }

    uint32_t backgroundSelectedColor;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundSelectedColor, &backgroundSelectedColor))
    {
        ImGui::PushStyleColor(ImGuiCol_TextSelectedBg, backgroundSelectedColor);

        popStyleCount += 1;
    }

    float paddingX = style.FramePadding.x * this->_getScale();
    float paddingY = style.FramePadding.y * this->_getScale();
    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &paddingX))
    {
        paddingX *= this->getDpiScale();
        paddingY = paddingX;
    }
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(paddingX, paddingY));
    popStyleVarCount++;

    // Without this the field will not be able to change because the name should be unique. Otherwise we need to use
    // PushID
    ImGui::PushID(this);
    ImGui::PushID(data.m_underlyingId);

    ImVec2 size{ this->getComputedContentWidth(), this->getComputedContentHeight() };
    ImGuiInputTextFlags flags = ImGuiInputTextFlags_CallbackResize | this->_getSystemFlags();
    if (!(flags & ImGuiInputTextFlags_ReadOnly))
    {
        flags |= ImGuiInputTextFlags_CallbackAlways;
    }

    bool fieldWasActive = data.m_fieldActive;
    // InputTextEx will set m_fieldActive to true if it's active.
    data.m_fieldActive = false;

    this->_pushFont(*this);

    if (data.m_focusKeyboard)
    {
        ImGui::SetKeyboardFocusHere();
        data.m_focusKeyboard = false;
    }

    // We don't use InputFloat and InputInt even for float and int32_t fields because InputFloat and InputInt are very
    // limited. They don't have callbacks. We need callbacks to call beginEdit/endEdit. We have to always use InputText
    // because of callbacks. We use InputTextEx because unlike InputText, it has the size.
    bool result =
        ImGui::InputTextEx("##hidelabel", nullptr, data.m_textBuffer.data(), static_cast<int32_t>(data.m_textBuffer.size()), size,
                           flags, reinterpret_cast<ImGuiInputTextCallback>(AbstractField::_onInputTextActive), this);

    this->_popFont();

    if (!fieldWasActive && data.m_fieldActive)
    {
        // The user started editing.
        auto model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            model->processBeginEditCallbacks();
            this->forceRasterDirty(BakeDirtyReason::eEditBegan);
        }
        else
        {
            OMNIUI_LOG_ERROR("AbstractField::_drawContent had no model");
        }
    }

    if (result)
    {
        auto model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            data.m_isModelChangedInternally = true;

            // Trying to set the value. If the model accepts it, it will call onModelUpdated and update m_textBuffer.
            model->setValue(std::string{ data.m_textBuffer.data() });

            data.m_isModelChangedInternally = false;
        }
        else
        {
            OMNIUI_LOG_ERROR("AbstractField::_drawContent had no model");
        }

        // But if it doesn't accept it, we need to restore m_textBuffer.
        if (data.m_textModelCache != data.m_textBuffer.data())
        {
            std::copy(data.m_textModelCache.begin(), data.m_textModelCache.end(), data.m_textBuffer.data());
            data.m_textBuffer[data.m_textModelCache.length()] = '\0';
        }
    }

    if (fieldWasActive && !data.m_fieldActive)
    {
        // The user finished editing.
        auto model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            model->processEndEditCallbacks();
            this->forceRasterDirty(BakeDirtyReason::eEditEnded);
        }
        else
        {
            OMNIUI_LOG_ERROR("AbstractField::_drawContent had no model");
        }
    }

    ImGui::PopID();
    ImGui::PopID();
    ImGui::PopStyleColor(popStyleCount);
    ImGui::PopStyleVar(popStyleVarCount);
    ImGui::PopItemFlag();
}

int32_t AbstractField::_onInputTextActive(void* data)
{
    auto imGuiData = reinterpret_cast<ImGuiInputTextCallbackData*>(data);
    AbstractField* field = reinterpret_cast<AbstractField*>(imGuiData->UserData);
    auto& fieldData = field->_getData<AbstractFieldData>();

    if (imGuiData->EventFlag == ImGuiInputTextFlags_CallbackAlways)
    {
        fieldData.m_fieldActive = true;

        if (fieldData.m_forceContentChange)
        {
            // We are here because ImGui::InputTextEx has the keyboard cursor in it and it ignores input data. The only
            // way to change the content is using ImGuiInputTextFlags_CallbackAlways.

            // If we do `imGuiData->Buf = fieldData.m_textBuffer.data()`, ImGui's assertion is failed because ImGui expects
            // the new data is written to the provided buffer. The buffer size should be good because when InputTextEx
            // has keyboard cursor in it, it ignores buf, not buf_size. We passed the correct buf_size to InputTextEx
            // and here we should have correct size.
            OMNIUI_ASSERT(imGuiData->BufSize >= static_cast<int32_t>(fieldData.m_textBuffer.size()));

            // Find actual string length in source buffer (up to null terminator)
            const char* src = fieldData.m_textBuffer.data();
            const size_t maxSrcLen = fieldData.m_textBuffer.size();
            const size_t maxDestLen = static_cast<size_t>(std::max(0, imGuiData->BufSize - 1)); // Reserve space for null terminator

            size_t actualStrLen = 0;
            while (actualStrLen < maxSrcLen && actualStrLen < maxDestLen && src[actualStrLen] != '\0')
            {
                actualStrLen++;
            }

            // Copy only the actual string content (not garbage beyond null terminator)
            for (size_t i = 0; i < actualStrLen; ++i)
            {
                imGuiData->Buf[i] = src[i];
            }

            // Null-terminate and set length
            imGuiData->Buf[actualStrLen] = '\0';
            imGuiData->BufTextLen = static_cast<int32_t>(actualStrLen);

            imGuiData->BufDirty = true;
            imGuiData->CursorPos = imGuiData->BufTextLen;
            fieldData.m_forceContentChange = false;
        }
    }
    else if (imGuiData->EventFlag == ImGuiInputTextFlags_CallbackResize)
    {
        // Resize string callback. Reference: misc/cpp/imgui_stdlib.cpp
        assert(imGuiData->Buf == fieldData.m_textBuffer.data());

        size_t imGuiDataLength = imGuiData->BufTextLen + 1;
        if (fieldData.m_textBuffer.size() < imGuiDataLength)
        {
            fieldData.m_textBuffer.resize(imGuiDataLength);
            fieldData.m_textBuffer[imGuiDataLength - 1] = '\0';
            imGuiData->Buf = fieldData.m_textBuffer.data();
        }
    }

    field->_updateSystemText(data);

    return 0;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
