/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindUtils.h"
#include "BindWidget.h"
#include "DocPlot.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Plot                                                                                       \
    OMNIUI_PYBIND_INIT_Widget                                                                                         \
    OMNIUI_PYBIND_INIT_CAST(value_offset, setValueOffset, int)                                                        \
    OMNIUI_PYBIND_INIT_CAST(value_stride, setValueStride, int)                                                        \
    OMNIUI_PYBIND_INIT_CAST(mode, setMode, Plot::Mode)                                                                \
    OMNIUI_PYBIND_INIT_CAST(title, setTitle, std::string)                                                             \
    OMNIUI_PYBIND_INIT_CAST(x_label, setXLabel, std::string)                                                          \
    OMNIUI_PYBIND_INIT_CAST(y_label, setYLabel, std::string)                                                          \
    OMNIUI_PYBIND_INIT_CAST(series_label, setSeriesLabel, std::string)                                                \
    OMNIUI_PYBIND_INIT_CAST(show_title, setShowTitle, bool)                                                           \
    OMNIUI_PYBIND_INIT_CAST(show_legend, setShowLegend, bool)                                                         \
    OMNIUI_PYBIND_INIT_CAST(interactive, setInteractive, bool)                                                        \
    OMNIUI_PYBIND_INIT_CAST(auto_fit, setAutoFit, bool)                                                               \
    OMNIUI_PYBIND_INIT_CAST(sparkline, setSparkline, bool)                                                            \
    OMNIUI_PYBIND_INIT_CAST(crosshairs, setCrosshairs, bool)                                                          \
    OMNIUI_PYBIND_INIT_CAST(show_mouse_position, setShowMousePosition, bool)                                          \
    OMNIUI_PYBIND_INIT_CAST(show_markers, setShowMarkers, bool)                                                       \
    OMNIUI_PYBIND_INIT_CAST(show_sample_tooltip, setShowSampleTooltip, bool)                                          \
    OMNIUI_PYBIND_INIT_CAST(x_axis_format, setXAxisFormat, std::string)                                               \
    OMNIUI_PYBIND_INIT_CAST(sample_tooltip_value_label, setSampleTooltipValueLabel, std::string)                      \
    OMNIUI_PYBIND_INIT_CAST(sample_tooltip_x_label, setSampleTooltipXLabel, std::string)                              \
    OMNIUI_PYBIND_INIT_CAST(sample_tooltip_delta_x_label, setSampleTooltipDeltaXLabel, std::string)                   \
    OMNIUI_PYBIND_INIT_CAST(marker_size, setMarkerSize, float)                                                        \
    OMNIUI_PYBIND_INIT_CAST(line_weight, setLineWeight, float)

#define OMNIUI_PYBIND_KWARGS_DOC_Plot                                                                                 \
    "\n    `value_offset : int`\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Plot_valueOffset                                                                                \
    "\n    `value_stride : int`\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Plot_valueStride                                                                                \
    "\n    `title : str`\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Plot_title                                                                                      \
    "\n    `mode : PlotMode`\n        " OMNIUI_PYBIND_DOC_Plot_mode                                                   \
    "\n    `x_label : str`\n        " OMNIUI_PYBIND_DOC_Plot_xLabel                                                   \
    "\n    `y_label : str`\n        " OMNIUI_PYBIND_DOC_Plot_yLabel                                                   \
    "\n    `series_label : str`\n        " OMNIUI_PYBIND_DOC_Plot_seriesLabel                                         \
    "\n    `show_title : bool`\n        " OMNIUI_PYBIND_DOC_Plot_showTitle                                            \
    "\n    `show_legend : bool`\n        " OMNIUI_PYBIND_DOC_Plot_showLegend                                          \
    "\n    `interactive : bool`\n        " OMNIUI_PYBIND_DOC_Plot_interactive                                         \
    "\n    `auto_fit : bool`\n        " OMNIUI_PYBIND_DOC_Plot_autoFit                                                \
    "\n    `sparkline : bool`\n        " OMNIUI_PYBIND_DOC_Plot_sparkline                                             \
    "\n    `crosshairs : bool`\n        " OMNIUI_PYBIND_DOC_Plot_crosshairs                                           \
    "\n    `show_mouse_position : bool`\n        " OMNIUI_PYBIND_DOC_Plot_showMousePosition                           \
    "\n    `show_markers : bool`\n        " OMNIUI_PYBIND_DOC_Plot_showMarkers                                        \
    "\n    `show_sample_tooltip : bool`\n        " OMNIUI_PYBIND_DOC_Plot_showSampleTooltip                           \
    "\n    `x_axis_format : str`\n        " OMNIUI_PYBIND_DOC_Plot_xAxisFormat                                        \
    "\n    `sample_tooltip_value_label : str`\n        " OMNIUI_PYBIND_DOC_Plot_sampleTooltipValueLabel               \
    "\n    `sample_tooltip_x_label : str`\n        " OMNIUI_PYBIND_DOC_Plot_sampleTooltipXLabel                       \
    "\n    `sample_tooltip_delta_x_label : str`\n        " OMNIUI_PYBIND_DOC_Plot_sampleTooltipDeltaXLabel            \
    "\n    `marker_size : float`\n        " OMNIUI_PYBIND_DOC_Plot_markerSize                                         \
    "\n    `line_weight : float`\n        " OMNIUI_PYBIND_DOC_Plot_lineWeight                                         \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
