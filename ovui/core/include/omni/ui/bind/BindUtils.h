/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

// Logging: use OMNIUI_LOG_* macros from the platform abstraction layer.
// These resolve to the backend-specific logging implementation via the adapter layer.
#include <omni/ui/platform/Log.h>
#include <omni/ui/platform/Assert.h>

#ifndef OMNIUI_MAYBE_UNUSED
#define OMNIUI_MAYBE_UNUSED [[maybe_unused]]
#endif

#include <omni/ui/Api.h>
#include <omni/ui/bind/BindStyleContainer.h>
#include <omni/ui/bind/Pybind.h>

#include <functional>
#include <string>


#define OMNIUI_BIND(x)                                                                                                 \
    void wrap##x(pybind11::module& m);                                                                                 \
    wrap##x(m)

// Set of macros for python constructors. We need to provide a way to initialize all the properties in the Python
// constructor. And to do it we need to list all the properties from all the derived classes. To do it shortly, we use
// the following pattern in the Python init lambda:
//
//    OMNIUI_PYBIND_INIT(className)
//
// It expands to the Python constructor. Here are the implementations of the macros to do it.

// Expands to the code that constructs the C++ object and its properties from pybind11 init.
//
// ovui provides a property system. And this macro OMNIUI_PYBIND_INIT is the part of the property system. It's
// possible to set any property in the constructor of the Python object. It gives the ability to have declarative-like
// Python code. And we believe it allows the Python users creating complex widgets with straightforward code. The
// simplest example looks like this:
//
//   ui.Image(
//       image_source,
//       height=160,
//       alignment=ui.Alignment.CENTER,
//       style={"border_radius": 8, "margin": 20},
//   )
//
// We need to make sure that it's possible to initialize the properties of base class in the python constructor. It
// seems pybind11 doesn't have a way to call the python constructor of the base object. It means that the Python
// constructor of child class needs to have the code that initializes properties of the base class. To avoid duplicating
// of actual code, we put the initialization of properties to macros. And it looks like this (it's simplified):
//
//   #define OMNIUI_PYBIND_INIT_Widget
//       OMNIUI_PYBIND_INIT_CALL(width, setWidth, toLength)
//       OMNIUI_PYBIND_INIT_CALL(height, setHeight, toLength)
//       OMNIUI_PYBIND_INIT_CAST(name, setName, std::string)
//
// The initialization of child object looks like this (also simplified):
//
//   #define OMNIUI_PYBIND_INIT_Button
//       OMNIUI_PYBIND_INIT_Widget
//       OMNIUI_PYBIND_INIT_CAST(text, setText, std::string)
//
// And to construct the python object, we can use the macro like this (also simplified):
//
//   #define OMNIUI_PYBIND_INIT(className, ...)
//       auto result = className::create(__VA_ARGS__);
//       OMNIUI_PYBIND_INIT_##className
//
// We use className to create the object and to call the correct macro. Thus, the pybind11 constructor looks like this
// for all the widgets:
//
//   .def(init([](std::string title, kwargs kwargs) { OMNIUI_PYBIND_INIT(Button, title) }))
//
#define OMNIUI_PYBIND_INIT(className, ...)                                                                             \
    std::shared_ptr<className> result;                                                                                 \
    {                                                                                                                  \
        pybind11::gil_scoped_release gil;                                                                              \
        result = className::create(__VA_ARGS__);                                                                       \
    }                                                                                                                  \
    if (result)                                                                                                        \
    {                                                                                                                  \
        OMNIUI_PYBIND_INIT_BEGIN                                                                                       \
            OMNIUI_PYBIND_INIT_##className                                                                             \
        OMNIUI_PYBIND_INIT_END                                                                                         \
    }                                                                                                                  \
    return result;

