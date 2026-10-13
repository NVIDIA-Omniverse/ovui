/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"
#include "Stack.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Shortcut for Stack{eTopToBottom}. The widgets are placed in a column, with suitable sizes.
 *
 * @see Stack
 */
class OMNIUI_CLASS_API VStack : public Stack
{
    OMNIUI_OBJECT(VStack)

public:
    OMNIUI_API
    ~VStack() override;

protected:
    /**
     * @brief Construct a stack with the widgets placed in a column from top to bottom.
     */
    OMNIUI_API
    VStack();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
