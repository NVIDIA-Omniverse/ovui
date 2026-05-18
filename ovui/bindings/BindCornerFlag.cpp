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
