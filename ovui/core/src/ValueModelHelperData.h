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
