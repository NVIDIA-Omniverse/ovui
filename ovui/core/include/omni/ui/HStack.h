/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Stack.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Shortcut for Stack{eLeftToRight}. The widgets are placed in a row, with suitable sizes.
 *
 * @see Stack
 */
class OMNIUI_CLASS_API HStack : public Stack
{
    OMNIUI_OBJECT(HStack)

public:
    OMNIUI_API
    ~HStack() override;

protected:
    /**
     * @brief Construct a stack with the widgets placed in a row from left to right.
     */
    OMNIUI_API
    HStack();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
