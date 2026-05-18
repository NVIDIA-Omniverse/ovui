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

#include <omni/ui/Alignment.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapAlignment(module& m)
{
    enum_<Alignment>(m, "Alignment", "")
        .value("UNDEFINED", Alignment::eUndefined)
        .value("LEFT_TOP", Alignment::eLeftTop)
        .value("LEFT_CENTER", Alignment::eLeftCenter)
        .value("LEFT_BOTTOM", Alignment::eLeftBottom)
        .value("CENTER_TOP", Alignment::eCenterTop)
        .value("CENTER", Alignment::eCenter)
        .value("CENTER_BOTTOM", Alignment::eCenterBottom)
        .value("RIGHT_TOP", Alignment::eRightTop)
        .value("RIGHT_CENTER", Alignment::eRightCenter)
        .value("RIGHT_BOTTOM", Alignment::eRightBottom)
        .value("LEFT", Alignment::eLeft)
        .value("RIGHT", Alignment::eRight)
        .value("H_CENTER", Alignment::eHCenter)
        .value("TOP", Alignment::eTop)
        .value("BOTTOM", Alignment::eBottom)
        .value("V_CENTER", Alignment::eVCenter);
}
