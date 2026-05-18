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

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Grid.h>
#include <omni/ui/Profile.h>

#include "StackData.h"

#include <algorithm>
#include <numeric>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct Grid::GridData : public Stack::StackData
{
    ~GridData() override = default;

    CellSizeMode m_cellSizeMode = CellSizeMode::eSizeFromCount;
    // Flag to determine if the property set by user or by this class.
    bool m_internalPropertyChange = false;

    // True to determine that height (for V) or width (for H) was set explicitly.
    bool m_isLineSizeSet = false;

    // List of line offsets. It's empty if height (for V) or width (for H) was set explicitly.
    std::vector<float> m_lineOffset;

    // Currently visible lines.
    size_t m_lineLower = 0;
    // Max for the first frame and then it will be corrected.
    size_t m_lineUpper = SIZE_MAX;

    size_t m_prevColumnCount = 0;
    size_t m_prevRowCount = 0;
};


// TODO: Reuse it from Stack.cpp
static inline bool isHorizontal(Stack::Direction direction)
{
    return direction == Stack::Direction::eLeftToRight || direction == Stack::Direction::eRightToLeft;
}

// TODO: Reuse it from Stack.cpp
static inline bool isVertical(Stack::Direction direction)
{
    return direction == Stack::Direction::eTopToBottom || direction == Stack::Direction::eBottomToTop;
}

// TODO: Reuse it from Stack.cpp
static inline bool isReversed(Stack::Direction direction)
{
    return direction == Stack::Direction::eRightToLeft || direction == Stack::Direction::eBottomToTop ||
           direction == Stack::Direction::eFrontToBack;
}

/**
 * @brief Set width/height of child widgets
 *
 * @param children The child widgets.
 * @param isWidth True when the growing direction is vertical.
 * @param lineLower The first visible line.
 * @param lineUpper The last visible line.
 * @param itemsInLine The number of items in the line.
 * @param size The size to set.
 */
static void setSizeOfGridItems(const std::vector<std::shared_ptr<Widget>>& children,
                               bool isWidth,
                               size_t lineLower,
                               size_t lineUpper,
                               size_t itemsInLine,
                               float size)
{
    auto it = children.begin();
    auto end = children.end();
    // OMPE-40877: must force dirty for all children,
    // otherwise the child size may be wrong if it becomes visible after scrolling.
    while (it < end)
    {
        const auto& child = *(it++);
        if (isWidth)
        {
            child->forceWidthDirty(Widget::SizeDirtyReason::eParentDirty);
            child->setComputedWidth(size);
        }
        else
        {
            child->forceHeightDirty(Widget::SizeDirtyReason::eParentDirty);
            child->setComputedHeight(size);
        }
    }
}

/**
 * @brief The main logic that creates the grid layout. It iterates visible children widgets and computes the position
 * offsets from the begin of the table.
 *
 * @param children The child widgets.
 * @param isWidth True when the growing direction is vertical.
 * @param lineSize The size of one line. When width is true, it's the default column width.
 * @param lineLower The first visible line.
 * @param lineUpper The last visible line.
 * @param itemsInLine The number of items in the line.
 * @param offsets Output array that contains offsets of each line.
 */
