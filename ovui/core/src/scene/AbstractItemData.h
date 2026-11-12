/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/scene/AbstractItem.h>


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct AbstractItem::AbstractItemData
{
    virtual ~AbstractItemData();

    bool m_skipPreDraw = false;

    // The value of the process-wide write counter at the last write to this item, see AbstractItem::getWriteStamp.
    uint64_t m_writeStamp = 0;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
