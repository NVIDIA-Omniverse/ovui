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

#include "Api.h"
#include "Profile.h"

#include <boost/preprocessor.hpp>

#include <functional>
#include <utility>

/**
 * @brief Defines and declares a property in the class.
 *
 * Example:
 *    OMNIUI_PROPERTY(float, height,
 *        [PROTECTED],
 *        [READ, getHeight],
 *        [READ_VALUE, getHeightByValue],
 *        [WRITE, setHeight],
 *        [DEFAULT, 0.0f],
 *        [NOTIFY, onHeightChanged])
 *
 * Usage:
 *         OMNIUI_PROPERTY(
 *             Length, height,
 *             DEFAULT, Fraction{ 1.0f },
 *             READ, getHeight,
 *             WRITE, setHeight,
 *             PROTECTED,
 *             NOTIFY, _setHeightChangedFn);
 *
 * Expands to:
 *     private:
 *         Length m_height = Fraction{ 1.0f };
 *         PropertyCallback<Length const&> m__setHeightChangedFnCallbacks{ this };
 *     public:
 *         virtual Length const& getHeight() const
 *         {
 *             return m_height;
 *         }
 *     public:
 *         virtual void setHeight(Length const& v)
 *         {
 *             if (!checkIfEqual(m_height, v))
 *             {
 *                 m_height = v;
 *                 m__setHeightChangedFnCallbacks(v);
 *             }
 *         }
 *     protected:
 *         virtual void _setHeightChangedFn(std::function<void(Length const&)> f)
 *         {
 *              if (f)
 *              {
 *                  m__setHeightChangedFnCallbacks.add(std::move(f));
 *              }
 *              else
 *              {
 *                  m__setHeightChangedFnCallbacks.destroy();
 *              }
 *         }
 *     public:
 *
 * Everything on the right side of PROTECTED keyword will go to the protected section.
 *
 * The difference between READ and READ_VALUE is that READ returns const reference, READ_VALUE returns value.
 *
 * TODO: Callbacks are executed right on the time the value is changed. It would be better to accumulate them and
 * execute once altogether. The question: at which point we need to execute them?
 */
#define OMNIUI_PROPERTY(type, name, ...) OMNIUI_PROPERTY_DEFINE(type, name, BOOST_PP_VARIADIC_TO_SEQ(__VA_ARGS__)(END))

// Defines a private member variable and public members
#define OMNIUI_PROPERTY_DEFINE(type, name, arguments)                                                                  \
    OMNIUI_PROPERTY_DEFINE_VAR(                                                                                        \
        type, name, OMNIUI_PROPERTY_FIND_DEFAULT(arguments), OMNIUI_PROPERTY_FIND_NOTIFY(arguments), arguments)        \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PUBLIC_, BOOST_PP_SEQ_ELEM(0, arguments))                                             \
    (type, name, OMNIUI_PROPERTY_FIND_NOTIFY(arguments), arguments) public:

// Expands to
//    private:
//        type m_name [= default];
#define OMNIUI_PROPERTY_DEFINE_VAR(type, name, default, notify, arguments)                                             \
private:                                                                                                               \
    type OMNI_PROPERTY_NAME(name) OMNIUI_PROPERTY_DEFAULT(default);                                                    \
    OMNIUI_PROPERTY_DEFINE_CALLBACKS(type, notify)

// Expands to `m_name`
#define OMNI_PROPERTY_NAME(name) BOOST_PP_CAT(m_, name)
#define OMNI_PROPERTY_CALLBACK_NAME(...) BOOST_PP_CAT(BOOST_PP_CAT(m_, __VA_ARGS__), Callbacks)

// If something is passed, expands to `= args`, otherwise expands to empty
#define OMNIUI_PROPERTY_DEFAULT(...) BOOST_PP_IF(BOOST_PP_IS_EMPTY(__VA_ARGS__), BOOST_PP_EMPTY(), = __VA_ARGS__)

#define OMNIUI_PROPERTY_DEFINE_CALLBACK_EMPTY(type, ...) BOOST_PP_EMPTY()
#define OMNIUI_PROPERTY_DEFINE_CALLBACK_VAR(type, ...)                                                                 \
    PropertyCallback<CallbackHelperBase, type const&> OMNI_PROPERTY_CALLBACK_NAME(__VA_ARGS__){ this };
