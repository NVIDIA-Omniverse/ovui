/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/ValueModelHelper.h>

#include "ValueModelHelperData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

ValueModelHelper::ValueModelHelperData::~ValueModelHelperData()
{
}

ValueModelHelper::ValueModelHelper(ValueModelHelperData* dataPtr)
    : m_data(dataPtr)
{
    auto& model = _getModelData<ValueModelHelperData>().m_model;
    if (model)
    {
        model->subscribe(this);
    }
}

ValueModelHelper::ValueModelHelper(std::shared_ptr<AbstractValueModel> model)
    : ValueModelHelper(new ValueModelHelperData(std::move(model)))
{
}

ValueModelHelper::~ValueModelHelper()
{
    auto& data = _getModelData<ValueModelHelperData>();
    if (data.m_model)
    {
        data.m_model->unsubscribe(this);
    }
}

void ValueModelHelper::setModel(std::shared_ptr<AbstractValueModel> model)
{
    auto& data = _getModelData<ValueModelHelperData>();
    if (data.m_model != model)
    {
        // Unsubscribe from the previous model.
        if (data.m_model)
        {
            data.m_model->unsubscribe(this);
        }

        data.m_model = std::move(model);

        // Subscribe to the new model.
        if (data.m_model)
        {
            data.m_model->subscribe(this);

            // Update the current representation.
            this->onModelUpdated();
        }
    }
}

std::shared_ptr<AbstractValueModel> ValueModelHelper::getModel() const
{
    return _getModelData<ValueModelHelperData>().m_model;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
