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
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
