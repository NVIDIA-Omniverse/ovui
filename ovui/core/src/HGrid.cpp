/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/HGrid.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

HGrid::HGrid() : Grid(Stack::Direction::eLeftToRight)
{
}

HGrid::~HGrid() = default;

OMNIUI_NAMESPACE_CLOSE_SCOPE
