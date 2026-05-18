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

#include <omni/ui/Style.h>
#include <omni/ui/bind/BindStyleContainer.h>
#include <omni/ui/bind/DocStyle.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void setDefaultStyle(Style& style, const pybind11::handle& styleFromPython)
{
    style.setDefaultStyle(getStyleContainer(styleFromPython));
}

pybind11::object getDefaultStyle(Style& style)
{
    const auto& styleContainer = style.getDefaultStyle();
    return convertStyleToPython(styleContainer);
}

void wrapStyle(module& m)
{
    // No shared pointer becasue it's a singleton
    class_<Style>(m, "Style", OMNIUI_PYBIND_DOC_Style)
        .def_property("default", &getDefaultStyle, &setDefaultStyle, OMNIUI_PYBIND_DOC_Style_setDefaultStyle)
        .def_static(
            "get_instance", &Style::getInstance, return_value_policy::reference, OMNIUI_PYBIND_DOC_Style_getInstance)
        /* */;
}
