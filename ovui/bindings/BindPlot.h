/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Plot.h>
#include <omni/ui/bind/BindPlot.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapPlot(module& m)
{
    constexpr const char* plotDoc = OMNIUI_PYBIND_CLASS_DOC(Plot);
    static constexpr char plotConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Plot, Plot);

    enum_<Plot::Type>(m, "Type", "")
        .value("LINE", Plot::Type::eLine)
        .value("HISTOGRAM", Plot::Type::eHistogram)
        .value("LINE2D", Plot::Type::eLine2D)
        .value("SCATTER", Plot::Type::eScatter)
        .value("BARS", Plot::Type::eBars);
    m.attr("PlotType") = m.attr("Type");

    enum_<Plot::Mode>(m, "PlotMode", "Selects legacy or interactive plot drawing.")
        .value("LEGACY", Plot::Mode::eLegacy)
        .value("INTERACTIVE", Plot::Mode::eInteractive);

    class_<Plot, Widget, std::shared_ptr<Plot>>(m, "Plot", plotDoc)
        .def(init([](Plot::Type type, float scale_min, float scale_max, args args, kwargs kwargs) {
                 if (kwargs.contains("mode") && kwargs["mode"].cast<Plot::Mode>() == Plot::Mode::eInteractive)
                 {
                     std::vector<double> samples;
                     if (args.size() != 0 && isinstance<function>(args[0]))
                     {
                         if (args.size() != 2)
                             throw type_error("Plot provider needs a values count");
                         auto fn = args[0].cast<std::function<double(int)>>();
                         int count = args[1].cast<int>();
                         for (int index = 0; index < count; ++index)
                             samples.push_back(fn(index));
                     }
                     else
                     {
                         samples.reserve(args.size());
                         for (const auto& value : args)
                             samples.push_back(value.cast<double>());
                     }
                     OMNIUI_PYBIND_INIT(Plot, type, Plot::Mode::eInteractive, std::move(samples), scale_min, scale_max)
                 }
                 std::vector<float> valueList;

                 auto argsBegin = args.begin();
                 auto argsEnd = args.end();
                 if (argsBegin != argsEnd)
                 {
                     auto& arg = *argsBegin;
                     if (isinstance<function>(arg))
                     {
                         auto fn = arg.cast<std::function<float(int)>>();
                         int32_t valuesCount = 0;
                         if (++argsBegin == argsEnd)
                         {
                             OMNIUI_LOG_WARN("Plot Constructor: values count not found.");
                         }
                         else
                         {
                             auto& argCount = *argsBegin;
                             if (isinstance<int_>(*argCount))
                             {
                                 valuesCount = argCount.cast<int32_t>();
                                 valueList.reserve(valuesCount);
                                 for (int32_t i = 0; i < valuesCount; i++)
                                     valueList.push_back(fn(i));
                             }
                             else
                             {
                                 OMNIUI_LOG_WARN("Plot Constructor: argument is not int");
                             }
                         }
                     }
                     else if (isinstance<float_>(arg))
                     {
                         valueList.reserve(args.size());
                         while (argsBegin != argsEnd)
                         {
                             auto& argValue = *argsBegin;
                             if (isinstance<float_>(*argValue))
                             {
                                 valueList.push_back(argValue.cast<float_t>());
                             }
                             else
                             {
                                 OMNIUI_LOG_WARN("Plot Constructor: argument is not float");
                             }
                             argsBegin++;
                         }
                     }
                     else
                     {
                         OMNIUI_LOG_WARN("Plot Constructor: unknown argument");
                     }
                 }
                 OMNIUI_PYBIND_INIT(Plot, type, scale_min, scale_max, valueList)
             }),
             arg("type") = Plot::Type::eLine, arg("scale_min") = FLT_MAX, arg("scale_max") = FLT_MAX, plotConstructorDoc)
        .def_property("mode", &Plot::getMode, &Plot::setMode, OMNIUI_PYBIND_DOC_Plot_mode)
        .def_property("type", &Plot::getType, &Plot::setType, OMNIUI_PYBIND_DOC_Plot_type)
        .def_property("scale_min", &Plot::getScaleMin, &Plot::setScaleMin, OMNIUI_PYBIND_DOC_Plot_scaleMin)
        .def_property("scale_max", &Plot::getScaleMax, &Plot::setScaleMax, OMNIUI_PYBIND_DOC_Plot_scaleMax)
        .def_property("value_offset", &Plot::getValueOffset, &Plot::setValueOffset, OMNIUI_PYBIND_DOC_Plot_valueOffset)
        .def_property("value_stride", &Plot::getValueStride, &Plot::setValueStride, OMNIUI_PYBIND_DOC_Plot_valueStride)
        .def_property("title", &Plot::getTitle, &Plot::setTitle, OMNIUI_PYBIND_DOC_Plot_title)
        .def_property("x_label", &Plot::getXLabel, &Plot::setXLabel, OMNIUI_PYBIND_DOC_Plot_xLabel)
        .def_property("y_label", &Plot::getYLabel, &Plot::setYLabel, OMNIUI_PYBIND_DOC_Plot_yLabel)
        .def_property("series_label", &Plot::getSeriesLabel, &Plot::setSeriesLabel,
                      OMNIUI_PYBIND_DOC_Plot_seriesLabel)
        .def_property("show_title", &Plot::isShowTitle, &Plot::setShowTitle, OMNIUI_PYBIND_DOC_Plot_showTitle)
        .def_property("show_legend", &Plot::isShowLegend, &Plot::setShowLegend,
                      OMNIUI_PYBIND_DOC_Plot_showLegend)
        .def_property("interactive", &Plot::isInteractive, &Plot::setInteractive,
                      OMNIUI_PYBIND_DOC_Plot_interactive)
        .def_property("auto_fit", &Plot::isAutoFit, &Plot::setAutoFit, OMNIUI_PYBIND_DOC_Plot_autoFit)
        .def_property("sparkline", &Plot::isSparkline, &Plot::setSparkline, OMNIUI_PYBIND_DOC_Plot_sparkline)
        .def_property("crosshairs", &Plot::isCrosshairs, &Plot::setCrosshairs,
                      OMNIUI_PYBIND_DOC_Plot_crosshairs)
        .def_property("show_mouse_position", &Plot::isShowMousePosition, &Plot::setShowMousePosition,
                      OMNIUI_PYBIND_DOC_Plot_showMousePosition)
        .def_property("show_markers", &Plot::isShowMarkers, &Plot::setShowMarkers,
                      OMNIUI_PYBIND_DOC_Plot_showMarkers)
        .def_property("show_sample_tooltip", &Plot::isShowSampleTooltip, &Plot::setShowSampleTooltip,
                      OMNIUI_PYBIND_DOC_Plot_showSampleTooltip)
        .def_property("x_axis_format", &Plot::getXAxisFormat, &Plot::setXAxisFormat,
                      OMNIUI_PYBIND_DOC_Plot_xAxisFormat)
        .def_property("sample_tooltip_value_label", &Plot::getSampleTooltipValueLabel,
                      &Plot::setSampleTooltipValueLabel, OMNIUI_PYBIND_DOC_Plot_sampleTooltipValueLabel)
        .def_property("sample_tooltip_x_label", &Plot::getSampleTooltipXLabel, &Plot::setSampleTooltipXLabel,
                      OMNIUI_PYBIND_DOC_Plot_sampleTooltipXLabel)
        .def_property("sample_tooltip_delta_x_label", &Plot::getSampleTooltipDeltaXLabel,
                      &Plot::setSampleTooltipDeltaXLabel, OMNIUI_PYBIND_DOC_Plot_sampleTooltipDeltaXLabel)
        .def_property("marker_size", &Plot::getMarkerSize, &Plot::setMarkerSize,
                      OMNIUI_PYBIND_DOC_Plot_markerSize)
        .def_property("line_weight", &Plot::getLineWeight, &Plot::setLineWeight,
                      OMNIUI_PYBIND_DOC_Plot_lineWeight)
        .def("set_data_provider_fn",
             [](Plot& self, object fn, int valuesCount) {
                 if (self.getMode() == Plot::Mode::eInteractive)
                     self.setSampleProviderFn(wrapPythonCallback(fn.cast<std::function<double(int)>>()), valuesCount);
                 else
                     self.setDataProviderFn(wrapPythonCallback(fn.cast<std::function<float(int)>>()), valuesCount);
             },
             OMNIUI_PYBIND_DOC_Plot_setDataProviderFn)
        .def("set_xy_data", [](Plot& self, object values) {
            if (self.getMode() == Plot::Mode::eInteractive)
                self.setXYSamples(values.cast<std::vector<std::pair<double, double>>>());
            else
                self.setXYData(values.cast<std::vector<std::pair<float, float>>>());
        }, OMNIUI_PYBIND_DOC_Plot_setXYData)
        .def("set_data",
             [](Plot& self, args args) {
                 if (self.getMode() == Plot::Mode::eInteractive)
                 {
                     std::vector<double> samples;
                     samples.reserve(args.size());
                     for (const auto& value : args)
                         samples.push_back(value.cast<double>());
                     self.setSamples(std::move(samples));
                     return;
                 }
                 std::vector<float> valueList;

                 auto argsBegin = args.begin();
                 auto argsEnd = args.end();
                 while (argsBegin != argsEnd)
                 {
                     auto& arg = *argsBegin;
                     if (isinstance<float_>(arg))
                     {
                         valueList.push_back(arg.cast<float_t>());
                         argsBegin++;
                     }
                     else
                     {
                         OMNIUI_LOG_WARN("Plot data: unknown argument");
                     }
                 }
                 self.setData(valueList);
             },
             OMNIUI_PYBIND_DOC_Plot_setData)
        .def("fit", &Plot::fit, OMNIUI_PYBIND_DOC_Plot_fit)
        .def("set_axis_limits", &Plot::setAxisLimits, arg("x_min"), arg("x_max"), arg("y_min"), arg("y_max"),
             OMNIUI_PYBIND_DOC_Plot_setAxisLimits)
        .def("clear_axis_limits", &Plot::clearAxisLimits, OMNIUI_PYBIND_DOC_Plot_clearAxisLimits);
}
