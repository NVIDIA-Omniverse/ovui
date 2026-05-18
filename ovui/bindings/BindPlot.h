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

#include <omni/ui/Plot.h>
#include <omni/ui/bind/BindPlot.h>
#include <pybind11/pybind11.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapPlot(module& m)
{
    constexpr const char* plotDoc = OMNIUI_PYBIND_CLASS_DOC(Plot);
    static constexpr char plotConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Plot, Plot);

    enum_<Plot::Type>(m, "Type", "")
        .value("LINE", Plot::Type::eLine)
        .value("HISTOGRAM", Plot::Type::eHistogram)
        .value("LINE2D", Plot::Type::eLine2D);

    class_<Plot, Widget, std::shared_ptr<Plot>>(m, "Plot", plotDoc)
        .def(init([](Plot::Type type, float scale_min, float scale_max, args args, kwargs kwargs) {
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
        .def_property("type", &Plot::getType, &Plot::setType, OMNIUI_PYBIND_DOC_Plot_type)
        .def_property("scale_min", &Plot::getScaleMin, &Plot::setScaleMin, OMNIUI_PYBIND_DOC_Plot_scaleMin)
        .def_property("scale_max", &Plot::getScaleMax, &Plot::setScaleMax, OMNIUI_PYBIND_DOC_Plot_scaleMax)
        .def_property("value_offset", &Plot::getValueOffset, &Plot::setValueOffset, OMNIUI_PYBIND_DOC_Plot_valueOffset)
        .def_property("value_stride", &Plot::getValueStride, &Plot::setValueStride, OMNIUI_PYBIND_DOC_Plot_valueStride)
        .def_property("title", &Plot::getTitle, &Plot::setTitle, OMNIUI_PYBIND_DOC_Plot_title)
        .def("set_data_provider_fn",
             [](Plot& self, std::function<float(int)> fn, int valuesCount) {
                 self.setDataProviderFn(wrapPythonCallback(std::move(fn)), valuesCount);
             },
             OMNIUI_PYBIND_DOC_Plot_setDataProviderFn)
        .def("set_xy_data", &Plot::setXYData)
        .def("set_data",
             [](Plot& self, args args) {
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
             OMNIUI_PYBIND_DOC_Plot_setData);
}
