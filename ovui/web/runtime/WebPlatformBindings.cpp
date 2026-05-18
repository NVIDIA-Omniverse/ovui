/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "WebPlatform.h"

#include "../../bindings/PlatformBindings.h"

#include <pybind11/pybind11.h>

namespace omni {
namespace ui {

void registerPlatformBindings(pybind11::module_& m)
{
    m.def("_web_init", &web::init,
          "Initialize the browser WebGL/ImGui backend for the embedded CPython pybind11 module",
          pybind11::arg("canvas_selector") = "#canvas",
          pybind11::arg("width") = 1280,
          pybind11::arg("height") = 640,
          pybind11::arg("device_pixel_ratio") = 1.0f);
    m.def("_web_tick", &web::tick, "Render one browser frame");
    m.def("_web_shutdown", &web::shutdown, "Shut down the browser backend");
    m.def("_web_reset", &web::resetWorkspace, "Clear registered omni.ui windows before running a new script");
    m.def("_web_set_canvas_size", &web::setCanvasSize,
          "Resize the WebGL canvas backing store",
          pybind11::arg("width"), pybind11::arg("height"), pybind11::arg("device_pixel_ratio") = 1.0f);
    m.def("_web_window_callback_count", &web::windowCallbackCount,
          "Return the number of active browser window callbacks");
    m.def("_web_backend_info", &web::backendInfo,
          "Return a description of the active pybind11/WebAssembly renderer");
    m.def("_web_font_info", &web::fontInfo,
          "Return the packaged font load status");
    m.def("_web_dpi_info", &web::dpiInfo,
          "Return browser DPR, framebuffer scale, and ImGui font rasterizer density diagnostics");
}

} // namespace ui
} // namespace omni
