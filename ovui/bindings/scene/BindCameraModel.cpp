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

#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/CameraModel.h>
#include <omni/ui/scene/bind/BindCameraModel.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapCameraModel(module& m)
{
    constexpr const char* cameraModelDoc = OMNIUI_PYBIND_CLASS_DOC(CameraModel);
    static constexpr char cameraModelConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(CameraModel, CameraModel);

    class_<CameraModel, AbstractManipulatorModel, std::shared_ptr<CameraModel>>(m, "CameraModel", cameraModelDoc)
        .def(init([](object projection, object view)
                  { return std::make_shared<CameraModel>(pythonToMatrix4(projection), pythonToMatrix4(view)); }),
             cameraModelConstructorDoc)
        .def_property("projection", &CameraModel::getProjection,
                      [](CameraModel& self, handle projection) { self.setProjection(pythonToMatrix4(projection)); },
                      OMNIUI_PYBIND_DOC_CameraModel_getProjection)
        .def_property("view", &CameraModel::getView,
                      [](CameraModel& self, handle view) { self.setView(pythonToMatrix4(view)); },
                      OMNIUI_PYBIND_DOC_CameraModel_getProjection)
        /* */;
}
