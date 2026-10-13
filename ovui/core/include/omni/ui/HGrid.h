/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"
#include "Grid.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Shortcut for Grid{eLeftToRight}. The grid grows from left to right with the widgets placed.
 *
 * @see Grid
 */
class OMNIUI_CLASS_API HGrid : public Grid
{
    OMNIUI_OBJECT(HGrid)

public:
    OMNIUI_API
    ~HGrid() override;

protected:
    /**
     * @brief Construct a grid that grow from left to right with the widgets placed.
     */
    OMNIUI_API
    HGrid();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
