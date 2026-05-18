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

#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/SceneContainerScope.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <omni/ui/bind/Pybind.h>
#include <pybind11/stl.h>

//

#include <omni/ui/scene/bind/BindAbstractShape.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapAbstractShape(module& m)
{
    constexpr const char* abstractShapeDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractShape);

    class_<AbstractShape, AbstractItem, std::shared_ptr<AbstractShape>>(m, "AbstractShape", abstractShapeDoc)
        .def_property_readonly("gesture_payload", [](const AbstractShape& self) { return self.getGesturePayload(); },
                               OMNIUI_PYBIND_DOC_AbstractShape_getGesturePayload)
        .def("get_gesture_payload", [](const AbstractShape& self) { return self.getGesturePayload(); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_AbstractShape_getGesturePayload)
        .def("get_gesture_payload",
             [](const AbstractShape& self, GestureState state) { return self.getGesturePayload(state); },
             return_value_policy::reference, OMNIUI_PYBIND_DOC_AbstractShape_getGesturePayload01)
        .def_property("gestures", &AbstractShape::getGestures, &AbstractShape::setGestures,
                      OMNIUI_PYBIND_DOC_AbstractShape_getGestures);
}

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

std::vector<std::shared_ptr<ShapeGesture>> pythonToGestures(pybind11::handle obj)
{
    // Implicitly cast numbers into Pixel Length values:
    if (isinstance<ShapeGesture>(obj))
    {
        return std::vector<std::shared_ptr<ShapeGesture>>(1, obj.cast<std::shared_ptr<ShapeGesture>>());
    }
    else if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        std::vector<std::shared_ptr<ShapeGesture>> result;

        list pythonList = obj.cast<list>();
        result.reserve(pythonList.size());
        for (auto& item : pythonList)
        {
            if (!isinstance<ShapeGesture>(item))
            {
                throw type_error("Could not convert the list item of type " +
                                 static_cast<std::string>(pybind11::str(item.get_type())) + " to ShapeGesture");
                return {};
            }

            result.push_back(item.cast<std::shared_ptr<ShapeGesture>>());
        }

        return result;
    }

    throw type_error("The value of type " + static_cast<std::string>(pybind11::str(obj.get_type())) +
                     " can't be converted to ShapeGesture");
    return {};
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
