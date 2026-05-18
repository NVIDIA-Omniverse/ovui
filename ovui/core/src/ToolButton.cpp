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
#include <omni/ui/SimpleNumericModel.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/ToolButton.h>

#include "ButtonData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct ToolButton::ToolButtonData : public Button::ButtonData
{
    ~ToolButtonData() override = default;

    // Flag to call onModelUpdated
    bool m_modelUpdated = false;
};

ToolButton::ToolButton(const std::shared_ptr<AbstractValueModel>& model)
    : Button({}, new ToolButtonData)
    , ValueModelHelper(model)
{
    // By default using style from Button
    this->setStyleTypeNameOverride(Button::getTypeName());

    if (!model)
    {
        // If there is no model, create a simple one.
        this->setModel(SimpleBoolModel::create());
    }
}

ToolButton::~ToolButton() = default;

void ToolButton::onModelUpdated()
{
    auto model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("ToolButton::onModelUpdated had not model");
        return;
    }

    // Grab the value from the model.
    this->setChecked(model->getValue<bool>());

    this->forceRasterDirty(BakeDirtyReason::eContentChanged);
}

void ToolButton::_drawContent(float elapsedTime)
{
    auto& data = _getData<ToolButtonData>();
    if (!data.m_modelUpdated)
    {
        // We can't update the model in the initialization time because the parent sets the `checked` property as soon
        // as the widget is created. We set it only once on the render time.
        data.m_modelUpdated = true;
        this->onModelUpdated();
    }

    Button::_drawContent(elapsedTime);
}

void ToolButton::_clicked()
{
    auto model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("ToolButton::_clicked had no model");
        return;
    }

    // Toggle
    model->setValue(!model->getValue<bool>());
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
