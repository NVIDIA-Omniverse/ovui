/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/ValueModelHelper.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct ValueModelHelper::ValueModelHelperData
{
    ValueModelHelperData(std::shared_ptr<AbstractValueModel> model) : m_model(std::move(model)) {}

    virtual ~ValueModelHelperData();

    std::shared_ptr<AbstractValueModel> m_model = {};

};

OMNIUI_NAMESPACE_CLOSE_SCOPE
