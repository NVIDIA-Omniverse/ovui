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

#include <omni/ui/ContainerScope.h>

#include <memory>
#include <string>
#include <utility>

// The OMNIUI_OBJECT macro must appear in the public section of a class definition of all the objects that use
// other services provided by UI Framework system. It implements two public methods: create and castShared.
// We need to specify the class name because we need to have the text representation of it in getTypeName.
#define OMNIUI_OBJECT_(currentType, overrideText)                                                                      \
public:                                                                                                                \
    /* A little shortcut to get the current class type */                                                              \
    using This = currentType;                                                                                          \
                                                                                                                       \
    /** Create the widget and put it as a child of the top item of ContainerStack. */                                  \
    /* It's very useful to have the new object already attached to the layout. */                                      \
    template <typename... Args>                                                                                        \
    static std::shared_ptr<This> create(Args&&... args)                                                                \
    {                                                                                                                  \
        /* Guard against instantiation of abstract types (diagnosed as error on */                                     \
        /* Apple Clang even in uninstantiated templates). */                                                           \
        if constexpr (!std::is_abstract_v<This>)                                                                       \
        {                                                                                                              \
            /* Cannot use std::make_shared because the constructor is protected */                                     \
            std::shared_ptr<This> ptr{ new This{ std::forward<Args>(args)... } };                                      \
                                                                                                                       \
            ContainerStack::instance().addChildToTop(std::static_pointer_cast<Widget>(ptr));                           \
                                                                                                                       \
            return ptr;                                                                                                \
        }                                                                                                              \
        else                                                                                                           \
        {                                                                                                              \
            return nullptr;                                                                                            \
        }                                                                                                              \
    }                                                                                                                  \
    /* version that accepts a destructor and passes it to the shared_ptr */                                            \
    template<class Destructor, typename... Args>                                                                       \
    static std::shared_ptr<This> createWithDestructor(Destructor destructor, Args&&... args)                           \
    {                                                                                                                  \
        if constexpr (!std::is_abstract_v<This>)                                                                       \
        {                                                                                                              \
            /* Cannot use std::make_shared because the constructor is protected */                                     \
            std::shared_ptr<This> ptr{ new This{ std::forward<Args>(args)... }, std::forward<Destructor>(destructor) };\
                                                                                                                       \
            ContainerStack::instance().addChildToTop(std::static_pointer_cast<Widget>(ptr));                           \
                                                                                                                       \
            return ptr;                                                                                                \
        }                                                                                                              \
        else                                                                                                           \
        {                                                                                                              \
            return nullptr;                                                                                            \
        }                                                                                                              \
    }                                                                                                                  \
                                                                                                                       \
    /** Returns this as a shared pointer */                                                                            \
    template <typename T = This>                                                                                       \
    std::shared_ptr<T> castShared()                                                                                    \
    {                                                                                                                  \
        return std::static_pointer_cast<T>(this->shared_from_this());                                                  \
    }                                                                                                                  \
                                                                                                                       \
    /** Return the name of the current type. We use it to resolve the styles. */                                       \
    virtual const std::string& getTypeName() const overrideText                                                        \
    {                                                                                                                  \
        static const std::string typeName{ #currentType };                                                             \
        return typeName;                                                                                               \
    }                                                                                                                  \
                                                                                                                       \
private:

#define OMNIUI_OBJECT(currentType) OMNIUI_OBJECT_(currentType, override)
#define OMNIUI_OBJECT_BASE(currentType) OMNIUI_OBJECT_(currentType, )

// Use OMNIUI_OBJECT_ABSTRACT for abstract base classes that cannot be instantiated directly.
// It provides getTypeName() and castShared() but deliberately omits create() / createWithDestructor()
// to avoid compiler errors on Apple Clang (and other strict C++ compilers) that reject
// 'new AbstractClass{...}' even in uninstantiated template bodies.
#define OMNIUI_OBJECT_ABSTRACT(currentType)                                                                            \
public:                                                                                                                \
    using This = currentType;                                                                                          \
                                                                                                                       \
    /** Returns this as a shared pointer */                                                                            \
    template <typename T = This>                                                                                       \
    std::shared_ptr<T> castShared()                                                                                    \
    {                                                                                                                  \
        return std::static_pointer_cast<T>(this->shared_from_this());                                                  \
    }                                                                                                                  \
                                                                                                                       \
    virtual const std::string& getTypeName() const override                                                            \
    {                                                                                                                  \
        static const std::string typeName{ #currentType };                                                             \
        return typeName;                                                                                               \
    }                                                                                                                  \
                                                                                                                       \
private:
