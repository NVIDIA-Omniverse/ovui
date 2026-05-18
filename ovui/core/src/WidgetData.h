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

#include <omni/ui/Widget.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

// Number of mouse buttons Widget considers
//
constexpr uint32_t kMouseButtonCount = 5;

struct Widget::WidgetData
{
    virtual ~WidgetData();

    // True when the mouse pointer is inside the widget area.
    // TODO: Have not decided if we need this as a property. Probably when we have signals, it would be useful to have
    // signal that this property is changed.
    bool m_isHovered = false;
    bool m_isWindowHovered = false;
    bool m_isPressed[kMouseButtonCount] = {};
    bool m_isClicked[kMouseButtonCount] = {};

    // If falls, the widget skips margins.
    bool m_useMarginFromStyle = true;

    // True when we need to recompute content width
    SizeDirtyReason m_dirtyWidth = SizeDirtyReason::eSizeChanged;
    // True when we need to recompute content height
    SizeDirtyReason m_dirtyHeight = SizeDirtyReason::eSizeChanged;


    // unit: pixels
    float m_computedContentWidth = 0.0f;
    float m_computedContentHeight = 0.0f;
    float m_computedContentWidthOnDraw = 0.0f;
    float m_computedContentHeightOnDraw = 0.0f;

    // The current mouse position. We need it to decide if the mouse is moved and call m_mouseMovedFn.
    // TODO: Put it to a singleton. It's not good to have it in each widget.
    float m_mouseX = 0.0f;
    float m_mouseY = 0.0f;

    // The parent style definition with the local style definition merged. If there is no local style, this variable is
    // also nullptr.
    std::shared_ptr<StyleContainer> m_resolvedStyle;

    size_t m_styleStateGroupIndex = SIZE_MAX;

    // Margins for fast access
    float m_marginWidthCache = 0.0f;
    float m_marginHeightCache = 0.0f;

    // position from the last call draw call;
    // unit: pixels
    float m_cursorPositionXCache = 0.0f;
    float m_cursorPositionYCache = 0.0f;
    // Offset from parent. We need it to get the position of the widget when it's hidden.
    float m_cursorPositionOffsetXCache = 0.0f;
    float m_cursorPositionOffsetYCache = 0.0f;

    // Buffer variable to indicate if the tooltip was shown in the previous frame. We need it to be able to recreate the
    // widget when we need it.
    bool m_tooltipShown = false;

    // Tooltip support, can be either a simple text or a function callback that can create any widgets
    std::string m_tooltipString;
    // the frame for the tooltip
    std::shared_ptr<Frame> m_tooltipFrame;
    // the timer for the tooltip
    float m_tooltipTimer = 0.0f;

    // Flag to scroll to the widget
    bool m_scrollHereX = false;
    bool m_scrollHereY = false;
    float m_scrollHereXRatio = 0.0f;
    float m_scrollHereYRatio = 0.0f;

    // Drag and Drop
    // The buffer with DnD data. We keep it because ImGui needs to have this buffer every frame.
    std::string m_dragAndDropBuffer;
    bool m_dragActive = false;
    bool m_dropAccepted = false;
    // The frame for the drag and drop tooltip
    std::shared_ptr<Frame> m_dragFrame;

    // Flag when visibleMin/visibleMax is explicitly set.
    bool m_visibleMinSet = false;
    bool m_visibleMaxSet = false;

    // When true, ImGui::SetNextItemAllowOverlap() is called before interactive
    // items drawn by _drawContent() (e.g. InvisibleButton).  Set by Widget::draw()
    // when the parent Stack passes AllowOverlap for ZStack overlap handling.
    bool m_allowItemOverlap = false;

    float m_dpiAtPreviousFrame = 0.0f;
    bool m_wasVisiblePreviousFrame = false;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
