/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Stack.h>
#include "ContainerData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Stack::StackData : public Container::ContainerData
{
    ~StackData() override;

    std::vector<std::shared_ptr<Widget>> m_children;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
