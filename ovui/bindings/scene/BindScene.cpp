/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
