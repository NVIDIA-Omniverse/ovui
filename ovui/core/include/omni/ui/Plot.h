/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Widget.h"

#include <float.h>
#include <functional>
#include <string>
#include <utility>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief A plot with a legacy mode and an interactive draw-list mode.
 */
class OMNIUI_CLASS_API Plot : public Widget
{
    OMNIUI_OBJECT(Plot)

    using PlotData1D = std::vector<float>;
    using PlotData2D = std::vector<std::pair<float, float>>;
    using Samples1D = std::vector<double>;
    using Samples2D = std::vector<std::pair<double, double>>;

public:
    OMNIUI_API
    ~Plot() override;

    /**
     * @brief This type is used to determine the type of the image.
     */
    enum class Type
    {
        eLine,
        eHistogram,
        eLine2D,
        eScatter,
        eBars,
    };

    /** @brief Legacy preserves the original drawing. Interactive adds axes and mouse controls. */
    enum class Mode
    {
        eLegacy,
        eInteractive,
    };

    /** @brief Drawing mode. The default preserves existing Plot code. */
    OMNIUI_PROPERTY(Mode, mode, DEFAULT, Mode::eLegacy, READ, getMode, WRITE, setMode);

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than 1 pixel
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Sets the function that will be called when when data required.
     */
    OMNIUI_API
    virtual void setDataProviderFn(std::function<float(int)> fn, int valuesCount);

    /**
     * @brief Sets the image data value.
     */
    OMNIUI_API
    virtual void setData(PlotData1D valueList);

    /**
     * @brief Sets the 2d data. X coordinate helps to put the point at the exact
     * position. Useful when the points are at different distance.
     */
    OMNIUI_API
    virtual void setXYData(PlotData2D valueList);

    /** @brief Replace indexed samples without reducing their precision. */
    OMNIUI_API
    void setSamples(Samples1D valueList);

    /** @brief Replace samples by calling the provider once for each index. */
    OMNIUI_API
    void setSampleProviderFn(std::function<double(int)> fn, int valuesCount);

    /** @brief Replace XY samples without reducing their precision. */
    OMNIUI_API
    void setXYSamples(Samples2D valueList);

    /** @brief Fit both axes to the retained data on the next rendered frame. */
    OMNIUI_API
    void fit();

    /**
     * @brief Lock the primary axes to explicit ranges.
     *
     * The ranges remain active until fit() or clearAxisLimits() is called. This is
     * useful for synchronized metric sparklines and frozen timeline views.
     */
    OMNIUI_API
    void setAxisLimits(double xMin, double xMax, double yMin, double yMax);

    /** @brief Remove explicit axis ranges and request a one-shot data fit. */
    OMNIUI_API
    void clearAxisLimits();

    /**
     * @brief Select line, histogram, or XY line. Interactive mode also supports scatter and bars.
     * By default, the type is line.
     */
    OMNIUI_PROPERTY(Type, type, DEFAULT, Type::eLine, READ, getType, WRITE, setType);

    /**
     * @brief This property holds the min scale values.
     * By default, the value is FLT_MAX.
     */
    OMNIUI_PROPERTY(float, scaleMin, DEFAULT, FLT_MAX, READ, getScaleMin, WRITE, setScaleMin);

    /**
     * @brief This property holds the max scale values.
     * By default, the value is FLT_MAX.
     */
    OMNIUI_PROPERTY(float, scaleMax, DEFAULT, FLT_MAX, READ, getScaleMax, WRITE, setScaleMax);

    /**
     * @brief This property holds the value offset.
     * By default, the value is 0.
     */
    OMNIUI_PROPERTY(int, valueOffset, DEFAULT, 0, READ, getValueOffset, WRITE, setValueOffset);

    /**
     * @brief This property holds the stride to get value list.
     * By default, the value is 1.
     */
    OMNIUI_PROPERTY(int, valueStride, DEFAULT, 1, READ, getValueStride, WRITE, setValueStride);

    /**
     * @brief This property holds the title of the image.
     */
    OMNIUI_PROPERTY(std::string, title, DEFAULT, "", READ, getTitle, WRITE, setTitle);

    // These properties apply to interactive mode.
    /** @brief Primary X-axis label. */
    OMNIUI_PROPERTY(std::string, xLabel, DEFAULT, "", READ, getXLabel, WRITE, setXLabel);

    /** @brief Optional printf-style format for primary X-axis tick labels. Empty uses decimal tick labels. */
    OMNIUI_PROPERTY(std::string, xAxisFormat, DEFAULT, "", READ, getXAxisFormat, WRITE, setXAxisFormat);

