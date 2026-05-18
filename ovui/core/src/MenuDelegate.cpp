/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/Button.h>
#include <omni/ui/Frame.h>
#include <omni/ui/HStack.h>
#include <omni/ui/Image.h>
#include <omni/ui/ImageWithProvider.h>
#include <omni/ui/Label.h>
#include <omni/ui/Line.h>
#include <omni/ui/Menu.h>
#include <omni/ui/MenuDelegate.h>
#include <omni/ui/MenuItem.h>
#include <omni/ui/Rectangle.h>
#include <omni/ui/Separator.h>
#include <omni/ui/Spacer.h>
#include <omni/ui/Triangle.h>
#include <omni/ui/VStack.h>
#include <omni/ui/ZStack.h>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct MenuDelegate::MenuDelegateData
{
};


/**
 * @brief A singleton that keeps the default delegate
 */
class DefaultDelegateHolder
{
public:
    static DefaultDelegateHolder& instance()
    {
        static DefaultDelegateHolder holder;
        return holder;
    }

    // delete copy and move constructors and assign operators
    DefaultDelegateHolder(DefaultDelegateHolder const&) = delete;
    DefaultDelegateHolder(DefaultDelegateHolder&&) = delete;
    DefaultDelegateHolder& operator=(DefaultDelegateHolder const&) = delete;
    DefaultDelegateHolder& operator=(DefaultDelegateHolder&&) = delete;

    const std::shared_ptr<MenuDelegate>& getDefaultDelegate()
    {
        return m_defaultDelegate;
    }

    void setDefaultDelegate(std::shared_ptr<MenuDelegate> delegate)
    {
        m_defaultDelegate = std::move(delegate);
    }

private:
    DefaultDelegateHolder() : m_defaultDelegate{ std::make_shared<MenuDelegate>() }
    {
    }

    ~DefaultDelegateHolder() = default;

    std::shared_ptr<MenuDelegate> m_defaultDelegate;
};

MenuDelegate::MenuDelegate() = default;
MenuDelegate::~MenuDelegate() = default;

void MenuDelegate::buildItem(const MenuHelper* item)
{
    if (this->hasOnBuildItemFn())
    {
        this->callOnBuildItemFn(item);
        return;
    }

    static const std::string menuItemTypeName = "Menu.Item";
    static const std::string separatorTypeName = "Menu.Separator";
    static const std::string checkTypeName = "Menu.Item.CheckMark";
    static const std::string expandTypeName = "Menu.Item.ExpandMark";
    static const float iconWidth = 20.0f;

    if (auto menu = dynamic_cast<const Menu*>(item))
    {
        OMNIKIT_WITH_CONTAINER(HStack::create())
        {
            bool isMenuBar = menu->isInHorizontalLayout();

            if (!isMenuBar)
            {
                if (this->_siblingsHaveCheckable(item))
                {
                    Spacer::create()->setWidth(Pixel{ iconWidth });
                }
                else
                {
                    Spacer::create()->setWidth(Pixel{ iconWidth / 3.0f });
                }
            }

            auto label = Label::create(menu->getText());
            if (isMenuBar)
            {
                label->setStyleTypeNameOverride("MenuBar.Item");
            }
            else
            {
                label->setStyleTypeNameOverride(menuItemTypeName);
            }

            if (!isMenuBar)
            {
                auto image = ImageWithProvider::create();
                image->setWidth(Pixel{ iconWidth });
                image->setStyleTypeNameOverride(expandTypeName);
            }
        }
    }
    else if (auto separator = dynamic_cast<const Separator*>(item))
    {
        OMNIKIT_WITH_CONTAINER(HStack::create())
        {
            if (!separator->getText().empty())
            {
                auto label = Label::create(separator->getText());
                label->setWidth(Pixel{ 0.0f });
                label->setStyleTypeNameOverride(separatorTypeName);
            }

            auto line = Line::create();
            line->setStyleTypeNameOverride(separatorTypeName);
            line->setAlignment(Alignment::eCenter);
        }
    }
    else if (auto menuItem = dynamic_cast<const MenuItem*>(item))
    {
        OMNIKIT_WITH_CONTAINER(HStack::create())
        {
            if (menuItem->isCheckable())
            {
                if (menuItem->isChecked())
                {
                    // Check mark
                    auto image = ImageWithProvider::create();
                    image->setWidth(Pixel{ iconWidth });
                    image->setStyleTypeNameOverride(checkTypeName);
                }
                else
                {
                    // The space for the column with check mark
                    Spacer::create()->setWidth(Pixel{ iconWidth });
                }
            }
            else if (this->_siblingsHaveCheckable(item))
            {
                // The space for the column with check mark
                Spacer::create()->setWidth(Pixel{ iconWidth });
            }
            else
            {
                Spacer::create()->setWidth(Pixel{ iconWidth / 3.0f });
            }

            // The label itself
            auto label = Label::create(menuItem->getText());
            label->setStyleTypeNameOverride(menuItemTypeName);

            if (MenuDelegate::_siblingsHaveHotkeyText(menuItem))
            {
                auto hotkey = Label::create(menuItem->getHotkeyText());
                hotkey->setWidth(Pixel{ 100.0f });
                hotkey->setStyleTypeNameOverride(menuItemTypeName);
                hotkey->setEnabled(false);
            }
        }
    }
}

