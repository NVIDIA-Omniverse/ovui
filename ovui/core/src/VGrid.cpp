/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/VGrid.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

VGrid::VGrid() : Grid(Stack::Direction::eTopToBottom)
{
}

VGrid::~VGrid() = default;

OMNIUI_NAMESPACE_CLOSE_SCOPE
