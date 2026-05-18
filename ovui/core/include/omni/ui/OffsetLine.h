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

#include "FreeShape.h"

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The free widget is the widget that is independent of the layout. It
 * draws the line stuck to the bounds of other widgets.
 */
class OMNIUI_CLASS_API OffsetLine : public FreeLine
{
    OMNIUI_OBJECT(OffsetLine)
public:

    /**
     * @brief The offset to the direction of the line normal.
     * 
     */
    OMNIUI_PROPERTY(float, offset, DEFAULT, 0.0f, READ, getOffset, WRITE, setOffset);

    /**
     * @brief The offset from the bounds of the widgets this line is stuck to.
     * 
     */
    OMNIUI_PROPERTY(float, boundOffset, DEFAULT, 0.0f, READ, getBoundOffset, WRITE, setBoundOffset);

protected:
    /**
     * @brief Initialize the the shape with bounds limited to the positions of the given widgets.
     *
     * @param start The bound corder is in the border of this given widget.
     * @param end The bound corder is in the border of this given widget.
     */
    OMNIUI_API
    OffsetLine(std::shared_ptr<Widget> start, std::shared_ptr<Widget> end);

    /**
     * @brief Reimplemented the rendering code of the shape.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