static void computeGridContentSizeInGrowingDirection(const std::vector<std::shared_ptr<Widget>>& children,
                                                     bool isWidth,
                                                     float availableSize,
                                                     float dpiScale,
                                                     size_t lineLower,
                                                     size_t lineUpper,
                                                     size_t itemsInLine,
                                                     std::vector<float>& offsets)
{
    OMNIUI_PROFILE_VERBOSE_ZONE("[Grid] computeGridContentSizeInGrowingDirection");

    // Skip invisible children.
    size_t visibleChildrenNumber =
        std::count_if(children.begin(), children.end(), [](const std::shared_ptr<Widget>& w) { return w->isVisible(); });

    // Initialzie offsets. By default this array has offets as all the line have size lineSize.
    size_t lineCount =
        static_cast<uint32_t>(visibleChildrenNumber / itemsInLine + ((visibleChildrenNumber % itemsInLine) ? 1 : 0));
    if (lineCount != offsets.size())
    {
        size_t previousOffsetSize = offsets.size();
        offsets.resize(lineCount);
        // Reset the offsets
        lineLower = 0;
        lineUpper = lineCount;
        offsets[0] = 0.0f;
    }

    if (lineLower >= lineCount)
    {
        // All the items are invisible.
        return;
    }

    float firstOffset = offsets[lineLower];
    std::fill(offsets.begin() + lineLower, offsets.begin() + std::min(lineUpper, offsets.size()), 0.0f);
    // Check size of each visible child.
    size_t firstChildId = itemsInLine * lineLower;
    size_t lastChildId = std::min(itemsInLine * lineUpper, visibleChildrenNumber);

    // Two passes. First pass to get max, second pass to set it.
    auto it = children.begin();
    auto end = children.end();
    size_t skipVisibleNumber = 0;
    size_t counter = firstChildId;
    while (it < end && counter < lastChildId)
    {
        const auto& child = *(it++);
        if (!child->isVisible())
        {
            // Skip invisible children.
            continue;
        }
        skipVisibleNumber++;
        if (skipVisibleNumber <= firstChildId)
        {
            // Skip first visible children
            continue;
        }

        float childSize;

        float computedLength;
        const auto& currentLength = isWidth ? child->getWidth() : child->getHeight();
        if (currentLength.unit == UnitType::ePixel)
        {
            computedLength = currentLength.value * dpiScale;
        }
        else if (currentLength.unit == UnitType::ePercent)
        {
            computedLength = currentLength.value * 1e-2f * availableSize;
        }
        else // if (currentLength.unit == UnitType::eFraction)
        {
            // The behaviour is undefined.
            computedLength = 0.0f;
        }

        if (isWidth)
        {
            child->setComputedWidth(computedLength);
            childSize = child->getComputedWidth();
        }
        else
        {
            child->setComputedHeight(computedLength);
            childSize = child->getComputedHeight();
        }

        size_t lineId = counter / itemsInLine;
        offsets[lineId] = std::max(offsets[lineId], childSize);
        counter++;
    }

    it = children.begin();
    skipVisibleNumber = 0;
    counter = firstChildId;
    while (it < end && counter < lastChildId)
    {
        const auto& child = *(it++);
        if (!child->isVisible())
        {
            // Skip invisible children.
            continue;
        }
        skipVisibleNumber++;
        if (skipVisibleNumber <= firstChildId)
        {
            // Skip first visible children
            continue;
        }

        size_t lineId = counter / itemsInLine;
        if (isWidth)
        {
            child->setComputedWidth(offsets[lineId]);
        }
        else
        {
            child->setComputedHeight(offsets[lineId]);
        }
        counter++;
    }

    // Regenerate the offsets of visible items.
    for (size_t i = lineLower; i < std::min(lineUpper, offsets.size()); ++i)
    {
        float currentLineSize = offsets[i];
        offsets[i] = firstOffset;
        firstOffset += currentLineSize;
    }

    if (lineUpper == offsets.size())
    {
        return;
    }

    if (firstOffset == offsets[lineUpper])
    {
        return;
    }

    // We are here because the size of visible items is changed and we need to move the rest of offsets accordingly.
    float difference = firstOffset - offsets[lineUpper];
    for (size_t i = lineUpper, n = offsets.size(); i < n; ++i)
    {
        offsets[i] += difference;
    }
}

Grid::Grid(Direction direction)
    : Stack(direction, new GridData)
{
    // The grid has two modes of working. When the user sets column_count property, the grid uses this property as a
    // number of columns. When the user sets column_width, the grid layout computes the number of columns using
    // available sizes.
    this->_setColumnWidthChangedFn([this](const auto& width) {
        auto& data = _getData<GridData>();
        if (data.m_internalPropertyChange)
        {
            return;
        }

        if (isVertical(this->getDirection()))
        {
            data.m_cellSizeMode = CellSizeMode::eCountFromSize;
        }
        else
        {
            // We are here because it's horizontal grid and the user set width. It means we shouldn't compute the widths
            // of items and use the provided width.
            data.m_isLineSizeSet = true;
        }
        // Force to update child width
        this->forceWidthDirty(SizeDirtyReason::eChildDirty);
    });

    this->_setRowHeightChangedFn([this](const auto& height) {
        auto& data = _getData<GridData>();
        if (data.m_internalPropertyChange)
        {
            return;
        }

        if (isHorizontal(this->getDirection()))
        {
            data.m_cellSizeMode = CellSizeMode::eCountFromSize;
        }
        else
        {
            // We are here because it's a vertical grid and the user set height. It means we shouldn't compute the
            // heights of items and use the provided height.
            data.m_isLineSizeSet = true;
        }
        // Force to update child height
        this->forceHeightDirty(SizeDirtyReason::eChildDirty);
    });

    this->_setColumnCountChangedFn([this](const auto& count) {
        auto& data = _getData<GridData>();
        if (data.m_internalPropertyChange)
        {
            return;
        }

        if (isVertical(this->getDirection()))
        {
            data.m_cellSizeMode = CellSizeMode::eSizeFromCount;
        }
    });

    this->_setRowCountChangedFn([this](const auto& count) {
        auto& data = _getData<GridData>();
        if (data.m_internalPropertyChange)
        {
            return;
        }

        if (isHorizontal(this->getDirection()))
        {
            data.m_cellSizeMode = CellSizeMode::eSizeFromCount;
        }
    });
}

