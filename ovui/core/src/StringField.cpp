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
#include <omni/ui/StringField.h>

#include "StringFieldData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

StringField::StringField(std::shared_ptr<AbstractValueModel> model, StringFieldData* data) :
    AbstractField{ model, data ? data : new StringFieldData }
{
    if (!model)
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleStringModel::create());
    }
    else
    {
        this->onModelUpdated();
    }
}

StringField::StringField(const std::shared_ptr<AbstractValueModel>& model)
    : StringField(model, nullptr)
{
}

std::string StringField::_generateTextForField()
{
    const auto& model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("StringField::_generateTextForField had no model");
        return {};
    }

    return model->getValue<std::string>();
}

void StringField::_updateSystemText(void*)
{
    // Nothing to do. The field accepts every symbol.
}

int32_t StringField::_getSystemFlags() const
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

OMNIUI_NAMESPACE_CLOSE_SCOPE