#define OMNIUI_PROPERTY_DEFINE_CALLBACKS(type, ...)                                                                    \
    BOOST_PP_IF(                                                                                                       \
        BOOST_PP_IS_EMPTY(__VA_ARGS__), OMNIUI_PROPERTY_DEFINE_CALLBACK_EMPTY, OMNIUI_PROPERTY_DEFINE_CALLBACK_VAR)    \
    (type, __VA_ARGS__)

#define OMNIUI_PROPERTY_CALLBACK_CODE(type, name, ...)                                                                 \
    BOOST_PP_IF(BOOST_PP_IS_EMPTY(__VA_ARGS__), BOOST_PP_EMPTY(), OMNI_PROPERTY_CALLBACK_NAME(__VA_ARGS__)(v);)

// It works like a chain. For example we have arguments like this: (READ)(getHeight)(WRITE)(setHeight)(PROTECTED).
// It works with getHeight and calls OMNIUI_PROPERTY_PUBLIC_*WRITE* with arguments (WRITE)(setHeight)(PROTECTED).
// The called macro is doing the same.
/* Common macro to expand all other property-get macros */
#define OMNIUI_PROPERTY_DECLARE_GETTER(scope, getDeclaration, qual_type, type, name, notify, arguments)                \
scope:                                                                                                                 \
    virtual qual_type BOOST_PP_SEQ_ELEM(1, arguments)() const                                                          \
    getDeclaration                                                                                                     \
    /* Call the proper macro for the next argument */                                                                  \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PUBLIC_, BOOST_PP_SEQ_ELEM(2, arguments))                                             \
    (type, name, notify, BOOST_PP_SEQ_REST_N(2, arguments))

/* READ key, declare the virtual function to return by const reference */
#define OMNIUI_PROPERTY_PUBLIC_READ(type, name, notify, arguments)                                                     \
    OMNIUI_PROPERTY_DECLARE_GETTER(public,                                                                             \
                                   {return OMNI_PROPERTY_NAME(name);},                                                 \
                                   type const&,                                                                        \
                                   type, name, notify, arguments)


#define OMNIUI_PROPERTY_PROTECTED_READ(type, name, notify, arguments)                                                  \
    OMNIUI_PROPERTY_DECLARE_GETTER(protected,                                                                          \
                                   {return OMNI_PROPERTY_NAME(name);},                                                 \
                                   type const&,                                                                        \
                                   type, name, notify, arguments)

/* READ_VALUE key, declare the virtual function to return by value (copy) */
#define OMNIUI_PROPERTY_PUBLIC_READ_VALUE(type, name, notify, arguments)                                               \
    OMNIUI_PROPERTY_DECLARE_GETTER(public,                                                                             \
                                   {return OMNI_PROPERTY_NAME(name);},                                                 \
                                   type,                                                                               \
                                   type, name, notify, arguments)

#define OMNIUI_PROPERTY_PROTECTED_READ_VALUE(type, name, notify, arguments)                                            \
    OMNIUI_PROPERTY_DECLARE_GETTER(protected,                                                                          \
                                   {return OMNI_PROPERTY_NAME(name);},                                                 \
                                   type,                                                                               \
                                   type, name, notify, arguments)

/* GET_VALUE key, declare the virtual function, but use must implement it */
#define OMNIUI_PROPERTY_PUBLIC_GET_VALUE(type, name, notify, arguments)                                                \
    OMNIUI_PROPERTY_DECLARE_GETTER(public,                                                                             \
                                   ;,                                                                                  \
                                   type,                                                                               \
                                   type, name, notify, arguments)

#define OMNIUI_PROPERTY_PROTECTED_GET_VALUE(type, name, notify, arguments)                                             \
    OMNIUI_PROPERTY_DECLARE_GETTER(protected,                                                                          \
                                   ;,                                                                                  \
                                   type,                                                                               \
                                   type, name, notify, arguments)

