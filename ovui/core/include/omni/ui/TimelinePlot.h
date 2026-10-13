/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Widget.h"

#include <cstddef>
#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

/** @brief One duration sample rendered on a timeline lane. */
struct TimelineInterval
{
    uint32_t laneIndex = 0; /**< Zero-based row within the timeline. */
    double startSeconds = 0.0; /**< Sample start relative to process start. */
    double durationMilliseconds = 0.0; /**< Sample duration. */
    uint32_t colorIndex = 0; /**< Stable index into the widget's visible color palette. */
};

/** @brief Non-owning UTF-8 label used by @ref TimelinePlotDataView. */
struct TimelineLabelView
{
    const char* text = nullptr;
    size_t length = 0;
};

/**
 * @brief Non-owning arrays rendered by TimelinePlot.
 *
 * Every pointer must remain valid and unchanged until another data view is set
 * or the widget is destroyed. Label text must be null terminated; @ref
 * TimelineLabelView::length avoids scanning it. This view is the zero-copy C++
 * update path.
 */
struct TimelinePlotDataView
{
    const TimelineLabelView* laneLabels = nullptr;
    size_t laneLabelCount = 0;
    const uint32_t* groupRows = nullptr;
    size_t groupRowCount = 0;
    const TimelineInterval* intervals = nullptr;
    size_t intervalCount = 0;
};

/**
 * @brief Batched duration timeline rendered directly with ImGui draw commands.
 *
 * The widget draws every lane and interval without allocating child widgets.
 * This keeps metric timelines bounded even when many retained samples are
 * visible. Lane labels are used only for hover details; callers may present
 * their own aligned label/selection panel alongside the widget.
 */
class OMNIUI_CLASS_API TimelinePlot : public Widget
{
    OMNIUI_OBJECT(TimelinePlot)

public:
    OMNIUI_API
    ~TimelinePlot() override;

    /**
     * @brief Point the widget at persistent visible-lane and interval arrays.
     *
     * @param data Non-owning data view. Its arrays and label text must remain
     * valid until the next call or widget destruction.
     */
    OMNIUI_API
    void setData(const TimelinePlotDataView& data);

    /**
     * @brief Copy a temporary view into reusable widget-owned native storage.
     *
     * Lane text is retained in fixed 256-byte strings. Array capacities grow
     * only when necessary and are reused by later calls. Python bindings use
     * this path because Python string and sequence storage is not persistent.
     */
    OMNIUI_API
    void setDataCopy(const TimelinePlotDataView& data);

    /** @brief Set the visible process-relative time range in seconds. */
    OMNIUI_API
    void setTimeRange(double startSeconds, double endSeconds);

    /** @copydoc Widget::setComputedContentWidth */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /** @copydoc Widget::setComputedContentHeight */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /** @brief Height of one group or metric lane in logical pixels. */
    OMNIUI_PROPERTY(float, laneHeight, DEFAULT, 24.0f, READ, getLaneHeight, WRITE, setLaneHeight);

protected:
    OMNIUI_API
    TimelinePlot();

    /** @copydoc Widget::_drawContent */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct TimelinePlotData;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
