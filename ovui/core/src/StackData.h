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

#include <omni/ui/Stack.h>
#include "ContainerData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Stack::StackData : public Container::ContainerData
{
    ~StackData() override;

    std::vector<std::shared_ptr<Widget>> m_children;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
