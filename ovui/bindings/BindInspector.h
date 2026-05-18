/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Inspector.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/DocInspector.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapInspector(module& m)
{
    class_<Inspector>(m, "Inspector", OMNIUI_PYBIND_DOC_Inspector)
        .def_static("get_children", &Inspector::getChildren, arg("widget"), OMNIUI_PYBIND_DOC_Inspector_getChildren)
        .def_static("get_resolved_style", &Inspector::getResolvedStyle, arg("widget"),
                    OMNIUI_PYBIND_DOC_Inspector_getResolvedStyle)
        .def_static("begin_computed_width_metric", &Inspector::beginComputedWidthMetric,
                    OMNIUI_PYBIND_DOC_Inspector_beginComputedWidthMetric)
        .def_static("end_computed_width_metric", &Inspector::endComputedWidthMetric,
                    OMNIUI_PYBIND_DOC_Inspector_endComputedWidthMetric)
        .def_static("begin_computed_height_metric", &Inspector::beginComputedHeightMetric,
                    OMNIUI_PYBIND_DOC_Inspector_beginComputedHeightMetric)
        .def_static("end_computed_height_metric", &Inspector::endComputedHeightMetric,
                    OMNIUI_PYBIND_DOC_Inspector_endComputedHeightMetric)
        .def_static("get_stored_font_atlases", &Inspector::getStoredFontAtlases,
                    OMNIUI_PYBIND_DOC_Inspector_getStoredFontAtlases)
        /**/;
}