Grid::~Grid() = default;

void Grid::setComputedContentWidth(float width)
{
    // Skip invisible children.
    const auto& children = _getChildren();
    size_t visibleChildrenNumber = std::count_if(
        children.begin(), children.end(), [](const std::shared_ptr<Widget>& w) { return w->isVisible(); });

    bool isVerticalDirection = isVertical(this->getDirection());
    // TODO: Reversed

    float dpiScale = this->getDpiScale();
    float evaluatedWidth = 0.0f;

    if (isVerticalDirection)
    {
        float scaledColumnWidth;
        uint32_t columnCount;

        auto& data = _getData<GridData>();
        if (data.m_cellSizeMode == CellSizeMode::eSizeFromCount)
        {
            columnCount = this->getColumnCount();
            scaledColumnWidth = width / columnCount;

            data.m_internalPropertyChange = true;
            this->setColumnWidth(scaledColumnWidth / dpiScale);
            data.m_internalPropertyChange = false;
        }
        else // eCountFromSize
        {
            scaledColumnWidth = this->getColumnWidth() * dpiScale;
            columnCount = static_cast<uint32_t>(width / scaledColumnWidth);

            data.m_internalPropertyChange = true;
            this->setColumnCount(std::max(columnCount, 1u));
            data.m_internalPropertyChange = false;
        }

        setSizeOfGridItems(children, true, data.m_lineLower, data.m_lineUpper, columnCount, scaledColumnWidth);
        evaluatedWidth = scaledColumnWidth * columnCount;
    }
    else
    {
        auto& data = _getData<GridData>();
        if (data.m_isLineSizeSet)
        {
            // The user set width. We don't compute widths. It's the fastest path.

            size_t rowCount = this->getRowCount();
            float scaledColumnWidth = this->getColumnWidth() * dpiScale;
            setSizeOfGridItems(children, true, data.m_lineLower, data.m_lineUpper, rowCount, scaledColumnWidth);

            uint32_t columnCount =
                static_cast<uint32_t>(visibleChildrenNumber / rowCount + ((visibleChildrenNumber % rowCount) ? 1 : 0));

            data.m_internalPropertyChange = true;
            this->setColumnCount(std::max(columnCount, 1u));
            data.m_internalPropertyChange = false;

            evaluatedWidth = scaledColumnWidth * columnCount;
        }
        else
        {
            // The user didn't set width. We have to compute it. It's the slow path, but every line can have different
            // width.

            size_t rowCount = this->getRowCount();
            computeGridContentSizeInGrowingDirection(
                children, true, width, dpiScale, data.m_lineLower, data.m_lineUpper, rowCount, data.m_lineOffset);

            data.m_internalPropertyChange = true;
            this->setColumnCount(std::max(static_cast<uint32_t>(data.m_lineOffset.size()), 1u));
            data.m_internalPropertyChange = false;

            evaluatedWidth = !data.m_lineOffset.empty() ? data.m_lineOffset.back() : 0.0f;
        }
    }

    Widget::setComputedContentWidth(std::max(evaluatedWidth, width));
}

