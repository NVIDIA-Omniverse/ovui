/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/TimelinePlot.h>
#include <omni/ui/bind/BindTimelinePlot.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/Pybind.h>

#include <utility>
#include <vector>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapTimelinePlot(module& m)
{
    constexpr const char* timelineDoc = OMNIUI_PYBIND_CLASS_DOC(TimelinePlot);
    static constexpr char timelineConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(TimelinePlot, TimelinePlot);

    class_<TimelinePlot, Widget, std::shared_ptr<TimelinePlot>>(m, "TimelinePlot", timelineDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(TimelinePlot) }), timelineConstructorDoc)
        .def_property(
            "lane_height",
            &TimelinePlot::getLaneHeight,
            &TimelinePlot::setLaneHeight,
            OMNIUI_PYBIND_DOC_TimelinePlot_laneHeight)
        .def(
            "set_data",
            [](TimelinePlot& self,
               iterable laneLabelValues,
               iterable groupRowValues,
               iterable intervalValues) {
                const auto lengthHint = [](handle values) -> size_t {
                    const Py_ssize_t result = PyObject_LengthHint(values.ptr(), 0);
                    if (result < 0)
                    {
                        throw error_already_set();
                    }
                    return static_cast<size_t>(result);
                };

                std::vector<object> labelOwners;
                std::vector<TimelineLabelView> laneLabels;
                const size_t labelCountHint = lengthHint(laneLabelValues);
                labelOwners.reserve(labelCountHint);
                laneLabels.reserve(labelCountHint);
                for (handle value : laneLabelValues)
                {
                    object owner = reinterpret_borrow<object>(value);
                    Py_ssize_t textLength = 0;
                    const char* text = PyUnicode_AsUTF8AndSize(owner.ptr(), &textLength);
                    if (!text)
                    {
                        throw error_already_set();
                    }
                    labelOwners.push_back(std::move(owner));
                    laneLabels.push_back(TimelineLabelView{ text, static_cast<size_t>(textLength) });
                }

                std::vector<uint32_t> groupRows;
                groupRows.reserve(lengthHint(groupRowValues));
                for (handle value : groupRowValues)
                {
                    groupRows.push_back(value.cast<uint32_t>());
                }

                std::vector<TimelineInterval> intervals;
                intervals.reserve(lengthHint(intervalValues));
                for (handle value : intervalValues)
                {
                    sequence fields = reinterpret_borrow<sequence>(value);
                    if (fields.size() != 4)
                    {
                        throw value_error(
                            "timeline interval must contain lane, start seconds, duration milliseconds, and color index");
                    }
                    intervals.push_back(TimelineInterval{
                        fields[0].cast<uint32_t>(),
                        fields[1].cast<double>(),
                        fields[2].cast<double>(),
                        fields[3].cast<uint32_t>(),
                    });
                }
                self.setDataCopy(TimelinePlotDataView{
                    laneLabels.data(),
                    laneLabels.size(),
                    groupRows.data(),
                    groupRows.size(),
                    intervals.data(),
                    intervals.size(),
                });
            },
            arg("lane_labels"),
            arg("group_rows"),
            arg("intervals"),
            OMNIUI_PYBIND_DOC_TimelinePlot_setData)
        .def(
            "set_time_range",
            &TimelinePlot::setTimeRange,
            arg("start_seconds"),
            arg("end_seconds"),
            OMNIUI_PYBIND_DOC_TimelinePlot_setTimeRange);
}
