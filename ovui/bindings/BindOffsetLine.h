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

#include <omni/ui/OffsetLine.h>
#include <omni/ui/bind/BindOffsetLine.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapOffsetLine(module& m)
{
    constexpr const char* offsetLineDoc = OMNIUI_PYBIND_CLASS_DOC(OffsetLine);
    static constexpr char offsetLineConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(OffsetLine, OffsetLine);
    class_<OffsetLine, FreeLine, std::shared_ptr<OffsetLine>>(m, "OffsetLine", offsetLineDoc)
        .def(init([](std::shared_ptr<Widget> from, std::shared_ptr<Widget> to, kwargs kwargs) {
                 OMNIUI_PYBIND_INIT(OffsetLine, from, to)
             }),
             "")
        .def_property("offset", &OffsetLine::getOffset, &OffsetLine::setOffset, OMNIUI_PYBIND_DOC_OffsetLine_offset)
        .def_property("bound_offset", &OffsetLine::getBoundOffset, &OffsetLine::setBoundOffset, OMNIUI_PYBIND_DOC_OffsetLine_boundOffset)
        /**/;
}