void Grid::setComputedContentHeight(float height)
{
    bool isHorizontalDirection = isHorizontal(this->getDirection());
    // TODO: Reversed

    float dpiScale = this->getDpiScale();
    float evaluatedHeight = 0.0f;
    const auto& children = _getChildren();

    if (isHorizontalDirection)
    {
        float scaledRowHeight;
        uint32_t rowCount;

        auto& data = _getData<GridData>();
        if (data.m_cellSizeMode == CellSizeMode::eSizeFromCount)
        {
            rowCount = this->getRowCount();
            scaledRowHeight = height / rowCount;

            data.m_internalPropertyChange = true;
            this->setRowHeight(scaledRowHeight / dpiScale);
            data.m_internalPropertyChange = false;
        }
        else // eCountFromSize
        {
            scaledRowHeight = this->getRowHeight() * dpiScale;
            rowCount = static_cast<uint32_t>(height / scaledRowHeight);

            data.m_internalPropertyChange = true;
            this->setRowCount(std::max(rowCount, 1u));
            data.m_internalPropertyChange = false;
        }

        setSizeOfGridItems(children, false, data.m_lineLower, data.m_lineUpper, rowCount, scaledRowHeight);
        evaluatedHeight = scaledRowHeight * rowCount;
    }
    else
    {
        auto& data = _getData<GridData>();
        if (data.m_isLineSizeSet)
        {
            // The user set height. We don't compute it. It's the fastest path.

            size_t columnCount = this->getColumnCount();
            float scaledRowHeight = this->getRowHeight() * dpiScale;
            setSizeOfGridItems(children, false, data.m_lineLower, data.m_lineUpper, columnCount, scaledRowHeight);

            // Skip invisible children.
            size_t visibleChildrenNumber = std::count_if(
                children.begin(), children.end(), [](const std::shared_ptr<Widget>& w) { return w->isVisible(); });

            uint32_t rowCount = static_cast<uint32_t>(visibleChildrenNumber / columnCount +
                                                      ((visibleChildrenNumber % columnCount) ? 1 : 0));

            data.m_internalPropertyChange = true;
            this->setRowCount(std::max(rowCount, 1u));
            data.m_internalPropertyChange = false;

            evaluatedHeight = scaledRowHeight * rowCount;
        }
        else
        {
            // The user didn't set height. We have to compute it. It's the slow path, but every line can have different
            // height.

            size_t columnCount = this->getColumnCount();
            computeGridContentSizeInGrowingDirection(
                children, false, height, dpiScale, data.m_lineLower, data.m_lineUpper, columnCount, data.m_lineOffset);

            data.m_internalPropertyChange = true;
            this->setRowCount(std::max(static_cast<uint32_t>(data.m_lineOffset.size()), 1u));
            data.m_internalPropertyChange = false;

            evaluatedHeight = !data.m_lineOffset.empty() ? data.m_lineOffset.back() : 0.0f;
        }
    }

    Widget::setComputedContentHeight(std::max(evaluatedHeight, height));
}

