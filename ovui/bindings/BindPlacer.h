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

#include <omni/ui/Placer.h>
#include <omni/ui/bind/BindPlacer.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapPlacer(module& m)
{
    constexpr const char* placerDoc = OMNIUI_PYBIND_CLASS_DOC(Placer);
    static constexpr char placerConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Placer, Placer);

    class_<Placer, Container, std::shared_ptr<Placer>>(m, "Placer", placerDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Placer) }), placerConstructorDoc)
        .def("invalidate_raster", &Placer::invalidateRaster, OMNIUI_PYBIND_DOC_RasterHelper_invalidateRaster)
        .def_property(
            "offset_x", &Placer::getOffsetX, [](Placer& self, handle offset) { self.setOffsetX(toLength(offset)); },
            OMNIUI_PYBIND_DOC_Placer_offsetX)
        .def_property(
            "offset_y", &Placer::getOffsetY, [](Placer& self, handle offset) { self.setOffsetY(toLength(offset)); },
            OMNIUI_PYBIND_DOC_Placer_offsetY)
        .def_property("draggable", &Placer::isDraggable, &Placer::setDraggable, OMNIUI_PYBIND_DOC_Placer_draggable)
        .def_property("drag_axis", &Placer::getDragAxis, &Placer::setDragAxis, OMNIUI_PYBIND_DOC_Placer_dragAxis)
        .def_property("stable_size", &Placer::isStableSize, &Placer::setStableSize, OMNIUI_PYBIND_DOC_Placer_stableSize)
        .def_property("frames_to_start_drag", &Placer::getFramesToStartDrag, &Placer::setFramesToStartDrag,
                      OMNIUI_PYBIND_DOC_Placer_stableSize)
        .def("set_offset_x_changed_fn", wrapCallbackSetter(&Placer::setOffsetXChangedFn), OMNIUI_PYBIND_DOC_Placer_offsetX)
        .def("set_offset_y_changed_fn", wrapCallbackSetter(&Placer::setOffsetYChangedFn), OMNIUI_PYBIND_DOC_Placer_offsetY)
        .def_property("raster_policy", &Placer::getRasterPolicy, &Placer::setRasterPolicy,
                      OMNIUI_PYBIND_DOC_RasterHelper_rasterPolicy)
        /* */;
}
