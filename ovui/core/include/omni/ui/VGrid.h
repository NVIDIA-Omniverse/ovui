/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"
#include "Grid.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Shortcut for Grid{eTopToBottom}. The grid grows from top to bottom with the widgets placed.
 *
 * @see Grid
 */
class OMNIUI_CLASS_API VGrid : public Grid
{
    OMNIUI_OBJECT(VGrid)

public:
    OMNIUI_API
    ~VGrid() override;

protected:
    /**
     * @brief Construct a grid that grows from top to bottom with the widgets placed.
     */
    OMNIUI_API
    VGrid();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
