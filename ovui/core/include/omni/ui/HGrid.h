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
