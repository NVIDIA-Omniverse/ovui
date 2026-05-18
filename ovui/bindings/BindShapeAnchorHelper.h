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

#include <omni/ui/ShapeAnchorHelper.h>
#include <omni/ui/bind/BindShapeAnchorHelper.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapShapeAnchorHelper(module& m)
{
    constexpr const char* shapeAnchorHelperDoc = OMNIUI_PYBIND_CLASS_DOC(ShapeAnchorHelper);
    static constexpr char shapeAnchorHelperConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(ShapeAnchorHelper, ShapeAnchorHelper);

    class_<ShapeAnchorHelper, std::shared_ptr<ShapeAnchorHelper>>(m, "ShapeAnchorHelper", shapeAnchorHelperDoc)
        .def_property("anchor_position", &ShapeAnchorHelper::getAnchorPosition, &ShapeAnchorHelper::setAnchorPosition,
                      OMNIUI_PYBIND_DOC_ShapeAnchorHelper_anchorPosition)
        .def_property("anchor_alignment", &ShapeAnchorHelper::getAnchorAlignment, &ShapeAnchorHelper::setAnchorAlignment,
                      OMNIUI_PYBIND_DOC_ShapeAnchorHelper_anchorAlignment)
        .OMNIUI_PYBIND_DEF_CALLBACK(anchor, ShapeAnchorHelper, Anchor)
        .def("invalidate_anchor", &ShapeAnchorHelper::invalidateAnchor, OMNIUI_PYBIND_DOC_ShapeAnchorHelper_invalidateAnchor)
        .def("get_closest_parametric_position", &ShapeAnchorHelper::closestParametricPosition, arg("position_x"), arg("position_y"),
             OMNIUI_PYBIND_DOC_ShapeAnchorHelper_closestParamPosition)
        ;
}
