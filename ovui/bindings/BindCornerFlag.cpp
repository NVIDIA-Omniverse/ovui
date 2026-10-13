/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/CornerFlag.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapCornerFlag(module& m)
{
    enum_<CornerFlag>(m, "CornerFlag", "")
        .value("NONE", CornerFlag::eNone)
        .value("TOP_LEFT", CornerFlag::eTopLeft)
        .value("TOP_RIGHT", CornerFlag::eTopRight)
        .value("BOTTOM_LEFT", CornerFlag::eBottomLeft)
        .value("BOTTOM_RIGHT", CornerFlag::eBottomRight)
        .value("TOP", CornerFlag::eTop)
        .value("BOTTOM", CornerFlag::eBottom)
        .value("LEFT", CornerFlag::eLeft)
        .value("RIGHT", CornerFlag::eRight)
        .value("ALL", CornerFlag::eAll);
}
