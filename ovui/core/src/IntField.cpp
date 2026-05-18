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
#include <omni/ui/IntField.h>
#include <omni/ui/SimpleNumericModel.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

IntField::IntField(std::shared_ptr<AbstractValueModel> model)
    : AbstractField(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleIntModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated();
    }
}

std::string IntField::_generateTextForField()
{
    const auto& model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("IntField::_generateTextForField had no model");
        return {};
    }

    return std::to_string(model->getValue<int64_t>());
}

void IntField::_updateSystemText(void*)
{
    // TODO: Limit entered symbold with [0..9]
}

int32_t IntField::_getSystemFlags() const
{
    return ImGuiInputTextFlags_CharsDecimal;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
