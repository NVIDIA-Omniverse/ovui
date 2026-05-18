/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
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
