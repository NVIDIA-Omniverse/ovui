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
#include <omni/ui/scene/Scene.h>
#include <omni/ui/scene/bind/BindScene.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapScene(module& m)
{
    constexpr const char* sceneDoc = OMNIUI_PYBIND_CLASS_DOC(Scene);
    static constexpr char sceneConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Scene, Scene);

    class_<Scene, AbstractContainer, std::shared_ptr<Scene>>(m, "Scene", sceneDoc)
        .def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Scene) }), sceneConstructorDoc)
        .def_property_readonly(
            "draw_list_buffer_count", &Scene::getDrawListBufferCount, OMNIUI_PYBIND_DOC_Scene_getDrawListBufferCount)
        /* */;
}