/* Common macro for scoped write implementation */
#define OMNIUI_PROPERTY_SCOPED_WRITE(scope, type, name, notify, arguments)                                             \
scope:                                                                                                                 \
    virtual void BOOST_PP_SEQ_ELEM(1, arguments)(type const& v)                                                        \
    {                                                                                                                  \
        if (!checkIfEqual(OMNI_PROPERTY_NAME(name), v))                                                                \
        {                                                                                                              \
            OMNI_PROPERTY_NAME(name) = v;                                                                              \
            OMNIUI_PROFILE_VERBOSE_FUNCTION;                                                                           \
            OMNIUI_PROPERTY_CALLBACK_CODE(type, name, notify)                                                          \
        }                                                                                                              \
    }                                                                                                                  \
    /* Call the proper macro for the next argument */                                                                  \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PUBLIC_, BOOST_PP_SEQ_ELEM(2, arguments))                                             \
    (type, name, notify, BOOST_PP_SEQ_REST_N(2, arguments))

/* WRITE key for public access */
#define OMNIUI_PROPERTY_PUBLIC_WRITE(type, name, notify, arguments)                                                    \
    OMNIUI_PROPERTY_SCOPED_WRITE(public, type, name, notify, arguments)

/* WRITE key for protected access */
#define OMNIUI_PROPERTY_PROTECTED_WRITE(type, name, notify, arguments)                                                 \
    OMNIUI_PROPERTY_SCOPED_WRITE(protected, type, name, notify, arguments)

#define OMNIUI_PROPERTY_PUBLIC_NOTIFY(type, name, notify, arguments)                                                   \
public:                                                                                                                \
    virtual void notify(std::function<void(type const&)> f)                                                            \
    {                                                                                                                  \
        if(f)                                                                                                          \
        {                                                                                                              \
            OMNI_PROPERTY_CALLBACK_NAME(notify).add(std::move(f));                                                     \
        }                                                                                                              \
        else                                                                                                           \
        {                                                                                                              \
            OMNI_PROPERTY_CALLBACK_NAME(notify).destroy();                                                             \
        }                                                                                                              \
    }                                                                                                                  \
    /* Call the proper macro for the next argument */                                                                  \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PUBLIC_, BOOST_PP_SEQ_ELEM(2, arguments))                                             \
    (type, name, notify, BOOST_PP_SEQ_REST_N(2, arguments))

#define OMNIUI_PROPERTY_PROTECTED_NOTIFY(type, name, notify, arguments)                                                \
protected:                                                                                                             \
    virtual void notify(std::function<void(type const&)> f)                                                            \
    {                                                                                                                  \
        if(f)                                                                                                          \
        {                                                                                                              \
            OMNI_PROPERTY_CALLBACK_NAME(notify).add(std::move(f));                                                     \
        }                                                                                                              \
        else                                                                                                           \
        {                                                                                                              \
            OMNI_PROPERTY_CALLBACK_NAME(notify).destroy();                                                             \
        }                                                                                                              \
    }                                                                                                                  \
    /* Call the proper macro for the next argument */                                                                  \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PROTECTED_, BOOST_PP_SEQ_ELEM(2, arguments))                                          \
    (type, name, notify, BOOST_PP_SEQ_REST_N(2, arguments))

#define OMNIUI_PROPERTY_PUBLIC_PROTECTED(type, name, notify, arguments)                                                \
    /* Change the next keyword to PROTECTED */                                                                         \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PROTECTED_, BOOST_PP_SEQ_ELEM(1, arguments))                                          \
    (type, name, notify, BOOST_PP_SEQ_REST_N(1, arguments))

#define OMNIUI_PROPERTY_PROTECTED_PROTECTED(type, name, notify, arguments) /* Should never happen */                   \
    BOOST_PP_ERROR(0x0001)

#define OMNIUI_PROPERTY_PUBLIC_DEFAULT(type, name, notify, arguments)                                                  \
    /* Skip and continue working with the next keyword */                                                              \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PUBLIC_, BOOST_PP_SEQ_ELEM(2, arguments))                                             \
    (type, name, notify, BOOST_PP_SEQ_REST_N(2, arguments))

