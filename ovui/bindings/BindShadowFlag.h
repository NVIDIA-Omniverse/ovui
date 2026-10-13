/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/ShadowFlag.h>

#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapShadowFlag(module& m)
{
    enum_<ShadowFlag>(m, "ShadowFlag", "")
        .value("NONE", ShadowFlag::eNone)
        .value("CUT_OUT_SHAPE_BACKGROUND", ShadowFlag::eCutOutShapeBackground);
}
