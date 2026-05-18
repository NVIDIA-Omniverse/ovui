/*
 * SPDX-FileCopyrightText: Copyright (c) 2023-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

// Standalone variant: carb/assert/AssertUtils.h and carb/logging/Log.h removed;
// CARB_LOG_INFO replaced with OMNIUI_LOG_INFO, CARB_ASSERT replaced with OMNIUI_ASSERT.
//
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/TransformBasis.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

/**
 * @brief Trampoline class for TransformBasis
 */
class PyTransformBasis : public TransformBasis
{
public:
    PyTransformBasis() : TransformBasis()
    {
        OMNIUI_LOG_INFO("PyTransformBasis being created");
    }

    ~PyTransformBasis() override
    {
        OMNIUI_LOG_INFO("PyTransformBasis being destroyed");
    }

    Matrix44 getMatrix() override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD(Matrix44, TransformBasis, get_matrix);
        return { 1.0 };
    }

    // Cache a pointer to the PyObject which is related to `this`
    void storePySelf(PyObject* pySelf)
    {
        OMNIUI_ASSERT(m_pySelf == nullptr, "Do not reassign pySelf");

        m_pySelf = pySelf;
    }

    // NOTE: pybind11 doesn't keep Python objects alive when only the C++ shared_ptr is alive,
    // so we need to artificially increment and decrement the internal Python ref count.
    // These functions are already (and should only be) called by Transform when a basis is set
    // or removed, and when the Transform is destroyed, tying their life cycle to an owner
    // Transform object.

    void _attachToTransform() override
    {
        OMNIUI_LOG_INFO("PyTransformBasis is attaching");

        if (m_pySelf)
        {
            gil_scoped_acquire gil;
            Py_INCREF(m_pySelf);
        }
    }

    void _detachFromTransform() override
    {
        OMNIUI_LOG_INFO("PyTransformBasis is detaching");

        if (m_pySelf)
        {
            gil_scoped_acquire gil;
            Py_DECREF(m_pySelf);
            m_pySelf = nullptr;
        }
    }

private:
    PyObject* m_pySelf = nullptr;
};

void wrapTransformBasis(module& m)
{
    class_<TransformBasis, PyTransformBasis, std::shared_ptr<TransformBasis>>(m, "TransformBasis")
        .def(
            "__init__",
            [](detail::value_and_holder& v_h, kwargs args)
            {
                // We need to use a custom creation process in order to get the
                // Python container for subclassed instances. It looks very complex,
                // but basically we are injecting the containing PyObject pointer
                // into the instance of PyTransformBasis when it gets created via
                // a lambda function supplied as an argument to pybind11's normal
                // construct function.
                auto createFn = [](handle derived, kwargs kwargs) -> std::shared_ptr<PyTransformBasis>
                {
                    using ThisType = PyTransformBasis;
                    std::shared_ptr<ThisType> result{ new ThisType() };

                    if (derived && !derived.is_none())
                    {
                        PyObject* pyDerivedPtr = derived.ptr();
                        if (pyDerivedPtr)
                        {
                            result->storePySelf(pyDerivedPtr);
                        }
                    }

                    return result;
                };

                auto handle = reinterpret_cast<PyObject*>(v_h.inst);
                detail::initimpl::construct<class_<TransformBasis, PyTransformBasis, std::shared_ptr<TransformBasis>>>(
                    v_h, createFn(handle, std::forward<kwargs>(args)), Py_TYPE(v_h.inst) != v_h.type->type);
            },
            detail::is_new_style_constructor())
        .def("get_matrix", &TransformBasis::getMatrix);
}
