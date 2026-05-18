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
#include <omni/ui/ShapeAnchorHelper.h>
#include <omni/ui/Line.h>
#include <omni/ui/bind/BindLine.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapLine(module& m)
{
    constexpr const char* lineDoc = OMNIUI_PYBIND_CLASS_DOC(Line);
    static constexpr char lineConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Line, Line);

    class_<Line, Shape, ArrowHelper, ShapeAnchorHelper, std::shared_ptr<Line>>(m, "Line", lineDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Line) }), lineConstructorDoc)
        .def_property("alignment", &Line::getAlignment, &Line::setAlignment, OMNIUI_PYBIND_DOC_Line_alignment)
    ;
}
