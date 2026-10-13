/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/scene/Culling.h>
#include <omni/ui/bind/Pybind.h>


using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapCulling(module& m)
{
    enum_<Culling>(m, "Culling").value("NONE", Culling::eNone).value("BACK", Culling::eBack).value("FRONT", Culling::eFront)
        /**/;
}
