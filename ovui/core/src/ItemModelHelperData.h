/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/ItemModelHelper.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct ItemModelHelper::ItemModelHelperData
{
    static ItemModelHelperData& getData(const ItemModelHelper* helper)
    {
        return static_cast<ItemModelHelperData&>(*helper->m_data);
    }

    ItemModelHelperData(std::shared_ptr<AbstractItemModel> model) : m_model(std::move(model)) {}

    virtual ~ItemModelHelperData();

    std::shared_ptr<AbstractItemModel> m_model = {};

};

OMNIUI_NAMESPACE_CLOSE_SCOPE