#define OMNIUI_PROPERTY_PROTECTED_DEFAULT(type, name, notify, arguments)                                               \
    /* Skip and continue working with the next keyword */                                                              \
    BOOST_PP_CAT(OMNIUI_PROPERTY_PROTECTED_, BOOST_PP_SEQ_ELEM(2, arguments))                                          \
    (type, name, notify, BOOST_PP_SEQ_REST_N(2, arguments))

#define OMNIUI_PROPERTY_PUBLIC_END(type, name, notify, arguments)
#define OMNIUI_PROPERTY_PROTECTED_END(type, name, notify, arguments)

// Looking for DEFAULT in the sequece
#define OMNIUI_PROPERTY_FIND_DEFAULT(arguments)                                                                        \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_DEFAULT_, BOOST_PP_SEQ_ELEM(0, arguments))(arguments)
#define OMNIUI_PROPERTY_FIND_DEFAULT_READ(arguments)                                                                   \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_DEFAULT_, BOOST_PP_SEQ_ELEM(2, arguments))                                       \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_DEFAULT_READ_VALUE(arguments)                                                             \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_DEFAULT_, BOOST_PP_SEQ_ELEM(2, arguments))                                       \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_DEFAULT_GET_VALUE(arguments)                                                              \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_DEFAULT_, BOOST_PP_SEQ_ELEM(2, arguments))                                       \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_DEFAULT_WRITE(arguments)                                                                  \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_DEFAULT_, BOOST_PP_SEQ_ELEM(2, arguments))                                       \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_DEFAULT_NOTIFY(arguments)                                                                 \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_DEFAULT_, BOOST_PP_SEQ_ELEM(2, arguments))                                       \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_DEFAULT_PROTECTED(arguments)                                                              \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_DEFAULT_, BOOST_PP_SEQ_ELEM(1, arguments))                                       \
    (BOOST_PP_SEQ_REST_N(1, arguments))
#define OMNIUI_PROPERTY_FIND_DEFAULT_DEFAULT(arguments) BOOST_PP_SEQ_ELEM(1, arguments)
#define OMNIUI_PROPERTY_FIND_DEFAULT_END(arguments) BOOST_PP_EMPTY()

// Looking for NOTIFY in the sequece
#define OMNIUI_PROPERTY_FIND_NOTIFY(arguments)                                                                         \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_NOTIFY_, BOOST_PP_SEQ_ELEM(0, arguments))(arguments)
#define OMNIUI_PROPERTY_FIND_NOTIFY_READ(arguments)                                                                    \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_NOTIFY_, BOOST_PP_SEQ_ELEM(2, arguments))                                        \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_NOTIFY_READ_VALUE(arguments)                                                              \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_NOTIFY_, BOOST_PP_SEQ_ELEM(2, arguments))                                        \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_NOTIFY_GET_VALUE(arguments)                                                               \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_NOTIFY_, BOOST_PP_SEQ_ELEM(2, arguments))                                        \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_NOTIFY_WRITE(arguments)                                                                   \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_NOTIFY_, BOOST_PP_SEQ_ELEM(2, arguments))                                        \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_NOTIFY_DEFAULT(arguments)                                                                 \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_NOTIFY_, BOOST_PP_SEQ_ELEM(2, arguments))                                        \
    (BOOST_PP_SEQ_REST_N(2, arguments))
#define OMNIUI_PROPERTY_FIND_NOTIFY_PROTECTED(arguments)                                                               \
    BOOST_PP_CAT(OMNIUI_PROPERTY_FIND_NOTIFY_, BOOST_PP_SEQ_ELEM(1, arguments))                                        \
    (BOOST_PP_SEQ_REST_N(1, arguments))
#define OMNIUI_PROPERTY_FIND_NOTIFY_NOTIFY(arguments) BOOST_PP_SEQ_ELEM(1, arguments)
#define OMNIUI_PROPERTY_FIND_NOTIFY_END(arguments) BOOST_PP_EMPTY()

OMNIUI_NAMESPACE_OPEN_SCOPE

class Widget;

// We need a custom fuction to test if the objects are equal because some objects don't provide equal operator.
template <typename T>
inline bool checkIfEqual(T const& t, T const& u)
{
    return t == u;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
