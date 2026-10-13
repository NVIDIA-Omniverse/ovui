/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_Plot                                                                                        \
    "A plot with legacy drawing by default. Select PlotMode.INTERACTIVE for axes, scatter, bars, and mouse controls.\n"\
    "\n"


#define OMNIUI_PYBIND_DOC_Plot_Type "This type is used to determine the type of the image.\n"


#define OMNIUI_PYBIND_DOC_Plot_setComputedContentHeight                                                               \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than 1 pixel.\n"


#define OMNIUI_PYBIND_DOC_Plot_setDataProviderFn "Sets the function that will be called when when data required.\n"


#define OMNIUI_PYBIND_DOC_Plot_setData "Sets the image data value.\n"


#define OMNIUI_PYBIND_DOC_Plot_type                                                                                   \
    "Select line, histogram, or XY line. Interactive mode also supports scatter and bars. By default, the type is line.\n"


#define OMNIUI_PYBIND_DOC_Plot_scaleMin "This property holds the min scale values. By default, the value is FLT_MAX.\n"


#define OMNIUI_PYBIND_DOC_Plot_scaleMax "This property holds the max scale values. By default, the value is FLT_MAX.\n"


#define OMNIUI_PYBIND_DOC_Plot_valueOffset "This property holds the value offset. By default, the value is 0.\n"


#define OMNIUI_PYBIND_DOC_Plot_valueStride                                                                            \
    "This property holds the stride to get value list. By default, the value is 1.\n"


#define OMNIUI_PYBIND_DOC_Plot_title "This property holds the title of the image.\n"


#define OMNIUI_PYBIND_DOC_Plot_Plot                                                                                   \
    "Construct Plot. The first two arguments after type remain scale_min and scale_max. Use set_data() for samples in interactive mode.\n"\
    "\n"                                                                                                              \
    "\n"                                                                                                              \
    "### Arguments:\n"                                                                                                \
    "\n"                                                                                                              \
    "    `type :`\n"                                                                                                  \
    "        The type of the image, can be line or histogram.\n"                                                      \
    "\n"                                                                                                              \
    "    `scaleMin :`\n"                                                                                              \
    "        The minimal scale value.\n"                                                                              \
    "\n"                                                                                                              \
    "    `scaleMax :`\n"                                                                                              \
    "        The maximum scale value.\n"                                                                              \
    "\n"                                                                                                              \
    "    `valueList :`\n"                                                                                             \
    "        The list of values to draw the image.\n"

#define OMNIUI_PYBIND_DOC_Plot_mode "Drawing mode. PlotMode.LEGACY preserves the original drawing and is the default.\n"
#define OMNIUI_PYBIND_DOC_Plot_xLabel "The primary X-axis label.\n"
#define OMNIUI_PYBIND_DOC_Plot_yLabel "The primary Y-axis label.\n"
#define OMNIUI_PYBIND_DOC_Plot_seriesLabel "The series label used by the legend and hover information.\n"
#define OMNIUI_PYBIND_DOC_Plot_showTitle "Whether the plot title is visible.\n"
#define OMNIUI_PYBIND_DOC_Plot_showLegend "Whether the legend is visible.\n"
#define OMNIUI_PYBIND_DOC_Plot_interactive "Whether mouse pan, zoom, selection, and menus are enabled.\n"
#define OMNIUI_PYBIND_DOC_Plot_autoFit "Whether both axes continuously fit the retained data.\n"
#define OMNIUI_PYBIND_DOC_Plot_sparkline                                                                              \
    "Whether to render as a decoration-free, non-interactive sparkline.\n"
#define OMNIUI_PYBIND_DOC_Plot_crosshairs "Whether hovering the plot replaces the cursor with a crosshair.\n"
#define OMNIUI_PYBIND_DOC_Plot_showMousePosition                                                                      \
    "Whether the current plot-space mouse coordinates are visible.\n"
#define OMNIUI_PYBIND_DOC_Plot_showMarkers "Whether line plots draw a circular marker at every sample.\n"
#define OMNIUI_PYBIND_DOC_Plot_showSampleTooltip                                                                      \
    "Whether hovering presents the Y value, X value, and previous-X delta of a retained sample.\n"
#define OMNIUI_PYBIND_DOC_Plot_xAxisFormat                                                                            \
    "Optional printf-style format for primary X-axis tick labels. Empty uses decimal tick labels.\n"
#define OMNIUI_PYBIND_DOC_Plot_sampleTooltipValueLabel                                                                \
    "The Y-value label in the optional sample tooltip. An empty label hides this row.\n"
#define OMNIUI_PYBIND_DOC_Plot_sampleTooltipXLabel                                                                    \
    "The selected X-value label in the optional sample tooltip. An empty label hides this row.\n"
#define OMNIUI_PYBIND_DOC_Plot_sampleTooltipDeltaXLabel                                                               \
    "The previous-X-delta label in the optional sample tooltip. An empty label hides this row.\n"
#define OMNIUI_PYBIND_DOC_Plot_markerSize "The circular sample marker radius in pixels.\n"
#define OMNIUI_PYBIND_DOC_Plot_lineWeight "The plotted line and marker-edge thickness in pixels.\n"
#define OMNIUI_PYBIND_DOC_Plot_setXYData "Replace the retained series with explicit `(x, y)` pairs.\n"
#define OMNIUI_PYBIND_DOC_Plot_fit "Fit both axes to the retained data on the next rendered frame.\n"
#define OMNIUI_PYBIND_DOC_Plot_setAxisLimits                                                                          \
    "Lock the primary axes to explicit X and Y ranges until `fit()` or `clear_axis_limits()` is called.\n"
#define OMNIUI_PYBIND_DOC_Plot_clearAxisLimits                                                                        \
    "Remove explicit axis ranges and fit the retained data on the next rendered frame.\n"
