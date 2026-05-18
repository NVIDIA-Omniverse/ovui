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

#include "Axis.h"
#include "Container.h"
#include "RasterHelper.h"

#include <cstdint>
#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The Placer class place a single widget to a particular position based on the offet
 */
class OMNIUI_CLASS_API Placer : public Container, public RasterHelper
{
    OMNIUI_OBJECT(Placer)

public:
    using CallbackHelperBase = Widget;

    OMNIUI_API
    ~Placer() override;

    OMNIUI_API
    void destroy() override;

    /**
     * @brief Reimplemented adding a widget to this Placer. The Placer class can not contain multiple widgets.
     *
     * @see Container::addChild
     */
    OMNIUI_API
    void addChild(std::shared_ptr<Widget> widget) override;

    /**
     * @brief Reimplemented to simply set the single child to null
     *
     * @see Container::clear
     */
    OMNIUI_API
    void clear() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the minimal size of the child widget.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the minimal size of the child widget.
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
     * @brief offsetX defines the offset placement for the child widget relative to the Placer
     *
     * TODO: We will need percents to be able to keep the relative position when scaling.
     * Example: In Blender sequencer when resizing the window the relative position of tracks is not changing.
     */
    OMNIUI_PROPERTY(Length, offsetX, DEFAULT, Pixel(0.0f), READ, getOffsetX, WRITE, setOffsetX, NOTIFY, setOffsetXChangedFn);

    /**
     * @brief offsetY defines the offset placement for the child widget relative to the Placer
     *
     */
    OMNIUI_PROPERTY(Length, offsetY, DEFAULT, Pixel(0.0f), READ, getOffsetY, WRITE, setOffsetY, NOTIFY, setOffsetYChangedFn);

    /**
     * @brief Provides a convenient way to make an item draggable.
     *
     * TODO:
     * dragMaximumX
     * dragMaximumY
     * dragMinimumX
     * dragMinimumY
     * dragThreshold
     */
    OMNIUI_PROPERTY(bool, draggable, DEFAULT, false, READ, isDraggable, WRITE, setDraggable);

    /**
     * @brief Sets if dragging can be horizontally or vertically.
     */
    OMNIUI_PROPERTY(Axis, dragAxis, DEFAULT, Axis::eXY, READ, getDragAxis, WRITE, setDragAxis);

    /**
     * @brief The placer size depends on the position of the child when false.
     */
    OMNIUI_PROPERTY(bool, stableSize, DEFAULT, false, READ, isStableSize, WRITE, setStableSize);

    /**
     * @brief Set number of frames to start dragging if drag is not detected the first frame.
     */
    OMNIUI_PROPERTY(uint32_t, framesToStartDrag, DEFAULT, 0, READ, getFramesToStartDrag, WRITE, setFramesToStartDrag);

protected:
    /**
     * @brief Construct Placer
     */
    OMNIUI_API
    Placer();

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

    /**
     * @brief This method fills an unordered set with the visible minimum and
     * maximum values of the Widget and children.
     */
    OMNIUI_API
    void _fillVisibleThreshold(void* thresholds) const override;

private:
    struct PlacerData;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
