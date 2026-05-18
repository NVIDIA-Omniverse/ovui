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

#include "platform/Assert.h"
#include <omni/ui/Container.h>
#include <omni/ui/Style.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The widget that is never drawn. It's used as the holder for the default root style.
 */
class RootStyleContainer : public Container
{
public:
    RootStyleContainer() = default;
    ~RootStyleContainer() = default;

    virtual void addChild(std::shared_ptr<Widget> widget) override
    {
        m_children.emplace_back(std::move(widget));
    }

    virtual void clear() override
    {
        m_children.clear();
    }

    void cascadeStyle() override
    {
        Widget::cascadeStyle();

        for (auto it = m_children.begin(); it != m_children.end();)
        {
            std::shared_ptr<Widget> child = it->lock();
            if (!child)
            {
                // Erase invalid child
                it = m_children.erase(it);
                continue;
            }

            child->cascadeStyle();
            ++it;
        }
    }

protected:
    void _drawContent(float elapsedTime) override
    {
        // Should never be executed.
        OMNIUI_ASSERT(false);
    }

    std::vector<std::shared_ptr<Widget>> _getChildren() const override
    {
        return {};
    }

private:
    std::vector<std::weak_ptr<Widget>> m_children;
};

Style::Style() : m_rootStyleWidget(new RootStyleContainer{})
{
    // When we have Python default style, we need to get rid of StyleContainer::defaultStyle
    m_rootStyleWidget->setStyle(StyleContainer::defaultStyle());
}

Style::~Style() = default;

Style& Style::getInstance()
{
    static Style instance;
    return instance;
}

std::shared_ptr<StyleContainer> const& Style::getDefaultStyle() const
{
    return m_rootStyleWidget->getStyle();
}

void Style::setDefaultStyle(std::shared_ptr<StyleContainer> const& style)
{
    m_rootStyleWidget->setStyle(style);
}

void Style::setDefaultStyle(StyleContainer&& style)
{
    // Move it to shared pointer.
    this->setDefaultStyle(std::make_shared<StyleContainer>(std::move(style)));
}

void Style::connectToGlobalStyle(const std::shared_ptr<Widget>& widget)
{
    widget->setParent(m_rootStyleWidget.get());
    m_rootStyleWidget->addChild(widget);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
