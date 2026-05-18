/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/scene/AbstractContainer.h>
#include "AbstractItemData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct AbstractContainer::AbstractContainerData : public AbstractItem::AbstractItemData
{
    virtual ~AbstractContainerData();

    std::vector<std::shared_ptr<AbstractItem>> m_children;

    // Record cache state and allocated DrawBuffer. Scene uses the root buffer index from the draw list. Access via
    // _getDrawBufferIndex()
    DrawBufferIndex m_bufferIndex;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
