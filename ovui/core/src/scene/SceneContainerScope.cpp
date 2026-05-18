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

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/SceneContainerScope.h>

#include <assert.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

SceneContainerStack& SceneContainerStack::instance()
{
    static SceneContainerStack containerStack;
    return containerStack;
}

void SceneContainerStack::push(std::shared_ptr<AbstractContainer> current)
{
    m_stack.push(std::move(current));
}

void SceneContainerStack::pop()
{
    assert(!m_stack.empty());

    m_stack.pop();
}

std::shared_ptr<AbstractContainer> SceneContainerStack::top()
{
    const auto& stack = SceneContainerStack::instance().m_stack;
    if (!stack.empty())
    {
        return stack.top();
    }
    return {};
}

bool SceneContainerStack::addChildToTop(std::shared_ptr<AbstractItem> child)
{
    if (m_stack.empty() || !m_stack.top())
    {
        return false;
    }

    // Hold a local reference in case any code below winds up pushing to the stack.
    std::shared_ptr<AbstractContainer> top = m_stack.top();

    top->addChild(child);

    child->_setParent(top.get());
    child->setScene(top.get()->_getScene());
    child->_setSceneView(top.get()->getSceneView());

    return true;
}

SceneContainerScopeBase::SceneContainerScopeBase(const std::shared_ptr<AbstractContainer> current)
    : m_current{ std::move(current) }, m_isValid{ true }
{
    SceneContainerStack::instance().push(m_current);
}

SceneContainerScopeBase::~SceneContainerScopeBase()
{
    SceneContainerStack::instance().pop();
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
