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

#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/Space.h>
#include <omni/ui/scene/bind/BindSpace.h>


using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapSpace(module& m)
{
    enum_<Space>(m, "Space")
        .value("CURRENT", Space::eCurrent)
        .value("WORLD", Space::eWorld)
        .value("OBJECT", Space::eObject)
        .value("NDC", Space::eNdc)
        .value("SCREEN", Space::eScreen)
        /**/;
}