    /** @brief Primary Y-axis label. */
    OMNIUI_PROPERTY(std::string, yLabel, DEFAULT, "", READ, getYLabel, WRITE, setYLabel);

    /** @brief Series label used by the legend and hover information. */
    OMNIUI_PROPERTY(std::string, seriesLabel, DEFAULT, "Values", READ, getSeriesLabel, WRITE, setSeriesLabel);

    /** @brief Whether the plot title is visible. */
    OMNIUI_PROPERTY(bool, showTitle, DEFAULT, true, READ, isShowTitle, WRITE, setShowTitle);

    /** @brief Whether the legend is visible. */
    OMNIUI_PROPERTY(bool, showLegend, DEFAULT, false, READ, isShowLegend, WRITE, setShowLegend);

    /** @brief Whether mouse pan, zoom, selection, and menus are enabled. */
    OMNIUI_PROPERTY(bool, interactive, DEFAULT, true, READ, isInteractive, WRITE, setInteractive);

    /** @brief Whether both axes continuously fit the retained data. */
    OMNIUI_PROPERTY(bool, autoFit, DEFAULT, false, READ, isAutoFit, WRITE, setAutoFit);

    /** @brief Whether to render as a decoration-free, non-interactive sparkline. */
    OMNIUI_PROPERTY(bool, sparkline, DEFAULT, false, READ, isSparkline, WRITE, setSparkline);

    /** @brief Whether hovering the plot replaces the cursor with a crosshair. */
    OMNIUI_PROPERTY(bool, crosshairs, DEFAULT, false, READ, isCrosshairs, WRITE, setCrosshairs);

    /** @brief Whether the current plot-space mouse coordinates are visible. */
    OMNIUI_PROPERTY(bool, showMousePosition, DEFAULT, true, READ, isShowMousePosition, WRITE, setShowMousePosition);

    /** @brief Whether line plots draw a circular marker at every sample. */
    OMNIUI_PROPERTY(bool, showMarkers, DEFAULT, false, READ, isShowMarkers, WRITE, setShowMarkers);

    /** @brief Whether hovering the plot presents retained sample details. */
    OMNIUI_PROPERTY(bool, showSampleTooltip, DEFAULT, false, READ, isShowSampleTooltip, WRITE, setShowSampleTooltip);

    /** @brief Label preceding the Y value in the optional sample tooltip. */
    OMNIUI_PROPERTY(std::string,
                    sampleTooltipValueLabel,
                    DEFAULT,
                    "Value",
                    READ,
                    getSampleTooltipValueLabel,
                    WRITE,
                    setSampleTooltipValueLabel);

    /** @brief Label preceding the selected X value in the optional sample tooltip. */
    OMNIUI_PROPERTY(std::string,
                    sampleTooltipXLabel,
                    DEFAULT,
                    "X",
                    READ,
                    getSampleTooltipXLabel,
                    WRITE,
                    setSampleTooltipXLabel);

    /** @brief Label preceding the delta from the previous X value in the optional sample tooltip. */
    OMNIUI_PROPERTY(std::string,
                    sampleTooltipDeltaXLabel,
                    DEFAULT,
                    "Delta X",
                    READ,
                    getSampleTooltipDeltaXLabel,
                    WRITE,
                    setSampleTooltipDeltaXLabel);

    /** @brief Circular sample marker radius in pixels. */
    OMNIUI_PROPERTY(float, markerSize, DEFAULT, 3.0f, READ, getMarkerSize, WRITE, setMarkerSize);

    /** @brief Plotted line and marker edge thickness in pixels. */
    OMNIUI_PROPERTY(float, lineWeight, DEFAULT, 1.0f, READ, getLineWeight, WRITE, setLineWeight);

protected:
    /**
     * @brief Construct Plot
     *
     * @param type The type of the image, can be line or histogram.
     * @param scaleMin The minimal scale value.
     * @param scaleMax The maximum scale value.
     * @param valueList The list of values to draw the image.
     */
    OMNIUI_API
    Plot(Type type, float scaleMin, float scaleMax, PlotData1D);

    OMNIUI_API
    Plot(Type type, float scaleMin, float scaleMax, PlotData2D valueList);

    /** @brief Construct a plot from double-precision samples in the selected mode. */
    OMNIUI_API
    Plot(Type type, Mode mode, Samples1D valueList, float scaleMin = FLT_MAX, float scaleMax = FLT_MAX);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    void _drawInteractiveContent();
    struct PlotData;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
