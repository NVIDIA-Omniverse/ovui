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
#include <omni/ui/scene/Transform.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/scene/bind/BindTransform.h>


using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapTransform(module& m)
{
    constexpr const char* transformDoc = OMNIUI_PYBIND_CLASS_DOC(Transform);
    static constexpr char transformConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Transform, Transform);

    auto transform = class_<Transform, AbstractContainer, std::shared_ptr<Transform>>(m, "Transform", transformDoc);

    enum_<Transform::LookAt>(transform, "LookAt")
        .value("NONE", Transform::LookAt::eNone)
        .value("CAMERA", Transform::LookAt::eCamera)
        /**/;

    transform.def(init([](kwargs kwargs) { OMNIUI_PYBIND_INIT(Transform) }), transformConstructorDoc)
        .def(init([](object transform, kwargs kwargs) {
            const auto xform = pythonToMatrix4(transform);
            OMNIUI_PYBIND_INIT(Transform, xform)
        }), transformConstructorDoc)
        .def_property("transform", &Transform::getTransform,
                      [](Transform& self, const pybind11::handle& matrix) { self.setTransform(pythonToMatrix4(matrix)); },
                      OMNIUI_PYBIND_DOC_Transform_transform)
        .def_property("scale_to", &Transform::getScaleTo, &Transform::setScaleTo, OMNIUI_PYBIND_DOC_Transform_scaleTo)
        .def_property("look_at", &Transform::getLookAt, &Transform::setLookAt, OMNIUI_PYBIND_DOC_Transform_lookAt)
        .def_property("basis", &Transform::getBasis, &Transform::setBasis, OMNIUI_PYBIND_DOC_Transform_basis)
        /**/;
}
