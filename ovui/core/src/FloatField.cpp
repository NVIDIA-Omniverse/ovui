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
#include <omni/ui/FloatField.h>
#include <omni/ui/FloatSlider.h>
#include <omni/ui/SimpleNumericModel.h>

#include <algorithm>
#include <sstream>

OMNIUI_NAMESPACE_OPEN_SCOPE

FloatField::FloatField(std::shared_ptr<AbstractValueModel> model)
    : AbstractField(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleFloatModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated();
    }
}

std::string FloatField::_generateTextForField()
{
    const auto& model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("FloatField::_generateTextForField had no model");
        return {};
    }

    constexpr size_t size = 64;
    std::unique_ptr<char[]> buf(new char[size]);

    double value = model->getValue<double>();
    snprintf(buf.get(), size, FloatSlider::getFormatString(value, this->getPrecision()), value);

    return { buf.get() };
}

void FloatField::_updateSystemText(void*)
{
    // Nothing to do. We already specified ImGuiInputTextFlags_CharsScientific.
}

int32_t FloatField::_getSystemFlags() const
{
    return ImGuiInputTextFlags_CharsScientific;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
