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

#include <omni/ui/ArrowHelper.h>
#include <omni/ui/bind/BindArrowHelper.h>
#include <omni/ui/bind/Pybind.h>

#include <memory>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapArrowHelper(module& m)
{
    enum_<ArrowHelper::ArrowType>(m, "ArrowType", "")
        .value("NONE", ArrowHelper::ArrowType::eNone)
        .value("ARROW", ArrowHelper::ArrowType::eArrow);

    constexpr const char* arrowDoc = OMNIUI_PYBIND_CLASS_DOC(ArrowHelper);
    static constexpr char arrowConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ArrowHelper, ArrowHelper);

    class_<ArrowHelper, std::shared_ptr<ArrowHelper>>(m, "ArrowHelper", arrowDoc)
        .def_property("begin_arrow_width", &ArrowHelper::getBeginArrowWidth, &ArrowHelper::setBeginArrowWidth,
                      OMNIUI_PYBIND_DOC_ArrowHelper_beginArrowWidth)
        .def_property("begin_arrow_height", &ArrowHelper::getBeginArrowHeight, &ArrowHelper::setBeginArrowHeight,
                      OMNIUI_PYBIND_DOC_ArrowHelper_beginArrowHeight)
        .def_property("begin_arrow_type", &ArrowHelper::getBeginArrowType, &ArrowHelper::setBeginArrowType,
                      OMNIUI_PYBIND_DOC_ArrowHelper_beginArrowType)
        .def_property("end_arrow_width", &ArrowHelper::getEndArrowWidth, &ArrowHelper::setEndArrowWidth,
                      OMNIUI_PYBIND_DOC_ArrowHelper_endArrowWidth)
        .def_property("end_arrow_height", &ArrowHelper::getEndArrowHeight, &ArrowHelper::setEndArrowHeight,
                      OMNIUI_PYBIND_DOC_ArrowHelper_endArrowHeight)
        .def_property("end_arrow_type", &ArrowHelper::getEndArrowType, &ArrowHelper::setEndArrowType,
                      OMNIUI_PYBIND_DOC_ArrowHelper_endArrowType);
}