void MenuDelegate::buildTitle(const MenuHelper* item)
{
    if (this->hasOnBuildTitleFn())
    {
        this->callOnBuildTitleFn(item);
        return;
    }

    auto menu = dynamic_cast<const Menu*>(item);
    if (menu && (menu->getDirection() == Stack::Direction::eLeftToRight ||
                 menu->getDirection() == Stack::Direction::eRightToLeft))
    {
        return;
    }

    float height = 14.0f;

    auto layers = ZStack::create();
    layers->setHeight(Pixel{ height });
    OMNIKIT_WITH_CONTAINER(layers)
    {
        auto rect = Rectangle::create();
        rect->setStyleTypeNameOverride("Menu.Title");
        auto* rectPtr = rect.get();
        rect->setCheckedChangedFn([rectPtr](const bool&) { rectPtr->setChecked(false); });

        if (menu)
        {
            OMNIKIT_WITH_CONTAINER(HStack::create())
            {
                Spacer::create()->setWidth(Pixel{ height });

                auto line = Line::create();
                line->setStyleTypeNameOverride("Menu.Title.Line");

                auto closeFrame = Frame::create();
                closeFrame->setWidth(Pixel{ height });
                OMNIKIT_WITH_CONTAINER(closeFrame)
                {
                    // Close button is invisible by default. It will be shown when
                    // the mouse hovers the title.
                    auto closeButton = Image::create();
                    closeButton->setStyleTypeNameOverride("Menu.Item.CloseMark");

                    std::weak_ptr<Menu> weakItem = const_cast<Menu*>(menu)->castShared();
                    closeButton->setMousePressedFn([weakItem](auto x, auto y, auto button, auto flag) {
                        if (button != 0)
                        {
                            return;
                        }

                        auto sharedItem = weakItem.lock();
                        if (sharedItem)
                        {
                            sharedItem->hide();
                        }
                    });
                }
            }
        }
    }
}

void MenuDelegate::buildStatus(const MenuHelper* item)
{
    if (this->hasOnBuildStatusFn())
    {
        this->callOnBuildStatusFn(item);
        return;
    }

    auto menu = dynamic_cast<const Menu*>(item);
    if (menu && (menu->getDirection() == Stack::Direction::eLeftToRight ||
                 menu->getDirection() == Stack::Direction::eRightToLeft))
    {
        return;
    }

    // Empty space of 4 pixels
    auto spacer = Spacer::create();
    spacer->setHeight(Pixel{ 4.0f });
}

const std::shared_ptr<MenuDelegate>& MenuDelegate::getDefaultDelegate()
{
    return DefaultDelegateHolder::instance().getDefaultDelegate();
}

void MenuDelegate::setDefaultDelegate(std::shared_ptr<MenuDelegate> delegate)
{
    DefaultDelegateHolder::instance().setDefaultDelegate(delegate);
}

bool MenuDelegate::_siblingsHaveHotkeyText(const MenuHelper* item)
{
    for (const auto& sibling : item->_getSiblings())
    {
        if (auto menuHelperSibling = MenuHelper::_getMenuHelper(*sibling.get()))
        {
            if (!menuHelperSibling->getHotkeyText().empty())
            {
                return true;
            }
        }
    }

    return false;
}

bool MenuDelegate::_siblingsHaveCheckable(const MenuHelper* item)
{
    for (const auto& sibling : item->_getSiblings())
    {
        if (auto menuHelperSibling = MenuHelper::_getMenuHelper(*sibling.get()))
        {
            if (menuHelperSibling->isCheckable())
            {
                return true;
            }
        }
    }

    return false;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
