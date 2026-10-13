/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/AbstractMultiField.h>
#include "WidgetData.h"

#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct AbstractMultiField::AbstractMultiFieldData : public Widget::WidgetData
{
    ~AbstractMultiFieldData() override;

    // All the widgets to change the name
    std::vector<std::shared_ptr<Widget>> m_children;

    // The main layout. All the sub-widgets are children of the main layout.
    std::shared_ptr<Stack> m_mainLayout;
    // All the stacks. We need them to change spacing.
    std::vector<std::shared_ptr<Stack>> m_stacks;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
