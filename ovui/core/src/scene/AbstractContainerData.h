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

    // snapshot of m_children captured once at the start of the draw
    // cycle (AbstractContainer::_preDrawContent) and reused by _drawChildren and
    // _postDrawContent, so all three draw phases iterate the SAME set of children
    // even if a child callback (gesture, model update, manipulator on_build)
    // mutates m_children mid-draw. Holding shared_ptrs keeps each child alive for
    // the whole cycle; _postDrawContent clears it at the end. Deliberately NOT
    // touched by destroy() - a container can be destroyed mid-iteration and this
    // snapshot is what keeps its children alive while the loop is still running.
    std::vector<std::shared_ptr<AbstractItem>> m_drawSnapshot;

    // Record cache state and allocated DrawBuffer. Scene uses the root buffer index from the draw list. Access via
    // _getDrawBufferIndex()
    DrawBufferIndex m_bufferIndex;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
