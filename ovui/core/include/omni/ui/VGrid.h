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
