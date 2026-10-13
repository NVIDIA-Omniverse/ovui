/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/HStack.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

HStack::HStack() : Stack(Stack::Direction::eLeftToRight)
{
}

HStack::~HStack() = default;

OMNIUI_NAMESPACE_CLOSE_SCOPE
