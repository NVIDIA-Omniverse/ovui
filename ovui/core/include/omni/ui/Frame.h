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
#include "RasterHelper.h"

#include <functional>
#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct FramePrivate;

/**
 * @brief The Frame is a widget that can hold one child widget.
 *
 * Frame is used to crop the contents of a child widget or to draw small widget in a big view. The child widget must be
 * specified with addChild().
 */
class OMNIUI_CLASS_API Frame : public Container, public RasterHelper
{
    OMNIUI_OBJECT(Frame)

public:
    using CallbackHelperBase = Widget;

    OMNIUI_API
    ~Frame() override;

    OMNIUI_API
    void destroy() override;

    /**
     * @brief Reimplemented adding a widget to this Frame. The Frame class can not contain multiple widgets. The widget
     * overrides
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
     * @brief Set the callback that will be called once the frame is visible and the content of the callback will
     * override the frame child. It's useful for lazy load.
     */
    OMNIUI_CALLBACK(Build, void);

    /**
     * @brief After this method is called, the next drawing cycle build_fn will be called again to rebuild everything.
     */
    OMNIUI_API
    virtual void rebuild();

    /**
     * @brief Change dirty bits when the visibility is changed.
     */
    OMNIUI_API void setVisiblePreviousFrame(bool wasVisible, bool dirtySize = true) override;

    /**
     * @brief When the content of the frame is bigger than the frame the exceeding part is not drawn if the clipping is
     * on. It only works for horizontal direction.
     */
    OMNIUI_PROPERTY(bool, horizontalClipping, DEFAULT, false, READ, isHorizontalClipping, WRITE, setHorizontalClipping);

    /**
     * @brief When the content of the frame is bigger than the frame the exceeding part is not drawn if the clipping is
     * on. It only works for vertial direction.
     */
    OMNIUI_PROPERTY(bool, verticalClipping, DEFAULT, false, READ, isVerticalClipping, WRITE, setVerticalClipping);

    /**
     * @brief A special mode where the child is placed to the transparent borderless window. We need it to be able to
     * place the UI to the exact stacking order between other windows.
     */
    OMNIUI_PROPERTY(bool, separateWindow, DEFAULT, false, READ, isSeparateWindow, WRITE, setSeparateWindow);

    OMNIUI_PROPERTY(bool, frozen, DEFAULT, false, READ, isFrozen, WRITE, setFrozen, PROTECTED, NOTIFY, _setFrozenChangedFn);

protected:
    struct FrameData;

    /**
     * @brief Constructs Frame
     */
    OMNIUI_API
    Frame(bool needsPadding = true, FrameData* data = nullptr);

    OMNIUI_API
    Frame(FrameData* data);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * Draw the content.
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
    friend class Placer;
    friend class Inspector;
    friend class Widget;

    static float _evaluateLayout(const Length& canvasLength, float availableLength, float dpiScale);

    /**
     * @brief Replaces m_canvas with m_canvasPending is possible.
     */
    void _processPendingWidget();

    /**
     * @brief Used in Inspector. Calls build_fn if necessary.
     */
    void _populate();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
