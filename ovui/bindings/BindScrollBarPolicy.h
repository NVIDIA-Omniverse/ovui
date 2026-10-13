/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/ScrollBarPolicy.h>
#include <omni/ui/bind/Pybind.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapScrollBarPolicy(module& m)
{
    enum_<ScrollBarPolicy>(m, "ScrollBarPolicy", "")
        .value("SCROLLBAR_AS_NEEDED", ScrollBarPolicy::eScrollBarAsNeeded)
        .value("SCROLLBAR_ALWAYS_OFF", ScrollBarPolicy::eScrollBarAlwaysOff)
        .value("SCROLLBAR_ALWAYS_ON", ScrollBarPolicy::eScrollBarAlwaysOn);
}
