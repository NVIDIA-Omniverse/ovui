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
