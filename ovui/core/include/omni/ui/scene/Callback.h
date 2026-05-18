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

#pragma once

#include "../Api.h"

#include <boost/preprocessor.hpp>

#include <algorithm>
#include <functional>
#include <utility>
#include <vector>

// Receives: 3, 1, (int, char, float)
// Generates: char arg1
#define OMNIUI_ARGUMENT_NAME(z, n, seq) BOOST_PP_TUPLE_ELEM(n, seq) arg##n

// Receives: int, char, float
// Generates: (int arg0, char arg1, float arg2)
#define OMNIUI_FUNCTION_ARGS(...)                                                                                      \
    BOOST_PP_IF(                                                                                                       \
        BOOST_PP_IS_EMPTY(__VA_ARGS__), (),                                                                            \
        (BOOST_PP_ENUM(BOOST_PP_TUPLE_SIZE(BOOST_PP_VARIADIC_TO_TUPLE(__VA_ARGS__)), OMNIUI_ARGUMENT_NAME,             \
                       BOOST_PP_IF(BOOST_PP_IS_EMPTY(__VA_ARGS__), (error), BOOST_PP_VARIADIC_TO_TUPLE(__VA_ARGS__)))))

// Receives: int, char, float
// Generates: (arg0, arg1, arg2)
#define OMNIUI_CALL_ARGS(...)                                                                                          \
    BOOST_PP_IF(BOOST_PP_IS_EMPTY(__VA_ARGS__), (), (BOOST_PP_ENUM_PARAMS(BOOST_PP_VARIADIC_SIZE(__VA_ARGS__), arg)))

#define OMNIUI_VA_TEMPLATE(type, ...) type BOOST_PP_COMMA_IF(BOOST_PP_NOT(BOOST_PP_IS_EMPTY(__VA_ARGS__))) __VA_ARGS__

template <typename T>
inline T __return_type_init()
{
    return static_cast<T>(NULL);
}
template <>
inline std::string __return_type_init<std::string>()
{
    return std::string("");
}

/**
 * @brief This is the macro to define a widget callback. It creates the callback holder and four methods: set, on
 * changed, has and call.
 *
 * Using: OMNIUI_CALLBACK(MouseReleased, void, float, float, int32_t, omni::ui::KeyboardModifierFlags);
 *
 * Expands to:
 *     private:
 *         Callback<void, float, float, int32_t, omni::ui::KeyboardModifierFlags> m_MouseReleasedCallback{ this };
 *     public:
 *         virtual void setMouseReleasedFn(
 *             std::function<void(float, float, int32_t, omni::ui::KeyboardModifierFlags)> fn)
 *         {
 *             m_MouseReleasedCallback.set(std::move(fn));
 *         }
 *         virtual void setMouseReleasedChangedFn(std::function<void()> fn)
 *         {
 *             m_MouseReleasedCallback.setOnChanged(std::move(fn));
 *         }
 *         void callMouseReleasedFn(float arg0, float arg1, int32_t arg2, omni::ui::KeyboardModifierFlags arg3)
 *         {
 *             if (this->hasMouseReleasedFn())
 *             {
 *                 m_MouseReleasedCallback(arg0, arg1, arg2, arg3);
 *             }
 *             return static_cast<void>(0);
 *         }
 *         bool hasMouseReleasedFn() const
 *         {
 *             return m_MouseReleasedCallback;
 *         }
 */
#define OMNIUI_CALLBACK(name, type, ...)                                                                               \
private:                                                                                                               \
    Callback<CallbackHelperBase, OMNIUI_VA_TEMPLATE(type, __VA_ARGS__)> m_##name##Callback{ this };                    \
                                                                                                                       \
