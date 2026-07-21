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

#include <pybind11/stl.h>

//

#include <omni/ui/scene/Manipulator.h>
#include <omni/ui/scene/ManipulatorGesture.h>
#include <omni/ui/scene/bind/BindAbstractManipulatorModel.h>
#include <omni/ui/scene/bind/BindManipulator.h>
#include <omni/ui/scene/bind/BindManipulatorGesture.h>
#include <omni/ui/scene/bind/BindMath.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The trampoline class for Manipulator
 */
class PyManipulator : public Manipulator
{
public:
    using This = PyManipulator;

    template <typename... Args>
    static std::shared_ptr<This> create(pybind11::handle derivedFrom, Args&&... args)
    {
        std::shared_ptr<This> ptr{ new This{ std::forward<Args>(args)... }, [](This* ptr)
                                   {
                                       // Calling destroy to decrease reference counts
                                       gil_scoped_acquire gil;
                                       ptr->destroy();
                                       delete ptr;
                                   } };

        if (derivedFrom && !derivedFrom.is_none())
        {
            PyObject* pyDerivedPtr = derivedFrom.ptr();
            if (pyDerivedPtr)
            {
                // Increase the reference counts to protect the python object
                // from destroying
                gil_scoped_acquire gil;
                Py_INCREF(pyDerivedPtr);
                ptr->m_pyDerivedPtr = pyDerivedPtr;
            }
        }

        // Add to parent
        SceneContainerStack::instance().addChildToTop(std::static_pointer_cast<AbstractItem>(ptr));
        return ptr;
    }

    void destroy() override
    {
        if (m_pyDerivedPtr)
        {
            gil_scoped_acquire gil;
            Py_DECREF(m_pyDerivedPtr);
            m_pyDerivedPtr = nullptr;
        }

        Manipulator::destroy();
    }

    void onBuild() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, Manipulator, onBuild, on_build);
    }

    void onModelUpdated(const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>& item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, Manipulator, Manipulator::onModelUpdated, on_model_updated, item);
    }

    void _processGesture(object pyType,
                         GestureState state,
                         const std::shared_ptr<AbstractGesture::GesturePayload>& gesturePayload)
    {
        if (!gesturePayload)
        {
            return;
        }

        for (auto& gesture : getGestures())
        {
            auto castedGesture = std::dynamic_pointer_cast<PyManipulatorGesture>(gesture);
            if (!castedGesture)
            {
                continue;
            }

            try
            {
                if (!isinstance(castedGesture->getHandle(), pyType))
                {
                    continue;
                }
            }
            catch (const error_already_set&)
            {
                continue;
            }

            gesture->_processWithGesturePayload(this, state, gesturePayload);
        }
    }

    PyManipulator() : Manipulator{}
    {
    }

private:
    // The object that is derived from this class.
    PyObject* m_pyDerivedPtr = nullptr;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapManipulator(module& m)
{
    constexpr const char* manipulatorDoc = OMNIUI_PYBIND_CLASS_DOC(Manipulator);
    static constexpr char manipulatorConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(Manipulator, Manipulator);
    static constexpr char process[] = "Process the ManipulatorGestures that can be casted to the given type";

    class_<Manipulator, AbstractContainer, PyManipulator, std::shared_ptr<Manipulator>>(m, "Manipulator", manipulatorDoc)
        .def("__init__",
             [](detail::value_and_holder& v_h, kwargs args)
             {
                 // We need a low-level initialization for the case there is a
                 // python class derived from Manipulator. If such an object is
                 // created and not assigned to a variable, it will be
                 // immediately removed because Python doesn't know we keep the
                 // base object in C++. To avoid it, we need to increase the
                 // reference counts to protect the python object from
                 // destroying.
                 auto create = [](handle derived, kwargs kwargs) -> std::shared_ptr<PyManipulator> {
                     OMNIUI_PYBIND_INIT(PyManipulator, derived)
                 };
                 // v_h.inst is the Python object derived from Manipulator
                 detail::initimpl::construct<class_<Manipulator, PyManipulator, std::shared_ptr<Manipulator>>>(
                     v_h, create(handle{ reinterpret_cast<PyObject*>(v_h.inst) }, std::forward<kwargs>(args)),
                     Py_TYPE(v_h.inst) != v_h.type->type);
             },
             detail::is_new_style_constructor())
        .def("invalidate", &Manipulator::invalidate, OMNIUI_PYBIND_DOC_Manipulator_invalidate)
        .def("on_build", &Manipulator::onBuild, OMNIUI_PYBIND_DOC_Manipulator_OnBuild)
        .def("on_model_updated", &Manipulator::onModelUpdated, OMNIUI_PYBIND_DOC_ManipulatorModelHelper_onModelUpdated)
        .def("_process_gesture",
             [](PyManipulator& self, object pyType, GestureState state,
                const std::shared_ptr<AbstractGesture::GesturePayload>& gesturePayload)
             { self._processGesture(pyType, state, gesturePayload); },
             process)
        .def_property(
            "model", &Manipulator::getModel, &Manipulator::setModel, OMNIUI_PYBIND_DOC_ManipulatorModelHelper_getModel)
        .def_property(
            "gestures", &Manipulator::getGestures, &Manipulator::setGestures, OMNIUI_PYBIND_DOC_Manipulator_getGestures)
        .OMNIUI_PYBIND_DEF_CALLBACK(on_build, Manipulator, OnBuild)
        /**/;
}
