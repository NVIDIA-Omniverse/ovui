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

#include "Shape.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

#include <cstdint>

/**
 * @brief The ArrowHelper widget provides a colored rectangle to display.
 */
class OMNIUI_CLASS_API ArrowHelper
{
public:
    enum class ArrowType : uint8_t
    {
        eNone = 0,
        eArrow
    };

    OMNIUI_API
    virtual ~ArrowHelper();

    /**
     * @brief This property holds the width of the begin arrow
     */
    OMNIUI_PROPERTY(float, beginArrowWidth, DEFAULT, 8.0f, READ, getBeginArrowWidth, WRITE, setBeginArrowWidth);

    /**
     * @brief This property holds the height of the begin arrow
     */
    OMNIUI_PROPERTY(float, beginArrowHeight, DEFAULT, 8.0f, READ, getBeginArrowHeight, WRITE, setBeginArrowHeight);

    /**
     * @brief This property holds the type of the begin arrow can only be eNone or eRrrow.
     * By default, the arrow type is eNone.
     */
    OMNIUI_PROPERTY(ArrowType, beginArrowType, DEFAULT, ArrowType::eNone, READ, getBeginArrowType, WRITE, setBeginArrowType);

    /**
     * @brief This property holds the width of the end arrow
     */
    OMNIUI_PROPERTY(float, endArrowWidth, DEFAULT, 8.0f, READ, getEndArrowWidth, WRITE, setEndArrowWidth);

    /**
     * @brief This property holds the height of the end arrow
     */
    OMNIUI_PROPERTY(float, endArrowHeight, DEFAULT, 8.0f, READ, getEndArrowHeight, WRITE, setEndArrowHeight);

    /**
     * @brief This property holds the type of the end arrow can only be eNone or eRrrow.
     * By default, the arrow type is eNone.
     */
    OMNIUI_PROPERTY(ArrowType, endArrowType, DEFAULT, ArrowType::eNone, READ, getEndArrowType, WRITE, setEndArrowType);

protected:
    /**
     * @brief Constructs ArrowHelper
     */
    OMNIUI_API
    ArrowHelper();

    /**
     * @brief draw a arrow.
     *
     */
    OMNIUI_API
    void drawArrow(float x,
                   float y,
                   float width,
                   float height,
                   float dpi,
                   float lineWidth,
                   float arrowWidth,
                   float arrowHeight,
                   uint32_t color);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
