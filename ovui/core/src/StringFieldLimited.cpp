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
#include <omni/ui/SimpleStringModel.h>
#include <omni/ui/StringFieldLimited.h>

#include "StringFieldData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct StringFieldLimited::StringFieldLimitedData : public StringField::StringFieldData
{
    ~StringFieldLimitedData() override = default;

    bool atCharacterLimit = false;
    bool wasAtCharacterLimit = false;
    bool isInternalUpdate = false;
};

StringFieldLimited::StringFieldLimited(std::shared_ptr<AbstractValueModel> model) :
    StringField{ model, new StringFieldLimited::StringFieldLimitedData }
{
}

std::string StringFieldLimited::_generateTextForField()
{
    const auto& model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("StringFieldLimited::_generateTextForField had no model");
        return {};
    }

    std::string value = model->getValue<std::string>();

    uint32_t maxLen = this->getMaxLength();
    if (maxLen > 0)
    {
        _getData<StringFieldLimited::StringFieldLimitedData>().atCharacterLimit = (value.length() >= maxLen);
    }

    return value;
}

void StringFieldLimited::onModelUpdated()
{
    auto& data = _getData<StringFieldLimited::StringFieldLimitedData>();

    if (data.isInternalUpdate)
    {
        StringField::onModelUpdated();
        return;
    }

    uint32_t maxLen = this->getMaxLength();
    if (maxLen > 0)
    {
        auto model = this->getModel();
        if (model)
        {
            std::string value = model->getValue<std::string>();
            if (value.length() > maxLen)
            {
                std::string truncated = value.substr(0, maxLen);
                data.isInternalUpdate = true;
                model->setValue(truncated);
                data.isInternalUpdate = false;
                data.atCharacterLimit = true;
                this->forceRasterDirty(BakeDirtyReason::eContentChanged);
                return;
            }
        }
    }

    StringField::onModelUpdated();
}

void StringFieldLimited::_updateSystemText(void* rawData)
{
    auto imGuiData = reinterpret_cast<ImGuiInputTextCallbackData*>(rawData);
    auto& data = _getData<StringFieldLimited::StringFieldLimitedData>();

    uint32_t maxLen = this->getMaxLength();
    if (maxLen > 0)
    {
        int32_t currentLength = static_cast<int32_t>(imGuiData->BufTextLen);
        int32_t limit = static_cast<int32_t>(maxLen);

        if (currentLength > limit)
        {
            imGuiData->Buf[limit] = '\0';
            imGuiData->BufTextLen = limit;
            imGuiData->BufDirty = true;

            if (imGuiData->CursorPos > limit)
            {
                imGuiData->CursorPos = limit;
            }
            if (imGuiData->SelectionStart > limit)
            {
                imGuiData->SelectionStart = limit;
            }
            if (imGuiData->SelectionEnd > limit)
            {
                imGuiData->SelectionEnd = limit;
            }

            data.atCharacterLimit = true;
        }
        else
        {
            data.atCharacterLimit = (currentLength >= limit);
        }
    }
    else if (data.atCharacterLimit)
    {
        data.atCharacterLimit = false;
    }
}

int32_t StringFieldLimited::_getSystemFlags() const
{
    ImGuiInputTextFlags flags = ImGuiInputTextFlags_None;

    if (this->isPasswordMode())
    {
        flags |= (ImGuiInputTextFlags_Password | ImGuiInputTextFlags_CharsNoBlank);
    }

    if (this->isReadOnly())
    {
        flags |= ImGuiInputTextFlags_ReadOnly;
    }

    if (this->isMultiline())
    {
        flags |= ImGuiInputTextFlags_Multiline;
    }

    if (this->isTabInputAllowed())
    {
        flags |= ImGuiInputTextFlags_AllowTabInput;
    }

    return flags;
}

void StringFieldLimited::_drawContent(float elapsedTime)
{
    StringField::_drawContent(elapsedTime);

    auto& data = _getData<StringFieldLimited::StringFieldLimitedData>();

    uint32_t maxLen = this->getMaxLength();
    if (maxLen > 0)
    {
        bool stateChanged = (data.atCharacterLimit != data.wasAtCharacterLimit);
        if (stateChanged && this->hasCharacterLimitReachedFn())
        {
            this->callCharacterLimitReachedFn(data.atCharacterLimit);
        }
        data.wasAtCharacterLimit = data.atCharacterLimit;
    }
    else
    {
        data.wasAtCharacterLimit = false;
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
