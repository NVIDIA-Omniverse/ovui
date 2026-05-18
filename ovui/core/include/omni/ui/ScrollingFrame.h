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

#include "Frame.h"
#include "ScrollBarPolicy.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The ScrollingFrame class provides the ability to scroll onto another widget.
 *
 * ScrollingFrame is used to display the contents of a child widget within a frame. If the widget exceeds the size of
 * the frame, the frame can provide scroll bars so that the entire area of the child widget can be viewed. The child
 * widget must be specified with addChild().
 */
class OMNIUI_CLASS_API ScrollingFrame : public Frame
{
    OMNIUI_OBJECT(ScrollingFrame)

public:
    OMNIUI_API
    ~ScrollingFrame() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the minimal size of the child widgets.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the minimal size of the child widgets.
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief The horizontal position of the scroll bar. When it's changed, the contents will be scrolled accordingly.
     */
    OMNIUI_PROPERTY(float, scrollX, DEFAULT, 0.0f, READ, getScrollX, WRITE, setScrollX, NOTIFY, setScrollXChangedFn);

    /**
     * @brief The vertical position of the scroll bar. When it's changed, the contents will be scrolled accordingly.
     */
    OMNIUI_PROPERTY(float, scrollY, DEFAULT, 0.0f, READ, getScrollY, WRITE, setScrollY, NOTIFY, setScrollYChangedFn);

    /**
     * @brief The max position of the horizontal scroll bar.
     */
    OMNIUI_PROPERTY(float, scrollXMax, DEFAULT, 0.0f, READ, getScrollXMax, PROTECTED, WRITE, setScrollXMax);

    /**
     * @brief The max position of the vertical scroll bar.
     */
    OMNIUI_PROPERTY(float, scrollYMax, DEFAULT, 0.0f, READ, getScrollYMax, PROTECTED, WRITE, setScrollYMax);

    /**
     * @brief This property holds the policy for the horizontal scroll bar.
     */
    OMNIUI_PROPERTY(ScrollBarPolicy,
                    horizontalScrollBarPolicy,
                    DEFAULT,
                    ScrollBarPolicy::eScrollBarAsNeeded,
                    READ,
                    getHorizontalScrollBarPolicy,
                    WRITE,
                    setHorizontalScrollBarPolicy);

    /**
     * @brief This property holds the policy for the vertical scroll bar.
     */
    OMNIUI_PROPERTY(ScrollBarPolicy,
                    verticalScrollBarPolicy,
                    DEFAULT,
                    ScrollBarPolicy::eScrollBarAsNeeded,
                    READ,
                    getVerticalScrollBarPolicy,
                    WRITE,
                    setVerticalScrollBarPolicy);

protected:
    /**
     * @brief Construct ScrollingFrame
     */
    OMNIUI_API
    ScrollingFrame();

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * Draw the content in the scrolling frame.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct ScrollingFrameData;

    void _scrollXExplicitlyChanged();
    void _scrollYExplicitlyChanged();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
