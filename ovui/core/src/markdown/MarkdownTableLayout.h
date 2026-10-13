/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "RenderConfig.h"

#include <omni/ui/Api.h>

#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct MarkdownTableColumnMeasure
{
    float minWidth = 0.0f;
    float preferredWidth = 0.0f;
};

struct MarkdownTableLayoutResult
{
    std::vector<float> columnWidths;
    float tableWidth = 0.0f;
    bool clipped = false;
};

OMNIUI_API MarkdownTableLayoutResult computeMarkdownTableColumnLayout(
    MarkdownTableLayoutPolicy policy,
    const std::vector<MarkdownTableColumnMeasure>& measures,
    float availableWidth,
    float minColumnWidth,
    float maxColumnWidth,
    float fixedColumnWidth);

OMNIUI_NAMESPACE_CLOSE_SCOPE
