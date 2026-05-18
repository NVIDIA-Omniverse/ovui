/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
