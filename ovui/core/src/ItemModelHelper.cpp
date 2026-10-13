/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/ItemModelHelper.h>

#include "ItemModelHelperData.h"


OMNIUI_NAMESPACE_OPEN_SCOPE

ItemModelHelper::ItemModelHelperData::~ItemModelHelperData()
{
}

ItemModelHelper::ItemModelHelper(std::shared_ptr<AbstractItemModel> inModel)
    : m_data(new ItemModelHelperData(std::move(inModel)))
{
    auto& model = _getModelData<ItemModelHelperData>().m_model;
    if (model)
    {
        model->subscribe(this);
    }
}

ItemModelHelper::~ItemModelHelper()
{
    auto& model = _getModelData<ItemModelHelperData>().m_model;
    if (model)
    {
        model->unsubscribe(this);
    }
}

void ItemModelHelper::setModel(std::shared_ptr<AbstractItemModel> model)
{
    auto& data = _getModelData<ItemModelHelperData>();
    if (data.m_model != model)
    {
        // Unsubscribe from the previous model.
        if (data.m_model)
        {
            data.m_model->unsubscribe(this);
        }

        data.m_model = model;

        // Subscribe to the new model.
        if (data.m_model)
        {
            data.m_model->subscribe(this);
        }

        // Update the current representation.
        this->onModelUpdated(nullptr);
    }
}

std::shared_ptr<AbstractItemModel> ItemModelHelper::getModel() const
{
    return _getModelData<ItemModelHelperData>().m_model;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
