/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/ZStack.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

ZStack::ZStack() : Stack(Stack::Direction::eBackToFront)
{
}

ZStack::~ZStack() = default;

OMNIUI_NAMESPACE_CLOSE_SCOPE
