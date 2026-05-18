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

#include <memory>
#include <stack>
#include <utility>

// Creates the scope with the given stack widget. So all the items in the scope will be automatically placed to the
// given stack.
// TODO: Probably it's not the best name.
#define OMNIKIT_WITH_CONTAINER(A)                                                                                      \
    for (omni::ui::ContainerScope<> __parent{ A }; __parent.isValid(); __parent.invalidate())

OMNIUI_NAMESPACE_OPEN_SCOPE

class Container;
class Widget;

/**
 * @brief Singleton object that holds the stack of containers. We use it to automatically add widgets to the top
 * container when the widgets are created.
 */
class OMNIUI_CLASS_API ContainerStack
{
public:
    // Singleton pattern.
    ContainerStack(const ContainerStack&) = delete;
    ContainerStack& operator=(const ContainerStack&) = delete;
    // No move constructor and no move-assignments are allowed because of 12.8 [class.copy]/9 and 12.8 [class.copy]/20
    // of the C++ standard

    /**
     * @brief The only instance of the singleton.
     */
    OMNIUI_API
    static ContainerStack& instance();

    /**
     * @brief Push the container to the top of the stack. All the newly created widgets will be added to this container.
     */
    OMNIUI_API
    void push(std::shared_ptr<Container> current);

    /**
     * @brief Removes the container from the stack. The previous one will be active.
     */
    OMNIUI_API
    void pop();

    /**
     * @brief Add the given widget to the top container.
     */
    OMNIUI_API
    bool addChildToTop(std::shared_ptr<Widget> child);

private:
    // Disallow instantiation outside of the class.
    ContainerStack() = default;

    std::stack<std::shared_ptr<Container>> m_stack;
};


/**
 * @brief Puts the given container to the top of the stack when this object is constructed. And removes this container
 * when it's destructed.
 */
class OMNIUI_CLASS_API ContainerScopeBase
{
public:
    OMNIUI_API
    ContainerScopeBase(const std::shared_ptr<Container> current);

    OMNIUI_API
    virtual ~ContainerScopeBase();

    /**
     * @brief Returns the container it was created with.
     */
    const std::shared_ptr<Container>& get() const
    {
        return m_current;
    }

    /**
     * @brief Checks if this object is valid. It's always valid untill it's invalidated. Once it's invalidated, there is
     * no way to make it valid again.
     */
    bool isValid() const
    {
        return m_isValid;
    }

    /**
     * @brief Makes this object invalid.
     */
    void invalidate()
    {
        m_isValid = false;
    }

private:
    std::shared_ptr<Container> m_current;
    bool m_isValid;
};

/**
 * @brief The templated class ContainerScope creates a new container and puts it to the top of the stack.
 */
template <class T = void>
class ContainerScope : public ContainerScopeBase
{
public:
    template <typename... Args>
    ContainerScope(Args&&... args) : ContainerScopeBase{ T::create(std::forward<Args>(args)...) }
    {
    }
};

/**
 * @brief Specialization. It takes existing container and puts it to the top of the stack.
 */
template <>
class ContainerScope<void> : public ContainerScopeBase
{
public:
    template <typename... Args>
    ContainerScope(const std::shared_ptr<Container> current) : ContainerScopeBase{ std::move(current) }
    {
    }
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
