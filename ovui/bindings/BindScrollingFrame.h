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

#include <omni/ui/ScrollingFrame.h>
#include <omni/ui/bind/BindScrollingFrame.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapScrollingFrame(module& m)
{
    constexpr const char* scrollingFrameDoc = OMNIUI_PYBIND_CLASS_DOC(ScrollingFrame);
    static constexpr char scrollingFrameConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ScrollingFrame, ScrollingFrame);
    class_<ScrollingFrame, Frame, std::shared_ptr<ScrollingFrame>>(m, "ScrollingFrame", scrollingFrameDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(ScrollingFrame) }), scrollingFrameConstructorDoc)
        .def_property("scroll_x", &ScrollingFrame::getScrollX, &ScrollingFrame::setScrollX,
                      OMNIUI_PYBIND_DOC_ScrollingFrame_scrollX)
        .def_property("scroll_y", &ScrollingFrame::getScrollY, &ScrollingFrame::setScrollY,
                      OMNIUI_PYBIND_DOC_ScrollingFrame_scrollY)
        .def_property_readonly("scroll_x_max", &ScrollingFrame::getScrollXMax, OMNIUI_PYBIND_DOC_ScrollingFrame_scrollXMax)
        .def_property_readonly("scroll_y_max", &ScrollingFrame::getScrollYMax, OMNIUI_PYBIND_DOC_ScrollingFrame_scrollYMax)
        .def_property("horizontal_scrollbar_policy", &ScrollingFrame::getHorizontalScrollBarPolicy,
                      &ScrollingFrame::setHorizontalScrollBarPolicy,
                      OMNIUI_PYBIND_DOC_ScrollingFrame_horizontalScrollBarPolicy)
        .def_property("vertical_scrollbar_policy", &ScrollingFrame::getVerticalScrollBarPolicy,
                      &ScrollingFrame::setVerticalScrollBarPolicy,
                      OMNIUI_PYBIND_DOC_ScrollingFrame_verticalScrollBarPolicy)
        .def("set_scroll_x_changed_fn",
             [](ScrollingFrame& self, std::function<void(float)> fn) {
                 self.setScrollXChangedFn(wrapPythonCallback(std::move(fn)));
             },
             OMNIUI_PYBIND_DOC_ScrollingFrame_scrollX)
        .def("set_scroll_y_changed_fn",
             [](ScrollingFrame& self, std::function<void(float)> fn) {
                 self.setScrollYChangedFn(wrapPythonCallback(std::move(fn)));
             },
             OMNIUI_PYBIND_DOC_ScrollingFrame_scrollY)
        /* */;
}
