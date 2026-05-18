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

#include <omni/ui/Container.h>
#include <omni/ui/ContainerScope.h>

#include <assert.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

ContainerStack& ContainerStack::instance()
{
    static ContainerStack containerStack;
    return containerStack;
}

void ContainerStack::push(std::shared_ptr<Container> current)
{
    m_stack.push(std::move(current));
}

void ContainerStack::pop()
{
    assert(!m_stack.empty());

    m_stack.pop();
}

bool ContainerStack::addChildToTop(std::shared_ptr<Widget> child)
{
    if (m_stack.empty() || !m_stack.top())
    {
        return false;
    }

    // Hold a local reference in case any code below winds up pushing to the stack.
    std::shared_ptr<Container> top = m_stack.top();
    top->addChild(child);

    // TODO: We need to decide if it's the best place. It can also be inside addChild. The reason it's here is to set
    // the parent explicitly because parent object can also be if a widget is constructed with another widgets, like
    // Button is constructed with Label and Rectangle.
    child->setParent(top.get());

    return true;
}

ContainerScopeBase::ContainerScopeBase(const std::shared_ptr<Container> current)
    : m_current{ std::move(current) }, m_isValid{ true }
{
    ContainerStack::instance().push(m_current);
}

ContainerScopeBase::~ContainerScopeBase()
{
    ContainerStack::instance().pop();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