#define OMNIUI_PYBIND_INIT_WITH_DESTRUCTOR(className, destructor, ...)                                                 \
    std::shared_ptr<className> result;                                                                                 \
    {                                                                                                                  \
        pybind11::gil_scoped_release gil;                                                                              \
        result = className::createWithDestructor((destructor), ##__VA_ARGS__);                                         \
    }                                                                                                                  \
    if (result)                                                                                                        \
    {                                                                                                                  \
        OMNIUI_PYBIND_INIT_BEGIN                                                                                       \
            OMNIUI_PYBIND_INIT_##className                                                                             \
        OMNIUI_PYBIND_INIT_END                                                                                         \
    }                                                                                                                  \
    return result;

// The header of the code that constructs the C++ object and its properties from pybind11 init. It should only be used
// by OMNIUI_PYBIND_INIT
#define OMNIUI_PYBIND_INIT_BEGIN                                                                                       \
    for (auto item : kwargs)                                                                                           \
    {                                                                                                                  \
        auto name = item.first.cast<std::string>();                                                                    \
        OMNIUI_MAYBE_UNUSED const auto& value = item.second;                                                             \
                                                                                                                       \
        if (0)                                                                                                         \
        {                                                                                                              \
        }

// The footer of the code that constructs the C++ object and its properties from pybind11 init. It should only be used
// by OMNIUI_PYBIND_INIT
#ifdef OMNIUI_PYBIND_STRICT_KWARGS
#define OMNIUI_PYBIND_INIT_END                                                                                         \
    else                                                                                                               \
    {                                                                                                                  \
        throw pybind11::key_error(std::string("Unsupported omni.ui keyword argument: ") + name);                       \
    }                                                                                                                  \
    }
#else
#define OMNIUI_PYBIND_INIT_END }
#endif

// Initialize the property using the pybind11 cast to convert pybind11 handle to the type we need.
#define OMNIUI_PYBIND_INIT_CAST(NAME, METHOD, CASTTO)                                                                  \
    else if (name == #NAME)                                                                                            \
    {                                                                                                                  \
        result->METHOD(value.cast<CASTTO>());                                                                          \
    }

// Initialize the property using the additional function to convert pybind11 handle to the type we need.
#define OMNIUI_PYBIND_INIT_CALL(NAME, METHOD, CALL)                                                                    \
    else if (name == #NAME)                                                                                            \
    {                                                                                                                  \
        result->METHOD(CALL(value));                                                                                   \
    }

// Initialize the property with the function that is not a method.
#define OMNIUI_PYBIND_INIT_EXT_CALL(NAME, FUNCTION)                                                                    \
    else if (name == #NAME)                                                                                            \
    {                                                                                                                  \
        FUNCTION(result, value);                                                                                       \
    }

// Initialize the property of the function type.
#define OMNIUI_PYBIND_INIT_CALLBACK(NAME, METHOD, CASTTO)                                                              \
    else if (name == #NAME)                                                                                            \
    {                                                                                                                  \
        result->METHOD(wrapPythonCallback(value.cast<std::function<CASTTO>>()));                                       \
    }

// Initialize widget style from Python dictionary.
#define OMNIUI_PYBIND_INIT_STYLES                                                                                      \
    else if (name == "style")                                                                                          \
    {                                                                                                                  \
        setWidgetStyle(*result.get(), value);                                                                          \
    }

// Extended version of the init macros.
// clang-format off
#define OMNIUI_PYBIND_INIT_EX(className, ...)                                                                          \
    OMNIUI_PYBIND_INIT_EX_BEFORE_##className(__VA_ARGS__)                                                              \
    OMNIUI_PYBIND_INIT_EX_CREATE_##className(__VA_ARGS__)                                                              \
    OMNIUI_PYBIND_INIT_EX_AFTER_##className(__VA_ARGS__)                                                               \
    OMNIUI_PYBIND_INIT_EX_BEGIN_KWARGS_##className(__VA_ARGS__)                                                        \
    OMNIUI_PYBIND_INIT_EX_KWARGS_##className(__VA_ARGS__)                                                              \
    OMNIUI_PYBIND_INIT_EX_END_KWARGS_##className(__VA_ARGS__)                                                          \
    OMNIUI_PYBIND_INIT_EX_FINAL_##className(__VA_ARGS__)                                                               \
    return result;
// clang-format on

// Expands to the body of the method that is abstract in the base class. This method redirects the call to python
// bindings.
#define OMNIUI_PYBIND_ABSTRACT_METHOD(TYPE, PARENT, PYNAME)                                                            \
    try                                                                                                                \
    {                                                                                                                  \
        PYBIND11_OVERLOAD_PURE_NAME(TYPE, PARENT, #PYNAME, 0);                                                         \
    }                                                                                                                  \
    catch (const pybind11::error_already_set& e)                                                                       \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }                                                                                                                  \
    catch (const std::runtime_error& e)                                                                                \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }

#define OMNIUI_PYBIND_ABSTRACT_METHOD_VA(TYPE, PARENT, PYNAME, ...)                                                    \
    try                                                                                                                \
    {                                                                                                                  \
        PYBIND11_OVERLOAD_PURE_NAME(TYPE, PARENT, #PYNAME, 0, __VA_ARGS__);                                            \
    }                                                                                                                  \
    catch (const pybind11::error_already_set& e)                                                                       \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }                                                                                                                  \
    catch (const std::runtime_error& e)                                                                                \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }

#define OMNIUI_PYBIND_OVERLOAD(TYPE, PARENT, CNAME, PYNAME)                                                            \
    try                                                                                                                \
    {                                                                                                                  \
        PYBIND11_OVERLOAD_NAME(TYPE, PARENT, #PYNAME, CNAME);                                                          \
    }                                                                                                                  \
    catch (const pybind11::error_already_set& e)                                                                       \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }                                                                                                                  \
    catch (const std::runtime_error& e)                                                                                \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }

#define OMNIUI_PYBIND_OVERLOAD_VA(TYPE, PARENT, CNAME, PYNAME, ...)                                                    \
    try                                                                                                                \
    {                                                                                                                  \
        PYBIND11_OVERLOAD_INT(PYBIND11_TYPE(TYPE), PYBIND11_TYPE(PARENT), #PYNAME, __VA_ARGS__);                       \
    }                                                                                                                  \
    catch (const pybind11::error_already_set& e)                                                                       \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }                                                                                                                  \
    catch (const std::runtime_error& e)                                                                                \
    {                                                                                                                  \
        OMNIUI_LOG_ERROR("%s", e.what());                                                                                \
    }                                                                                                                  \
    return CNAME(__VA_ARGS__);

#define OMNIUI_PYBIND_CLASS_DOC(className) OMNIUI_PYBIND_DOC_##className

#define OMNIUI_PYBIND_CONSTRUCTOR_DOC(className, constructor)                                                          \
    BOOST_PP_CAT(OMNIUI_PYBIND_DOC_, BOOST_PP_CAT(className, BOOST_PP_CAT(_, constructor)))                            \
    "\n    `kwargs : dict`\n        See below\n\n### Keyword Arguments:\n" OMNIUI_PYBIND_KWARGS_DOC_##className

#define OMNIUI_PYBIND_DEF_CALLBACK(python_name, cpp_class, cpp_name)                                                   \
    def("set_" #python_name "_fn", wrapCallbackSetter(&cpp_class::set##cpp_name##Fn), arg("fn"),                       \
        OMNIUI_PYBIND_DOC_##cpp_class##_##cpp_name)                                                                    \
        .def("has_" #python_name "_fn", &cpp_class::has##cpp_name##Fn, OMNIUI_PYBIND_DOC_##cpp_class##_##cpp_name)     \
        .def("call_" #python_name "_fn", &cpp_class::call##cpp_name##Fn, OMNIUI_PYBIND_DOC_##cpp_class##_##cpp_name)

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * Assuming std::function will call into python code this function makes it safe.
 * It wraps it into try/catch, acquires GIL lock and log errors.
 */
template <typename ReturnT, typename... ArgsT>
ReturnT callPythonCodeSafe(const std::function<ReturnT(ArgsT...)>& fn, ArgsT... args)
{
    using namespace pybind11;

    try
    {
        if (fn)
        {
            gil_scoped_acquire gilLock;
            return fn(args...);
        }
    }
    catch (const error_already_set& e)
    {
        OMNIUI_LOG_ERROR("%s", e.what());
    }
    catch (const std::runtime_error& e)
    {
        OMNIUI_LOG_ERROR("%s", e.what());
    }

    return ReturnT();
}

// This is deprecated function, use the one below instead.
template <typename ReturnT, typename... Args>
auto wrapPythonCallback(const std::function<ReturnT(Args...)>& c) -> std::function<ReturnT(Args...)>
{
    return [=](Args... args) -> ReturnT { return callPythonCodeSafe<ReturnT, Args...>(c, args...); };
}

template <typename ReturnT, typename... Args>
std::function<ReturnT(Args...)> wrapPythonCallback(std::function<ReturnT(Args...)>&& c)
{
    return [c{ std::forward<std::function<ReturnT(Args...)>>(c) }](Args... args) -> ReturnT
    { return callPythonCodeSafe<ReturnT, Args...>(c, args...); };
}

/**
 * @brief Should be used when binding the callback setter, and it will lock GIL when calling the python callback.
 */
template <typename ClassT, typename R, typename... Args>
auto wrapCallbackSetter(void (ClassT::*MethodT)(std::function<R(Args...)>))
{
    return [MethodT](ClassT& self, std::function<R(Args...)> fn)
    {
        if (!fn)
        {
            // Set with an empty std::function
            (self.*MethodT)(std::function<R(Args...)>{});
        }
        else
        {
            (self.*MethodT)(wrapPythonCallback(std::move(fn)));
        }
    };
}

/**
 * @brief Convert pybind11::args to vector
 */
template <typename T, typename U = T>
std::vector<T> argsToVector(pybind11::args args)
{
    std::vector<T> result;
    // TODO: reserve
    for (const auto& it : args)
    {
        if (pybind11::isinstance<U>(it))
        {
            result.push_back(it.cast<T>());
        }
        else
        {
            OMNIUI_LOG_WARN("ovui Args: argument has wrong type");
        }
    }

    return result;
}

#define OMNIUI_PROTECT_PYBIND11_OBJECT(className, pythonClassName)                                                     \
    /* Storing shared_ptrs to Python-derived instances for later execution causes virtual functions to fail if the */  \
    /* Python instance has subsequently been destroyed. This is the workaround described in */                         \
    /* https://github.com/pybind/pybind11/issues/1546 */                                                               \
    namespace pybind11                                                                                                 \
    {                                                                                                                  \
    namespace detail                                                                                                   \
    {                                                                                                                  \
                                                                                                                       \
    template <>                                                                                                        \
    class type_caster<std::shared_ptr<className>>                                                                      \
    {                                                                                                                  \
        PYBIND11_TYPE_CASTER(std::shared_ptr<className>, _(#pythonClassName));                                         \
                                                                                                                       \
        using BaseCaster = copyable_holder_caster<className, std::shared_ptr<className>>;                              \
                                                                                                                       \
        bool load(pybind11::handle src, bool b)                                                                        \
        {                                                                                                              \
            BaseCaster bc;                                                                                             \
            bool success = bc.load(src, b);                                                                            \
            if (!success)                                                                                              \
            {                                                                                                          \
                return false;                                                                                          \
            }                                                                                                          \
                                                                                                                       \
            auto py_obj = pybind11::reinterpret_borrow<pybind11::object>(src);                                         \
            auto base_ptr = static_cast<std::shared_ptr<className>>(bc);                                               \
                                                                                                                       \
            /* Construct a shared_ptr to the py::object */                                                             \
            auto py_obj_ptr = std::shared_ptr<object>{ new object{ py_obj }, [](object* py_object_ptr)                 \
                                                       {                                                               \
                                                           /* It's possible that when the shared_ptr dies we won't */  \
                                                           /* have the gil (if the last holder is in a non-Python */   \
                                                           /* thread, so we make sure to acquire it in the deleter. */ \
                                                           gil_scoped_acquire gil;                                     \
                                                           delete py_object_ptr;                                       \
                                                       } };                                                            \
                                                                                                                       \
            value = std::shared_ptr<className>(py_obj_ptr, base_ptr.get());                                            \
            return true;                                                                                               \
        }                                                                                                              \
                                                                                                                       \
        static handle cast(std::shared_ptr<className> base, return_value_policy rvp, handle h)                         \
        {                                                                                                              \
            return BaseCaster::cast(base, rvp, h);                                                                     \
        }                                                                                                              \
    };                                                                                                                 \
                                                                                                                       \
    template <>                                                                                                        \
    struct is_holder_type<className, std::shared_ptr<className>> : std::true_type                                      \
    {                                                                                                                  \
    };                                                                                                                 \
    }                                                                                                                  \
    }

OMNIUI_NAMESPACE_CLOSE_SCOPE