public:                                                                                                                \
    virtual void set##name##Fn(std::function<type(__VA_ARGS__)> fn)                                                    \
    {                                                                                                                  \
        m_##name##Callback.set(std::move(fn));                                                                         \
    }                                                                                                                  \
                                                                                                                       \
    virtual void set##name##ChangedFn(std::function<void()> fn)                                                        \
    {                                                                                                                  \
        m_##name##Callback.setOnChanged(std::move(fn));                                                                \
    }                                                                                                                  \
    type call##name##Fn OMNIUI_FUNCTION_ARGS(__VA_ARGS__)                                                              \
    {                                                                                                                  \
        if (this->has##name##Fn())                                                                                     \
        {                                                                                                              \
            return m_##name##Callback OMNIUI_CALL_ARGS(__VA_ARGS__);                                                   \
        }                                                                                                              \
                                                                                                                       \
        return __return_type_init<type>();                                                                             \
    }                                                                                                                  \
                                                                                                                       \
    bool has##name##Fn() const                                                                                         \
    {                                                                                                                  \
        return m_##name##Callback;                                                                                     \
    }

OMNIUI_NAMESPACE_OPEN_SCOPE

template <typename W>
class CallbackBase;

/**
 * @brief Base class for the objects that should automatically clean up the callbacks. It collects all the callbacks
 * created with OMNIUI_CALLBACK and is able to clean all of them. We use it to destroy the callbacks if the parent
 * object is destroyed, and it helps to break circular references created by pybind11 because pybind11 can't use weak
 * pointers.
 */
template <typename W>
class OMNIUI_CLASS_API CallbackHelper
{
public:
    using CallbackHelperBase = W;

    void initializeCallback(CallbackBase<W>* callback)
    {
        m_callbacks.push_back(callback);
    }

    void disposeCallback(CallbackBase<W>* callback)
    {
        auto found = std::find(m_callbacks.begin(), m_callbacks.end(), callback);
        if (found != m_callbacks.end())
        {
            m_callbacks.erase(found);
        }
    }

    void destroyCallbacks()
    {
        if (!m_callbacksValid)
        {
            return;
        }

        m_callbacksValid = false;

        for (auto& callback : m_callbacks)
        {
            callback->destroy();
        }
    }

private:
    std::vector<CallbackBase<W>*> m_callbacks;
    bool m_callbacksValid = true;
};

/**
 * @brief Base object for callback containers.
 */
template <typename W>
class OMNIUI_CLASS_API CallbackBase
{
public:
    CallbackBase(CallbackHelper<W>* widget) : m_parent{ widget }
    {
        if (m_parent)
        {
            m_parent->initializeCallback(this);
        }
    }

    virtual ~CallbackBase()
    {
        if (m_parent)
        {
            m_parent->disposeCallback(this);
        }
    }

    virtual operator bool() const = 0;
    virtual void destroy() = 0;

private:
    CallbackHelper<W>* m_parent;
};

/**
 * @brief Callback containers that is used with OMNIUI_CALLBACK macro. It keeps only one function, but it's possible to
 * set up another function called when the main one is replaced.
 */
template <typename W, typename T, typename... Args>
class Callback : public CallbackBase<W>
{
public:
    using CallbackType = std::function<T(Args...)>;

    Callback(CallbackHelper<W>* widget) : CallbackBase<W>{ widget }
    {
    }

    void set(std::function<T(Args...)> fn)
    {
        m_callback = std::move(fn);
        if (m_onChanged)
        {
            m_onChanged();
        }
    }

    void setOnChanged(std::function<void()> fn)
    {
        m_onChanged = std::move(fn);
    }

    T operator()(Args... args)
    {
        return m_callback(args...);
    }

    operator bool() const override
    {
        return static_cast<bool>(m_callback);
    }

    void destroy() override
    {
        m_callback = {};
        m_onChanged = {};
    }

private:
    CallbackType m_callback;
    std::function<void()> m_onChanged;
};

/**
 * @brief Callback containers that is used with OMNIUI_PROPERTY macro.
 */
template <typename W, typename... Args>
class PropertyCallback : public CallbackBase<W>
{
public:
    PropertyCallback(CallbackHelper<W>* widget) : CallbackBase<W>{ widget }
    {
    }

    void add(std::function<void(Args...)> fn)
    {
        m_callbacks.emplace_back(std::move(fn));
    }

    void operator()(Args... args)
    {
        for (auto const& f : m_callbacks)
        {
            f(args...);
        }
    }

    operator bool() const override
    {
        return !m_callbacks.empty();
    }

    void destroy() override
    {
        m_callbacks.clear();
    }

private:
    std::vector<std::function<void(Args...)>> m_callbacks;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
