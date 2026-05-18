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
#include <omni/ui/scene/AbstractItem.h>
#include <omni/ui/scene/SceneView.h>
#include <omni/ui/scene/bind/BindAbstractItem.h>
#include <omni/ui/scene/bind/BindMath.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

static object _transformSpace(const AbstractItem& self, Space fromSpace, Space toSpace, const pybind11::handle& obj)
{
    if ((isinstance<tuple>(obj) || isinstance<list>(obj)) && obj.cast<list>().size() == 3)
    {
        Vector3 point = self.transformSpace(fromSpace, toSpace, pythonToVector3(obj));
        return vector3ToPython(point);
    }

    Vector4 vector = self.transformSpace(fromSpace, toSpace, pythonToVector4(obj));
    return vector4ToPython(vector);
}

void wrapAbstractItem(module& m)
{
    class_<MouseInput>(m, "MouseInput")
        .def(init<>())
        .def_readwrite("mouse", &MouseInput::mouse)
        .def_readwrite("mouse_wheel", &MouseInput::mouseWheel)
        .def_readwrite("mouse_origin", &MouseInput::mouseOrigin)
        .def_readwrite("mouse_direction", &MouseInput::mouseDirection)
        .def_readwrite("modifiers", &MouseInput::modifiers)
        .def_readwrite("clicked", &MouseInput::clicked)
        .def_readwrite("double_clicked", &MouseInput::doubleClicked)
        .def_readwrite("released", &MouseInput::released)
        .def_readwrite("down", &MouseInput::down)
        /**/;

    constexpr const char* abstractItemDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractItem);

    class_<AbstractItem, std::shared_ptr<AbstractItem>>(m, "AbstractItem", abstractItemDoc)
        .def("destroy", &AbstractItem::destroy)
        .def("transform_space", &_transformSpace, OMNIUI_PYBIND_DOC_AbstractItem_transformSpace)
        .def("compute_visibility", &AbstractItem::computeVisibility, OMNIUI_PYBIND_DOC_AbstractItem_computeVisibility)
        .def_property_readonly("scene_view", &AbstractItem::getSceneView, OMNIUI_PYBIND_DOC_AbstractItem_sceneView)
        .def_property(
            "visible", &AbstractItem::isVisible, &AbstractItem::setVisible, OMNIUI_PYBIND_DOC_AbstractItem_visible)
        /**/;
}
