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

#pragma once

#include "Stack.h"

#include <cstdint>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Grid is a container that arranges its child views in a grid. The grid vertical/horizontal direction is the
 * direction the grid size growing with creating more children.
 */
class OMNIUI_CLASS_API Grid : public Stack
{
    OMNIUI_OBJECT(Grid)

public:
    OMNIUI_API
    ~Grid() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief The width of the column. It's only possible to set it if the grid is vertical. Once it's set, the column
     * count depends on the size of the widget.
     */
    OMNIUI_PROPERTY(float,
                    columnWidth,
                    DEFAULT,
                    0.0f,
                    READ,
                    getColumnWidth,
                    WRITE,
                    setColumnWidth,
                    PROTECTED,
                    NOTIFY,
                    _setColumnWidthChangedFn);

    /**
     * @brief The height of the row. It's only possible to set it if the grid is horizontal. Once it's set, the row
     * count depends on the size of the widget.
     */
    OMNIUI_PROPERTY(
        float, rowHeight, DEFAULT, 0.0f, READ, getRowHeight, WRITE, setRowHeight, PROTECTED, NOTIFY, _setRowHeightChangedFn);

    /**
     * @brief The number of columns. It's only possible to set it if the grid is vertical. Once it's set, the column
     * width depends on the widget size.
     */
    OMNIUI_PROPERTY(uint32_t,
                    columnCount,
                    DEFAULT,
                    1,
                    READ,
                    getColumnCount,
                    WRITE,
                    setColumnCount,
                    PROTECTED,
                    NOTIFY,
                    _setColumnCountChangedFn);

    /**
     * @brief The number of rows. It's only possible to set it if the grid is horizontal. Once it's set, the row height
     * depends on the widget size.
     */
    OMNIUI_PROPERTY(
        uint32_t, rowCount, DEFAULT, 1, READ, getRowCount, WRITE, setRowCount, PROTECTED, NOTIFY, _setRowCountChangedFn);

protected:
    /**
     * @brief Constructor.
     *
     * @param direction Determines the direction the widget grows when adding more children.
     *
     * @see Stack::Direction
     */
    OMNIUI_API
    Grid(Direction direction);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    /**
     * @brief The grid has two modes of working. When the current mode is eSizeFromCount, the grid computes the size of
     * the cell using the number of columns/rows. When eCountFromSize, the size of the cells is always the same, but the
     * number of columns varies depending on the grid's full size.
     */
    enum class CellSizeMode : uint8_t
    {
        eSizeFromCount,
        eCountFromSize
    };

private:
    struct GridData;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
