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

#include <omni/ui/CanvasFrame.h>
#include <omni/ui/bind/BindCanvasFrame.h>
#include <omni/ui/bind/Pybind.h>

#include <memory>
#include <utility>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapCanvasFrame(module& m)
{
    constexpr const char* canvasFrameDoc = OMNIUI_PYBIND_CLASS_DOC(CanvasFrame);
    static constexpr char canvasFrameConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(CanvasFrame, CanvasFrame);

    class_<CanvasFrame, Frame, std::shared_ptr<CanvasFrame>>(m, "CanvasFrame", canvasFrameDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(CanvasFrame) }), canvasFrameConstructorDoc)
        .def_property("pan_x", &CanvasFrame::getPanX, &CanvasFrame::setPanX, OMNIUI_PYBIND_DOC_CanvasFrame_panX)
        .def_property("pan_y", &CanvasFrame::getPanY, &CanvasFrame::setPanY, OMNIUI_PYBIND_DOC_CanvasFrame_panY)
        .def_property("zoom", &CanvasFrame::getZoom, &CanvasFrame::setZoom, OMNIUI_PYBIND_DOC_CanvasFrame_zoom)
        .def_property("zoom_min", &CanvasFrame::getZoomMin, &CanvasFrame::setZoomMin, OMNIUI_PYBIND_DOC_CanvasFrame_zoomMin)
        .def_property("zoom_max", &CanvasFrame::getZoomMax, &CanvasFrame::setZoomMax, OMNIUI_PYBIND_DOC_CanvasFrame_zoomMax)
        .def_property("smooth_zoom", &CanvasFrame::isSmoothZoom, &CanvasFrame::setSmoothZoom,
                      OMNIUI_PYBIND_DOC_CanvasFrame_smoothZoom)
        .def_property(
            "draggable", &CanvasFrame::isDraggable, &CanvasFrame::setDraggable, OMNIUI_PYBIND_DOC_CanvasFrame_draggable)
        .def_property("compatibility", &CanvasFrame::isCompatibility, &CanvasFrame::setCompatibility,
                      OMNIUI_PYBIND_DOC_CanvasFrame_compatibility)
        .def("screen_to_canvas_x",
             [](const CanvasFrame& self, float x) { return self.screenToCanvasX(x * self.getDpiScale()); }, arg("x"),
             OMNIUI_PYBIND_DOC_CanvasFrame_screenToCanvasX)
        .def("screen_to_canvas_y",
             [](const CanvasFrame& self, float y) { return self.screenToCanvasY(y * self.getDpiScale()); }, arg("y"),
             OMNIUI_PYBIND_DOC_CanvasFrame_screenToCanvasY)
        .def("screen_to_canvas",
             [](const CanvasFrame& self, float x, float y) {
                 float dpiScale = self.getDpiScale();
                 return std::make_pair(self.screenToCanvasX(x * dpiScale), self.screenToCanvasY(y * dpiScale));
             },
             arg("x"), arg("y"), "Transforms screen-space coordinates to canvas-space")
        .def("set_pan_key_shortcut", &CanvasFrame::setPanKeyShortcut, arg("mouse_button"), arg("key_flag"),
             OMNIUI_PYBIND_DOC_CanvasFrame_setPanKeyShortcut)
        .def("set_zoom_key_shortcut", &CanvasFrame::setZoomKeyShortcut, arg("mouse_button"), arg("key_flag"),
             OMNIUI_PYBIND_DOC_CanvasFrame_setZoomKeyShortcut)
        .def("set_pan_x_changed_fn", wrapCallbackSetter(&CanvasFrame::setPanXChangedFn), arg("fn"),
             OMNIUI_PYBIND_DOC_CanvasFrame_panX)
        .def("set_pan_y_changed_fn", wrapCallbackSetter(&CanvasFrame::setPanYChangedFn), arg("fn"),
             OMNIUI_PYBIND_DOC_CanvasFrame_panY)
        .def("set_zoom_changed_fn", wrapCallbackSetter(&CanvasFrame::setZoomChangedFn), arg("fn"),
             OMNIUI_PYBIND_DOC_CanvasFrame_zoom)
        /**/;
}
