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

#include <omni/ui/Font.h>
#include <omni/ui/bind/BindUtils.h>


using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapFont(module& m)
{
    enum_<FontStyle>(m, "FontStyle", R"(Supported font styles.)")
        .value("NONE", FontStyle::eNone)
        .value("NORMAL", FontStyle::eNormal)
        .value("LARGE", FontStyle::eLarge)
        .value("SMALL", FontStyle::eSmall)
        .value("EXTRA_LARGE", FontStyle::eExtraLarge)
        .value("XXL", FontStyle::eXXL)
        .value("XXXL", FontStyle::eXXL)
        .value("EXTRA_SMALL", FontStyle::eExtraSmall)
        .value("XXS", FontStyle::eXXS)
        .value("XXXS", FontStyle::eXXXS)
        .value("ULTRA", FontStyle::eUltra)
        /* */;
}
