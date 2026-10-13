/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/VStack.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

VStack::VStack() : Stack(Stack::Direction::eTopToBottom)
{
}

VStack::~VStack() = default;

OMNIUI_NAMESPACE_CLOSE_SCOPE
