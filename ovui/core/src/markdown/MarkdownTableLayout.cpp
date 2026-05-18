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

#include "MarkdownTableLayout.h"

#include <algorithm>
#include <numeric>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

float _safeWidth(float value, float fallback)
{
    return value > 0.0f ? value : fallback;
}

float _sum(const std::vector<float>& values)
{
    return std::accumulate(values.begin(), values.end(), 0.0f);
}

void _distributeEvenly(std::vector<float>& widths, float extra)
{
    if (widths.empty() || extra <= 0.0f)
        return;
    float each = extra / static_cast<float>(widths.size());
    for (float& width : widths)
        width += each;
}

} // namespace

MarkdownTableLayoutResult computeMarkdownTableColumnLayout(
    MarkdownTableLayoutPolicy policy,
    const std::vector<MarkdownTableColumnMeasure>& measures,
    float availableWidth,
    float minColumnWidth,
    float maxColumnWidth,
    float fixedColumnWidth)
{
    MarkdownTableLayoutResult result;
    const size_t cols = measures.size();
    if (cols == 0)
        return result;

    float available = std::max(1.0f, availableWidth);
    float minW = std::max(1.0f, minColumnWidth);
    float maxW = std::max(minW, maxColumnWidth);
    float fixedW = std::max(1.0f, fixedColumnWidth);

    result.columnWidths.assign(cols, 0.0f);

    if (policy == MarkdownTableLayoutPolicy::Equal)
    {
        float width = available / static_cast<float>(cols);
        std::fill(result.columnWidths.begin(), result.columnWidths.end(), width);
        result.tableWidth = available;
        return result;
    }

    if (policy == MarkdownTableLayoutPolicy::Fixed)
    {
        std::fill(result.columnWidths.begin(), result.columnWidths.end(), fixedW);
        result.tableWidth = fixedW * static_cast<float>(cols);
        result.clipped = result.tableWidth > available + 0.5f;
        return result;
    }

    std::vector<float> mins(cols, minW);
    std::vector<float> preferred(cols, minW);
    for (size_t i = 0; i < cols; ++i)
    {
        float measuredMin = _safeWidth(measures[i].minWidth, minW);
        float measuredPreferred = _safeWidth(measures[i].preferredWidth, measuredMin);
        mins[i] = std::clamp(measuredMin, minW, maxW);
        preferred[i] = std::clamp(std::max(measuredPreferred, mins[i]), mins[i], maxW);
    }

    if (policy == MarkdownTableLayoutPolicy::Clipped)
    {
        result.columnWidths = preferred;
        result.tableWidth = _sum(result.columnWidths);
        if (result.tableWidth < available)
        {
            _distributeEvenly(result.columnWidths, available - result.tableWidth);
            result.tableWidth = available;
        }
        result.clipped = result.tableWidth > available + 0.5f;
        return result;
    }

    result.columnWidths = mins;
    float minSum = _sum(mins);
    float preferredSum = _sum(preferred);

    if (preferredSum <= available)
    {
        result.columnWidths = preferred;
        _distributeEvenly(result.columnWidths, available - preferredSum);
        result.tableWidth = available;
        return result;
    }

    if (minSum <= available)
    {
        float remaining = available - minSum;
        float growable = 0.0f;
        for (size_t i = 0; i < cols; ++i)
            growable += preferred[i] - mins[i];

        if (growable <= 0.0f)
        {
            _distributeEvenly(result.columnWidths, remaining);
        }
        else
        {
            for (size_t i = 0; i < cols; ++i)
                result.columnWidths[i] += remaining * ((preferred[i] - mins[i]) / growable);
        }
        result.tableWidth = available;
        return result;
    }

    float scale = available / minSum;
    for (float& width : result.columnWidths)
        width = std::max(1.0f, width * scale);
    result.tableWidth = _sum(result.columnWidths);
    return result;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
