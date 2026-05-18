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

#ifdef _MSC_VER
#    if _MSC_VER >= 1920
#        ifdef _DEBUG
// Fixing `_invalid_parameter is not a member of global scope` introduced in
// MSVS2019
#            include <crtdefs.h>
#            include <yvals.h>
#        endif
#    endif
#endif

#include <omni/ui/RasterPolicy.h>
#include <omni/ui/bind/DocRasterPolicy.h>
#include <pybind11/pybind11.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapRasterPolicy(module& m)
{
    enum_<RasterPolicy>(m, "RasterPolicy", OMNIUI_PYBIND_DOC_RasterPolicy)
        .value("NEVER", RasterPolicy::eNever, OMNIUI_PYBIND_DOC_RasterPolicy_eNever)
        .value("ON_DEMAND", RasterPolicy::eOnDemand, OMNIUI_PYBIND_DOC_RasterPolicy_eOnDemand)
        .value("AUTO", RasterPolicy::eAuto, OMNIUI_PYBIND_DOC_RasterPolicy_eAuto);
}
