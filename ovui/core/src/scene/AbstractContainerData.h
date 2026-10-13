/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
