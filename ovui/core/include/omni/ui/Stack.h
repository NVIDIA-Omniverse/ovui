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

#include "Container.h"

#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The Stack class lines up child widgets horizontally, vertically or sorted in a Z-order.
 */
class OMNIUI_CLASS_API Stack : public Container
{
    OMNIUI_OBJECT(Stack)

public:
    OMNIUI_API
    ~Stack() override;

    OMNIUI_API
    void destroy() override;

    /**
     * @brief This type is used to determine the direction of the layout.
     * If the Stack's orientation is eLeftToRight the widgets are placed in a horizontal row, from left to right.
     * If the Stack's orientation is eRightToLeft the widgets are placed in a horizontal row, from right to left.
     * If the Stack's orientation is eTopToBottom, the widgets are placed in a vertical column, from top to bottom.
     * If the Stack's orientation is eBottomToTop, the widgets are placed in a vertical column, from bottom to top.
     * If the Stack's orientation is eBackToFront, the widgets are placed sorted in a Z-order in top right corner.
     * If the Stack's orientation is eFrontToBack, the widgets are placed sorted in a Z-order in top right corner, the
     * first widget goes to front.
     */
    enum class Direction
    {
        eLeftToRight,
        eRightToLeft,
        eTopToBottom,
        eBottomToTop,
        eBackToFront,
        eFrontToBack
    };

    /**
     * @brief Reimplemented adding a widget to this Stack. The Stack class can contain multiple widgets.
     *
     * @see Container::addChild
     */
    OMNIUI_API
    void addChild(std::shared_ptr<Widget> widget) override;

    /**
     * @brief Reimplemented removing all the child widgets from this Stack.
     *
     * @see Container::clear
     */
    OMNIUI_API
    void clear() override;

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
     * @brief It's called when the style is changed. It should be propagated to children to make the style cached and
     * available to children.
     */
    OMNIUI_API
    void cascadeStyle() override;

    /**
     * @brief Next frame the content will be forced to re-bake.
     */
    OMNIUI_API
    void forceRasterDirty(BakeDirtyReason reason) override;

    /**
     * @brief Change dirty bits when the visibility is changed.
     */
    OMNIUI_API void setVisiblePreviousFrame(bool wasVisible, bool dirtySize = true) override;

    /**
     * @brief Determines if the child widgets should be clipped by the rectangle of this Stack.
     */
    OMNIUI_PROPERTY(bool, contentClipping, DEFAULT, false, READ, isContentClipping, WRITE, setContentClipping);

    /**
     * @brief Sets a non-stretchable space in pixels between child items of this layout.
     */
    OMNIUI_PROPERTY(float, spacing, DEFAULT, 0.0f, READ, getSpacing, WRITE, setSpacing);

    /**
     * @brief Determines the type of the layout. It can be vertical, horizontal or front-to-back.
     */
    OMNIUI_PROPERTY(Direction, direction, DEFAULT, Direction::eLeftToRight, READ, getDirection, WRITE, setDirection);

    /**
     * @brief When children of a Z-based stack overlap mouse events are normally sent to the topmost one. Setting
     * this property true will invert that behavior, sending mouse events to the bottom-most child.
     * 
     * Default is ImGui default
     */
    OMNIUI_PROPERTY(
        bool, sendMouseEventsToBack, READ, isSendMouseEventsToBack, WRITE, setSendMouseEventsToBack, DEFAULT, true);

protected:
    struct StackData;

    /**
     * @brief Constructor.
     *
     * @param direction Determines the orientation of the Stack.
     *
     * @see Stack::Direction
     */
    OMNIUI_API
    Stack(Direction direction, StackData* stackData = nullptr);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

    /**
     * @brief Return the list of children for the Container.
     */
    OMNIUI_API
    std::vector<std::shared_ptr<Widget>> _getChildren() const override;

    OMNIUI_API
    std::vector<std::shared_ptr<Widget>>& _getMutableChildren();

    /**
     * @brief This method fills an unordered set with the visible minimum and
     * maximum values of the Widget and children.
     */
    OMNIUI_API
    void _fillVisibleThreshold(void* thresholds) const override;

private:
    /**
     * @brief Evaluates the layout of one dimension (width or height) of the child widgets considering that in this
     * dimension, the widgets will be placed in a row one after each other.
     *
     * It's called for the width if the direction eLeftToRight, and for the height, if the direction is eTopToBottom.
     *
     * @return Returns the total length/width of the evaluated widgets.
     */
    float _evaluateConsecutiveLayout(float length, bool isWidthEvaluation);

    /**
     * @brief Evaluates the layout of one dimension (width or height) of the child widgets considering that in this
     * dimension, the widgets will be placed at the same point at the start of the dimension.
     *
     * It's called for the height if the direction eLeftToRight, and for the width, if the direction is eTopToBottom.
     * Also, it's called for both width and height if the direction is eBackToFront.
     *
     * @return Returns the total length/width of the evaluated widgets.
     */
    float _evaluateSimultaneousLayout(float length, bool isWidthEvaluation);

    void _forceChildDirty(std::shared_ptr<Widget>& child, bool width) const;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
