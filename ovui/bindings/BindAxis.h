/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Axis.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapAxis(module& m)
{
    enum_<Axis>(m, "Axis").value("NONE", Axis::eNone).value("X", Axis::eX).value("Y", Axis::eY).value("XY", Axis::eXY);
}