void Grid::_drawContent(float elapsedTime)
{
    auto* ctx = ImGui::GetCurrentContext();
    ImGuiWindow* window = ctx->CurrentWindow;
    ImRect clipRect = window->ClipRect;

    float dpiScale = this->getDpiScale();

    bool isVerticalDirection = isVertical(this->getDirection());
    bool isReversedOrder = isReversed(this->getDirection());

    uint32_t columnCount = this->getColumnCount();
    uint32_t rowCount = this->getRowCount();
    auto& data = _getData<GridData>();

    // If column count is changed, there is a big probability that the height is
    // also changed.
    // We can't flag it in _setColumnCountChangedFn because it's called from
    // setContentWidth and thus the durty flag is erased in draw. So we need to
    // check it from draw to make sure it's not erased.
    if (data.m_prevColumnCount != columnCount || data.m_prevRowCount != rowCount)
    {
        data.m_prevColumnCount = columnCount;
        data.m_prevRowCount = rowCount;
        this->forceWidthDirty(SizeDirtyReason::eChildDirty);
        this->forceHeightDirty(SizeDirtyReason::eChildDirty);
    }

    auto cursorAtStart = ImGui::GetCursorScreenPos();
    const auto& children = _getChildren();

    // Skip invisible children.
    size_t visibleChildrenNumber = std::count_if(
        children.begin(), children.end(), [](const std::shared_ptr<Widget>& w) { return w->isVisible(); });

    // It's the first and the last child to draw depending on the visibility. We don't draw invisible children.
    size_t firstChild;
    size_t lastChild;

    // The way to compute the first and the last one is different depending on the direction and on the properties the
    // user set.
    // TODO: It's very similar code. Make a function.
    if (isVerticalDirection)
    {
        // Find out the first and the last child to draw.
        float relativeRectMin = clipRect.Min.y - cursorAtStart.y;
        float relativeRectMax = clipRect.Max.y - cursorAtStart.y;

        if (data.m_isLineSizeSet)
        {
            float scaledRowHeight = this->getRowHeight() * dpiScale;
            data.m_lineLower = static_cast<size_t>(std::max(0.0f, floorf(relativeRectMin / scaledRowHeight)));
            data.m_lineUpper = static_cast<size_t>(std::max(0.0f, ceilf(relativeRectMax / scaledRowHeight)));

            if (data.m_lineLower > rowCount)
            {
                data.m_lineLower = rowCount;
            }
            if (data.m_lineUpper > rowCount)
            {
                data.m_lineUpper = rowCount;
            }
        }
        else
        {
            // TODO: Use binary search here
            auto low = std::find_if(
                data.m_lineOffset.begin(), data.m_lineOffset.end(), [relativeRectMin](float i) { return i >= relativeRectMin; });
            auto up = std::upper_bound(data.m_lineOffset.begin(), data.m_lineOffset.end(), relativeRectMax);

            data.m_lineLower = std::distance(data.m_lineOffset.begin(), low);
            data.m_lineUpper = std::distance(data.m_lineOffset.begin(), up);
            if (data.m_lineLower > 0)
            {
                data.m_lineLower--;
            }
        }

        firstChild = std::min(data.m_lineLower * columnCount, visibleChildrenNumber);
        lastChild = std::min(data.m_lineUpper * columnCount, visibleChildrenNumber);
    }
    else // isHorizontalDirection
    {
        // Find out the first and the last child to draw.
        float relativeRectMin = clipRect.Min.x - cursorAtStart.x;
        float relativeRectMax = clipRect.Max.x - cursorAtStart.x;

        if (data.m_isLineSizeSet)
        {
            float scaledColumnWidth = this->getColumnWidth() * dpiScale;
            data.m_lineLower = static_cast<size_t>(std::max(0.0f, floorf(relativeRectMin / scaledColumnWidth)));
            data.m_lineUpper = static_cast<size_t>(std::max(0.0f, ceilf(relativeRectMax / scaledColumnWidth)));

            if (data.m_lineLower > columnCount)
            {
                data.m_lineLower = columnCount;
            }
            if (data.m_lineUpper > columnCount)
            {
                data.m_lineUpper = columnCount;
            }
        }
        else
        {
            // TODO: Use binary search here
            auto low = std::find_if(
                data.m_lineOffset.begin(), data.m_lineOffset.end(), [relativeRectMin](float i) { return i >= relativeRectMin; });
            auto up = std::upper_bound(data.m_lineOffset.begin(), data.m_lineOffset.end(), relativeRectMax);

            data.m_lineLower = std::distance(data.m_lineOffset.begin(), low);
            data.m_lineUpper = std::distance(data.m_lineOffset.begin(), up);
            if (data.m_lineLower > 0)
            {
                data.m_lineLower--;
            }
        }

        firstChild = std::min(data.m_lineLower * rowCount, visibleChildrenNumber);
        lastChild = std::min(data.m_lineUpper * rowCount, visibleChildrenNumber);
    }

    // TODO: it's possible to get rid of counter
    size_t counter = firstChild;

    // The loop that can be forward of backward depending on the flag.
    // TODO: add reversed to setComputedContentWidth/setComputedContentHeight
    auto it = children.begin();
    auto rit = children.rbegin();
    auto end = children.end();
    auto rend = children.rend();
    size_t skipVisibleNumber = 0;
    while (it < end && rit < rend && counter < columnCount * rowCount && counter < lastChild)
    {
        const auto& child = isReversedOrder ? *(rit++) : *(it++);
        if (!child || !child->isVisible())
        {
            // Skip invisible children.
            continue;
        }
        skipVisibleNumber++;
        if (skipVisibleNumber <= firstChild)
        {
            continue;
        }

        // Find out column and row number
        size_t columnId;
        size_t rowId;
        if (isVerticalDirection)
        {
            columnId = counter % columnCount;
            rowId = counter / columnCount;
        }
        else // isHorizontalDirection
        {
            rowId = counter % rowCount;
            columnId = counter / rowCount;
        }

        float offsetX;
        float offsetY;
        if (isVerticalDirection)
        {
            offsetX = columnId * this->getColumnWidth() * dpiScale;
            if (data.m_isLineSizeSet)
            {
                offsetY = rowId * this->getRowHeight() * dpiScale;
            }
            else
            {
                offsetY = data.m_lineOffset[rowId];
            }
        }
        else // isHorizontalDirection
        {
            if (data.m_isLineSizeSet)
            {
                offsetX = columnId * this->getColumnWidth() * dpiScale;
            }
            else
            {
                offsetX = data.m_lineOffset[columnId];
            }
            offsetY = rowId * this->getRowHeight() * dpiScale;
        }

        ImVec2 currentCursor{ cursorAtStart.x + offsetX, cursorAtStart.y + offsetY };

        // Draw it
        ImGui::SetCursorScreenPos(currentCursor);
        child->draw(elapsedTime);

        counter++;
    }

    // Make scrollbar the correct size.
    ImGui::SetCursorScreenPos(
        ImVec2{ cursorAtStart.x + this->getComputedContentWidth(), cursorAtStart.y + this->getComputedHeight() });
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
