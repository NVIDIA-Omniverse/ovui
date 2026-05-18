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

//

#include <pybind11/chrono.h>
#include <pybind11/stl.h>

//

#include <omni/ui/scene/AbstractGesture.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/ClickGesture.h>
#include <omni/ui/scene/DoubleClickGesture.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/ManipulatorGesture.h>
#include <omni/ui/scene/ShapeGesture.h>
#include <omni/ui/scene/bind/BindClickGesture.h>
#include <omni/ui/scene/bind/BindDoubleClickGesture.h>
#include <omni/ui/scene/bind/BindDragGesture.h>
#include <omni/ui/scene/bind/BindGestureManager.h>
#include <omni/ui/scene/bind/BindManipulatorGesture.h>
#include <omni/ui/scene/bind/BindMath.h>

using namespace pybind11;
using namespace omni::ui;

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

std::shared_ptr<PyManipulatorGesture> PyManipulatorGesture::create(pybind11::handle derivedFrom)
{
    auto ptr = std::make_shared<PyManipulatorGesture>();

    if (derivedFrom && !derivedFrom.is_none())
    {
        PyObject* pyDerivedPtr = derivedFrom.ptr();
        if (pyDerivedPtr)
        {
            // Save derived object
            ptr->m_derivedFrom = pyDerivedPtr;
        }
    }

    return ptr;
}

void PyManipulatorGesture::process()
{
    OMNIUI_PYBIND_OVERLOAD(void, ManipulatorGesture, process, process);
}

const pybind11::handle& PyManipulatorGesture::getHandle() const
{
    return m_derivedFrom;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapManipulatorGesture(module& m)
{
    constexpr const char* gestureDoc = OMNIUI_PYBIND_CLASS_DOC(ManipulatorGesture);
    static constexpr char gestureConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ManipulatorGesture, ManipulatorGesture);

    class_<ManipulatorGesture, AbstractGesture, PyManipulatorGesture, std::shared_ptr<ManipulatorGesture>>(
        m, "ManipulatorGesture", gestureDoc)
        .def("__init__",
             [](detail::value_and_holder& v_h, kwargs args)
             {
                 // We need a low-level initialization because we need the access
                 // to the derived object to be able to properly cast when
                 // processing the gesture.
                 auto create = [](handle derived, kwargs kwargs) -> std::shared_ptr<PyManipulatorGesture> {
                     OMNIUI_PYBIND_INIT(PyManipulatorGesture, derived)
                 };
                 // v_h.inst is the Python object derived from Manipulator
                 detail::initimpl::construct<
                     class_<ManipulatorGesture, PyManipulatorGesture, std::shared_ptr<ManipulatorGesture>>>(
                     v_h, create(handle{ reinterpret_cast<PyObject*>(v_h.inst) }, std::forward<kwargs>(args)),
                     Py_TYPE(v_h.inst) != v_h.type->type);
             },
             detail::is_new_style_constructor())
        .def("__repr__",
             [](const std::shared_ptr<ManipulatorGesture>& self) -> std::string { return "<ManipulatorGesture " + (self ? self->getName(): "") + ">"; })
        .def_property_readonly("sender", &ManipulatorGesture::getSender, OMNIUI_PYBIND_DOC_ManipulatorGesture_getSender)
        /**/;
}
