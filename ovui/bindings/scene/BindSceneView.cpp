/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

// Standalone variant: carb/logging/Log.h removed;
// CARB_LOG_WARN_ONCE replaced with OMNIUI_LOG_WARN_ONCE (from platform/Log.h via BindUtils.h).
//
#include <omni/ui/bind/BindUtils.h>

//

#include <pybind11/stl.h>

//

#include <omni/ui/scene/Math.h>
#include <omni/ui/scene/Scene.h>
#include <omni/ui/scene/SceneView.h>
#include <omni/ui/scene/bind/BindAbstractManipulatorModel.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindSceneView.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE
static void _setMatrixModel(std::shared_ptr<SceneView>& self, const pybind11::handle& object, const char* itemName)
{
    auto model = self->getModel();

    if (!model)
    {
        throw type_error("Can't set " + std::string(itemName) + " because SceneView doesn't have the model");
        return;
    }

    auto item = model->getItem(itemName);

    if (!model)
    {
        throw type_error("Can't set " + std::string(itemName) +
                         " because the model of SceneView doesn't have the item with name " + std::string(itemName));
        return;
    }

    auto matrix = pythonToMatrix4(object);
    std::vector<Float> list{ matrix[0][0], matrix[0][1], matrix[0][2], matrix[0][3], matrix[1][0], matrix[1][1],
                             matrix[1][2], matrix[1][3], matrix[2][0], matrix[2][1], matrix[2][2], matrix[2][3],
                             matrix[3][0], matrix[3][1], matrix[3][2], matrix[3][3] };
    model->setFloats(item, list);
}

static void _setProjection(std::shared_ptr<SceneView>& self, const pybind11::handle& object)
{
    _setMatrixModel(self, object, "projection");
    OMNIUI_LOG_WARN_ONCE("The property 'SceneView.projection' is deprecated. Please use the model.");
}

static void _setView(std::shared_ptr<SceneView>& self, const pybind11::handle& object)
{
    _setMatrixModel(self, object, "view");
    OMNIUI_LOG_WARN_ONCE("The property 'SceneView.view' is deprecated. Please use the model.");
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE

OMNIUI_NAMESPACE_USING_DIRECTIVE
OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapSceneView(module& m)
{
    enum_<SceneView::AspectRatioPolicy>(m, "AspectRatioPolicy", "")
        .value("STRETCH", SceneView::AspectRatioPolicy::eStretch)
        .value("PRESERVE_ASPECT_FIT", SceneView::AspectRatioPolicy::ePreserveAspectFit)
        .value("PRESERVE_ASPECT_CROP", SceneView::AspectRatioPolicy::ePreserveAspectCrop)
        .value("PRESERVE_ASPECT_VERTICAL", SceneView::AspectRatioPolicy::ePreserveAspectVertical)
        .value("PRESERVE_ASPECT_HORIZONTAL", SceneView::AspectRatioPolicy::ePreserveAspectHorizontal);

    constexpr const char* sceneViewDoc = OMNIUI_PYBIND_CLASS_DOC(SceneView);
    static constexpr char sceneViewConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(SceneView, SceneView);

    class_<SceneView, omni::ui::Widget, std::shared_ptr<SceneView>>(m, "SceneView", sceneViewDoc)
        .def(init([](const std::shared_ptr<AbstractManipulatorModel>& model, kwargs kwargs)
                  { OMNIUI_PYBIND_INIT(SceneView, model) }),
             arg("model") = nullptr, sceneViewConstructorDoc)
        .def("get_ray_from_ndc",
             [](const SceneView& self, const Vector2& ndc) -> std::pair<Vector3, Vector3>
             {
                 Vector3 origin;
                 Vector3 direction;
                 self.getRayFromNdc(ndc, &origin, &direction);
                 return std::make_pair(origin, direction);
             },
             arg("ndc"), OMNIUI_PYBIND_DOC_ManipulatorModelHelper_getRayFromNdc)
        .def_property(
            "model", &SceneView::getModel, &SceneView::setModel, OMNIUI_PYBIND_DOC_ManipulatorModelHelper_getModel)
        .def_property("projection", &SceneView::getProjection, &_setProjection, OMNIUI_PYBIND_DOC_SceneView_getProjection)
        .def_property("view", &SceneView::getView, &_setView, OMNIUI_PYBIND_DOC_SceneView_getView)
        .def_property("aspect_ratio_policy", &SceneView::getAspectRatioPolicy, &SceneView::setAspectRatioPolicy,
                      OMNIUI_PYBIND_DOC_SceneView_aspectRatioPolicy)
        .def_property("screen_aspect_ratio", &SceneView::getScreenAspectRatio, &SceneView::setScreenAspectRatio,
                      OMNIUI_PYBIND_DOC_SceneView_screenAspectRatio)
        .def_property("child_windows_input", &SceneView::isChildWindowsInput, &SceneView::setChildWindowsInput,
                      OMNIUI_PYBIND_DOC_SceneView_childWindowsInput)
        .def_property("scene", &SceneView::getScene, &SceneView::setScene, OMNIUI_PYBIND_DOC_SceneView_scene)
        .def_property("cache_draw_buffer", &SceneView::getCacheDrawBuffer, &SceneView::setCacheDrawBuffer, OMNIUI_PYBIND_DOC_SceneView_cacheDrawBuffer);
    /* */;
}
