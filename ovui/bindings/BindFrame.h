/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Frame.h>
#include <omni/ui/bind/BindFrame.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapFrame(module& m)
{
    constexpr const char* stackDoc = OMNIUI_PYBIND_CLASS_DOC(Frame);
    static constexpr char stackConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Frame, Frame);

    class_<Frame, Container, std::shared_ptr<Frame>>(m, "Frame", stackDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Frame) }), stackConstructorDoc)
        .OMNIUI_PYBIND_DEF_CALLBACK(build, Frame, Build)
        .def("rebuild", &Frame::rebuild, OMNIUI_PYBIND_DOC_Frame_rebuild)
        .def("invalidate_raster", &Frame::invalidateRaster, OMNIUI_PYBIND_DOC_RasterHelper_invalidateRaster)
        .def_property("horizontal_clipping", &Frame::isHorizontalClipping, &Frame::setHorizontalClipping,
                      OMNIUI_PYBIND_DOC_Frame_horizontalClipping)
        .def_property("vertical_clipping", &Frame::isVerticalClipping, &Frame::setVerticalClipping,
                      OMNIUI_PYBIND_DOC_Frame_verticalClipping)
        .def_property("separate_window", &Frame::isSeparateWindow, &Frame::setSeparateWindow,
                      OMNIUI_PYBIND_DOC_Frame_separateWindow)
        .def_property("raster_policy", &Frame::getRasterPolicy, &Frame::setRasterPolicy,
                      OMNIUI_PYBIND_DOC_RasterHelper_rasterPolicy)
        .def_property("frozen", &Frame::isFrozen, &Frame::setFrozen,
                      OMNIUI_PYBIND_DOC_Frame_separateWindow)
        /* */;
}
