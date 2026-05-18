/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#define _USE_MATH_DEFINES
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/OffsetLine.h>

#include "ShapeData.h"

#include <algorithm>
#include <cmath>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Checks the intersection of two lines
 *
 * https://en.wikipedia.org/wiki/Line%E2%80%93line_intersection
 */
static bool _segmentSegmentIntersect(
    float x1, float y1, float x2, float y2, float x3, float y3, float x4, float y4, float* outX, float* outY)
{
    constexpr float exp = 1e-1f;

    // Check if bboxes are intersecting
    float xmin1 = std::min(x1, x2) - exp;
    float xmax1 = std::max(x1, x2) + exp;
    float xmin2 = std::min(x3, x4) - exp;
    float xmax2 = std::max(x3, x4) + exp;
    float ymin1 = std::min(y1, y2) - exp;
    float ymax1 = std::max(y1, y2) + exp;
    float ymin2 = std::min(y3, y4) - exp;
    float ymax2 = std::max(y3, y4) + exp;

    if (!(xmax1 >= xmin2 && xmax2 >= xmin1 && ymax1 >= ymin2 && ymax2 >= ymin1))
    {
        // Bounding boxes don't intersect, thus the segments don't intersect.
        return false;
    }

    // Next is Line-Line intersection https://en.wikipedia.org/wiki/Line%E2%80%93line_intersection

    float x12 = x1 - x2;
    float x34 = x3 - x4;
    float y12 = y1 - y2;
    float y34 = y3 - y4;

    // Determinant
    float det = x12 * y34 - y12 * x34;
    if (fabs(det) < exp)
    {
        // Parallel lines
        return false;
    }

    float detInv = 1.0f / det;

    // s and t should be in [0, 1] for the intersection
    float s = x1 * y2 - y1 * x2;
    float t = x3 * y4 - y3 * x4;
    // TODO: can we find out if the segment intersect from s and t?

    // x and y should be in the bound of the lines for the intersection
    float x = detInv * (s * x34 - t * x12);
    if (x < xmin1 || x > xmax1 || x < xmin2 || x > xmax2)
    {
        return false;
    }

    float y = detInv * (s * y34 - t * y12);
    if (y < ymin1 || y > ymax1 || y < ymin2 || y > ymax2)
    {
        return false;
    }

    *outX = x;
    *outY = y;

    return true;
}

/**
 * @brief Check the intersection of line and rectangle
 */
static bool _lineRectIntersect(
    float x1, float y1, float x2, float y2, float rx1, float ry1, float rx2, float ry2, float* x, float* y)
{
    bool intersected;

    // Check intersection with each line of the rectangle
    // Left
    intersected = _segmentSegmentIntersect(x1, y1, x2, y2, rx1, ry1, rx1, ry2, x, y);
    // Right
    intersected = intersected || _segmentSegmentIntersect(x1, y1, x2, y2, rx2, ry1, rx2, ry2, x, y);
    // Top
    intersected = intersected || _segmentSegmentIntersect(x1, y1, x2, y2, rx1, ry2, rx2, ry2, x, y);
    // Bottom
    intersected = intersected || _segmentSegmentIntersect(x1, y1, x2, y2, rx1, ry1, rx2, ry1, x, y);

    return intersected;
}

OffsetLine::OffsetLine(std::shared_ptr<Widget> start, std::shared_ptr<Widget> end)
    : FreeLine(std::move(start), std::move(end))
{
}

void OffsetLine::_drawContent(float elapsedTime)
{
    auto& data = _getData<FreeShapeData>();
    auto startPointWidget = data.m_startPointWidget.lock();
    auto endPointWidget = data.m_endPointWidget.lock();
    if (!startPointWidget || !endPointWidget)
    {
        return;
    }

    float dpiScale = this->getDpiScale();
    float boundOffset = this->getBoundOffset() * dpiScale;

    // Bounds
    float startBoxXmin = startPointWidget->getScreenPositionX() - boundOffset;
    float startBoxXmax = startBoxXmin + startPointWidget->getComputedWidth() + 2.0f * boundOffset;
    float startBoxYmin = startPointWidget->getScreenPositionY() - boundOffset;
    float startBoxYmax = startBoxYmin + startPointWidget->getComputedHeight() + 2.0f * boundOffset;
    float endBoxXmin = endPointWidget->getScreenPositionX() - boundOffset;
    float endBoxXmax = endBoxXmin + endPointWidget->getComputedWidth() + 2.0f * boundOffset;
    float endBoxYmin = endPointWidget->getScreenPositionY() - boundOffset;
    float endBoxYmax = endBoxYmin + endPointWidget->getComputedHeight() + 2.0f * boundOffset;

    // The middle of the widget.
    float startX = (startBoxXmin + startBoxXmax) * 0.5f;
    float startY = (startBoxYmin + startBoxYmax) * 0.5f;
    float endX = (endBoxXmin + endBoxXmax) * 0.5f;
    float endY = (endBoxYmin + endBoxYmax) * 0.5f;

    float offset = this->getOffset() * dpiScale;
    if (offset != 0.0f)
    {
        // Normal
        float nX = endY - startY;
        float nY = startX - endX;
        // Normalize normal
        float nLength = sqrt(nX * nX + nY * nY);
        nX = offset * nX / nLength;
        nY = offset * nY / nLength;

        // Offset
        startX += nX;
        startY += nY;
        endX += nX;
        endY += nY;
    }

    bool intersected =
        _lineRectIntersect(
            startX, startY, endX, endY, startBoxXmin, startBoxYmin, startBoxXmax, startBoxYmax, &startX, &startY) &&
        _lineRectIntersect(startX, startY, endX, endY, endBoxXmin, endBoxYmin, endBoxXmax, endBoxYmax, &endX, &endY);

    if (this->getAlignment() != Alignment::eUndefined || intersected)
    {
        this->_drawShape(elapsedTime, startX, startY, endX - startX, endY - startY);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
