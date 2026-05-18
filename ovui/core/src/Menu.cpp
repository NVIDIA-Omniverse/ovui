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

#include "platform/Assert.h"
#include "platform/Log.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include "platform/PlatformRegistry.h"
#include <omni/ui/Frame.h>
#include <omni/ui/Menu.h>
#include <omni/ui/MenuItem.h>
#include <omni/ui/MenuDelegate.h>
#include <omni/ui/Style.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/windowmanager/WindowManagerUtils.h>

#include "MenuData.h"

#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

// Filter if several menus was requested in one frame. When several popups are created at single frame, ImGui shows
// nothing. It's confusing when creating a menu and nothing shows. We need to show something. With this global variable
// when the user requests several menus to show at the same frame, the last one will be shown.
static Menu* g_requestedMenu = nullptr;
std::shared_ptr<Menu> g_currentMenu;

// The distance the user need to pass to make the menu teared off
constexpr float kStickDistance = 5.0f;

Menu::MenuData::~MenuData()
{
}


Menu::Menu(const std::string& text, MenuData* dataPtr)
    : Stack(Stack::Direction::eTopToBottom, dataPtr ? dataPtr : new MenuData)
{
    this->setText(text);

    // Know if the parent is a menu
    this->setParentChangedFn([this](auto* parent) {
        _getData<MenuData>().m_parentMenu = dynamic_cast<Menu*>(parent);
    });

    // Clear the title when tearable is changed
    this->_setTearableChangedFn([this](auto tearable) {
        _getData<MenuData>().m_titleDirty = true;
    });

    this->setStyleTypeNameOverrideChangedFn([this](auto name)
    {
        this->_setEmptyStyleTypeNameOverride();
    });

    this->_setMenuCompatibilityChangedFn([this](auto compatibility)
    {
        if (compatibility)
        {
            OMNIUI_LOG_WARN("Menu::setMenuCompatibility - compatibility is deprecated & no longer supported");
            this->setMenuCompatibility(false);
        }
    });

    this->_setTextChangedFn([this](auto text) {
        auto& data = _getData<MenuData>();
        const bool visible = !text.empty();
        if (data.m_title)
        {
            data.m_title->setVisible(visible);
        }
        if (data.m_status)
        {
            data.m_status->setVisible(visible);
        }
    });

    // We need a unique string for Editor::addWindow and for BeginPopup. It's possible that the user creates several
    // menus with the same name, that's why we use neither text nor name.
    auto& data = _getData<MenuData>();
    data.m_menuUniqueId = "Menu_" + std::to_string(reinterpret_cast<intptr_t>(this));
    data.m_popupUniqueId = "Popup_" + std::to_string(reinterpret_cast<intptr_t>(this));

    MenuHelper::_menuHelperInit(*this);

    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        const bool visible = !this->getText().empty();
        data.m_title = Frame::create();
        data.m_title->setVisible(visible);
        data.m_title->setParent(this);
        data.m_status = Frame::create();
        data.m_status->setVisible(visible);
        data.m_status->setParent(this);
    }
    // It will add the title and status to the stack
    this->clear();
}

bool Menu::_setEmptyStyleTypeNameOverride()
{
    static std::string modernTypeName = "Menu.Window";

    if (this->getStyleTypeNameOverride().empty())
    {
        this->setStyleTypeNameOverride(modernTypeName);
        return true;
    }
    return false;
}

std::string Menu::getIdentifier()
{
    std::string identifier = Widget::getIdentifier();
    if (identifier.empty())
    {
        identifier = this->getText();
        if (!identifier.empty())
        {
            identifier = normalizeIdentifier(identifier);
        }
    }
    return identifier;
}

Menu::~Menu()
{
    this->destroy();
}

void Menu::destroy()
{
    _getData<MenuData>().m_deferredOsWindowReleaseSubs.reset();

    this->_removeMenuWindow(true);

    this->_menuHelperDestroy();

    Stack::destroy();
}

void Menu::addChild(std::shared_ptr<Widget> widget)
{
    if (OMNIUI_UNLIKELY(!widget))
    {
        OMNIUI_LOG_ERROR("Menu::addChild attempting to add an invalid widget");
        return;
    }

    auto menuHelper = MenuHelper::_getMenuHelper(*widget.get());
    if (menuHelper)
    {
        // When menu_compatibility was true by default,
        // next setMenuCompatibility will trigger cascadeStyle
        // Now change menu_compatibility default to false,
        // Let's keep the behavior no change for same UI styles
        if (auto menu = dynamic_cast<Menu*>(widget.get()))
        {
            menu->_setEmptyStyleTypeNameOverride();
        }

        if (this->getText().empty() &&
            (this->getDirection() == Direction::eLeftToRight || this->getDirection() == Direction::eRightToLeft))
        {
            // Special case: MenuBar
            widget->setWidth(Pixel{ 0.0f });
        }
    }

    auto& children = _getMutableChildren();
    if (this->isMenuCompatibility())
    {
        children.push_back(widget);
        widget->useMarginFromStyle(useMarginFromStyle());
        return;
    }

    if (OMNIUI_LIKELY(!children.empty()))
    {
        children.pop_back();
    }

    Stack::addChild(widget);
    Stack::addChild(_getData<MenuData>().m_status);
}

void Menu::clear()
{
    // Destroy everything except the first and the last one.
    auto& children = _getMutableChildren();
    if (!children.empty())
    {
        for (size_t i = 1, n = children.size() - 1; i < n; ++i)
        {
            auto& child = children[i];
            if (child)
            {
                child->destroy();
                child->setParent(nullptr);
            }
        }
        children.clear();
    }

    auto& data = _getData<MenuData>();
    Stack::addChild(data.m_title);
    Stack::addChild(data.m_status);
}

void Menu::setComputedContentWidth(float width)
{
    this->_verifyTitleFrame();
    this->_verifyChildren();

    // Set the window size
    // TODO: if window visible
    if (this->getText().empty() &&
        (this->getDirection() == Direction::eLeftToRight || this->getDirection() == Direction::eRightToLeft))
    {
        // Special case: MenuBar
        Stack::setComputedContentWidth(width);
    }
    else
    {
        Stack::setComputedContentWidth(0.0f);
    }
    _getData<MenuData>().m_computedWindowWidth = this->getComputedContentWidth();

    if (!this->getText().empty())
    {
        Widget::setComputedContentWidth(this->_menuHelperEvalWidth(*this, width));
    }
}

void Menu::setComputedContentHeight(float height)
{
    this->_verifyTitleFrame();
    this->_verifyChildren();

    // Set the window size
    // TODO: if visible
    Stack::setComputedContentHeight(0.0f);
    _getData<MenuData>().m_computedWindowHeight = this->getComputedContentHeight();

    if (!this->getText().empty())
    {
        Widget::setComputedContentHeight(this->_menuHelperEvalHeight(*this, height));
    }
}

void Menu::cascadeStyle()
{
    // When menu_compatibility=true by default,
    // next setMenuCompatibility in constructor will trigger setMenuCompatibility(false)
    // Now change menu_compatibility default to false,
    // Let's keep the behavior no change for same UI styles
        if (this->_setEmptyStyleTypeNameOverride())
    {
        Stack::cascadeStyle();
        return;
    }

    this->useMarginFromStyle(false);
    Stack::cascadeStyle();
    this->_menuHelperCascadeStyle();
}

void Menu::_drawContent(float elapsedTime)
{
    this->_drawMenu(elapsedTime, false, true);
}

void Menu::_drawMenu(float elapsedTime, bool isInSeparateWindow, bool isPopupWindow)
{
    this->_verifyTitleFrame();
    this->_verifyChildren();

    enum class _WindowType
    {
        eNormal,
        ePopup,
        eMenu,
        eNoWindow,
    };

    // Save the current application window, so the window created in the draw loop will know which one it belongs to.
    auto& data = _getData<MenuData>();;
    std::unique_ptr<Workspace::AppWindowGuard> appWindowGuard;
    if (data.m_appWindow)
    {
        appWindowGuard = std::make_unique<Workspace::AppWindowGuard>(data.m_appWindow);
    }

    auto ctx = ImGui::GetCurrentContext();
    OMNIUI_ASSERT(ctx);
    ImGuiWindow* window = ctx->CurrentWindow;
    OMNIUI_ASSERT(window);

    float dpiScale = this->getDpiScale();

    const ImGuiID id =
        isInSeparateWindow ? window->GetID(data.m_popupUniqueId.c_str()) : window->GetID(data.m_menuUniqueId.c_str());
    bool popupWindowWasOpen = ImGui::IsPopupOpen(id, 0);

    // Get the window type.
    _WindowType needWindowType;
    if (!popupWindowWasOpen && !isInSeparateWindow && this->getText().empty())
    {
        needWindowType = _WindowType::eNoWindow;
    }
    else if (!isInSeparateWindow)
    {
        // We still need ImGui::BeginPopup, but it's called from another menu
        needWindowType = _WindowType::eMenu;
    }
    else if (isPopupWindow)
    {
        // We need ImGui::BeginPopup
        needWindowType = _WindowType::ePopup;
    }
    else
    {
        // We need ImGui::Begin
        needWindowType = _WindowType::eNormal;
    }

    bool wantOpenPopup = false;
    bool wantClosePopup = false;
    bool wantSkipMenu = false;

    if (needWindowType == _WindowType::ePopup && !popupWindowWasOpen)
    {
        // We are here because a context menu is just requested. Probably the
        // user requested many context menus. We need to show only the last one.

        if (this == g_requestedMenu)
        {
            // We are here because this context menu is the latest one the user
            // requested. It should be shown.
            wantOpenPopup = true;
            g_requestedMenu = nullptr;
            g_currentMenu = this->castShared();
        }
        else if (g_requestedMenu)
        {
            // It happens when several menus was requested at the same time. We
            // can only show one. Latest requested should be shown.
            this->_removeMenuWindowDeferred(false);
            return;
        }
    }

    // Styles
    uint32_t popColorCount = 0;
    uint32_t popFloatCount = 0;
    uint32_t color;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_PopupBg, color);
        ImGui::PushStyleColor(ImGuiCol_ChildBg, color);
        ImGui::PushStyleColor(ImGuiCol_WindowBg, color);
        popColorCount += 3;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_Border, color);
        popColorCount += 1;
    }

    float value;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &value))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_ChildBorderSize, value * dpiScale);
        ImGui::PushStyleVar(ImGuiStyleVar_PopupBorderSize, value * dpiScale);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, value * dpiScale);
        popFloatCount += 3;
    }

    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &value))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_PopupRounding, value * dpiScale);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, value * dpiScale);
        ImGui::PushStyleVar(ImGuiStyleVar_ChildRounding, value * dpiScale);
        popFloatCount += 3;
    }

    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &value))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(value * dpiScale, value * dpiScale));
        popFloatCount += 1;
    }

    Stack::Direction parentDirection = Stack::Direction::eTopToBottom;
    bool parentIsMoving = false;
    if (data.m_parentMenu)
    {
        parentDirection = data.m_parentMenu->getDirection();
        parentIsMoving = data.m_parentMenu->_getData<MenuData>().m_windowIsMoving;
    }
    bool isParentHorizontal =
        parentDirection == Stack::Direction::eLeftToRight || parentDirection == Stack::Direction::eRightToLeft;

    // AllowWhenBlockedByPopup because the sub menu is the popup window. If we
    // remove this, submenu will not open for teared off windows.
    bool noWindowsOnTop = ImGui::IsWindowHovered(ImGuiHoveredFlags_AllowWhenBlockedByPopup);
    bool hovered = isHovered() && noWindowsOnTop;
    bool pressed = ImGui::IsMouseClicked(0, false);
    bool released = ImGui::IsMouseReleased(0);
    bool wantWindowPosition = false;
    ImVec2 windowPosition{ 0.0f, 0.0f };

    // Indicates how many parents this menu has. Root level has 0 parents and
    // menuLevel for the root is 0. Root is usually a menu bar.
    int menuLevel = 0;
    {
        auto iterator = this;
        while (auto parent = iterator->_getData<MenuData>().m_parentMenu)
        {
            menuLevel++;
            iterator = parent;
        }
    }

    // Check if any of child window is hovered. We don't use
    // `ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows)` because it
    // checks the flag `ChildWindow` we don't use because of OM-58158.
    bool anyChildWindowHovered = false;
    {
        auto hovered = ctx->HoveredWindow;
        while (hovered)
        {
            if (hovered == window)
            {
                anyChildWindowHovered = true;
                break;
            }

            hovered = hovered->ParentWindow;
        }
    }

    auto cursor = ImGui::GetCursorScreenPos();

    if (hovered && !popupWindowWasOpen)
    {
        // We need to open the window if something is open in horizontal menu
        if (needWindowType == _WindowType::eMenu && data.m_parentMenu && isParentHorizontal)
        {
            // Since every Widget pushes ID, we need to compensate it when
            // looking for ID of siblings.
            ImGui::PopID();

            for (const auto& sibling : data.m_parentMenu->_getChildren())
            {
                if (const auto* menu = dynamic_cast<const Menu*>(sibling.get()))
                {
                    auto& menuData = menu->_getData<MenuData>();
                    // Like in the begin. We can't save ID and we can't use
                    // `menu->isShown()` because it's possible that this method
                    // is called twice for different windows, foe example for
                    // teared of window and for the menu popup.
                    ImGui::PushID(menu);
                    const ImGuiID siblingId = isInSeparateWindow ? window->GetID(menuData.m_popupUniqueId.c_str()) :
                                                                   window->GetID(menuData.m_menuUniqueId.c_str());
                    bool siblingWindowIsOpen = ImGui::IsPopupOpen(siblingId, 0);
                    ImGui::PopID();

                    if (siblingWindowIsOpen)
                    {
                        wantOpenPopup = true;
                        break;
                    }
                }
            }

            ImGui::PushID(this);
        }

        if (needWindowType == _WindowType::eMenu && !isParentHorizontal)
        {
            // The user hovers the menu item
            wantOpenPopup = !parentIsMoving;
        }

        if (needWindowType != _WindowType::eNoWindow && pressed)
        {
            // The user clicked the menu item
            wantOpenPopup = true;
        }
    }

    // Hide the menu in specific cases
    if (popupWindowWasOpen)
    {
        if (!hovered && ctx->HoveredWindow == window && !isParentHorizontal)
        {
            // The mouse hovers the window and doesn't hover the item.
            // We don't use wantClosePopup because it will close the floating
            // window. We want to hide the menu if the user doesn't hover the item.
            wantSkipMenu = true;
        }

        if (hovered && pressed && needWindowType == _WindowType::eMenu)
        {
            // Hide the menu if it's already opened and the user clicked it.
            wantSkipMenu = true;
        }

        bool pressedRight = ImGui::IsMouseClicked(1, false);
        bool pressedMiddle = ImGui::IsMouseClicked(2, false);
        if (needWindowType == _WindowType::eMenu && menuLevel == 1 && !anyChildWindowHovered &&
            (pressed || pressedRight || pressedMiddle))
        {
            // Hide the menu if left/right/middle button is pressed outside the
            // menu.
            wantSkipMenu = true;
        }
    }

    if (!popupWindowWasOpen && needWindowType == _WindowType::eMenu)
    {
        // The new menu position should be relative to the current menu.
        wantWindowPosition = true;
        if (isParentHorizontal)
        {
            // On the bottom of the current menu item
            windowPosition = ImFloor(ImVec2{ cursor.x, cursor.y + this->getComputedContentHeight() });
        }
        else
        {
            float titleHeight = 0.0f;
            if (data.m_title)
            {
                titleHeight = data.m_title->getComputedHeight();
            }
            // On the right of the current menu item
            // -2 to move the submenu closer to the parent menu to avoid the gap between them
            float const xAdjust = 2.0f;
            windowPosition = ImFloor(ImVec2{ cursor.x + this->getComputedContentWidth() - xAdjust, cursor.y - titleHeight });

            const auto& children = _getChildren();
            if (wantOpenPopup && !children.empty())
            {
                auto* platform = PlatformRegistry::instance().platform();
                std::shared_ptr<Widget> firstWidget = children.front();
                int appWindowWidth = 0;
                if (platform && data.m_appWindow)
                {
                    platform->getAppWindowSize(data.m_appWindow, &appWindowWidth, nullptr);
                }
                if (appWindowWidth > 0 && firstWidget)
                {
                    float max_width = static_cast<float>(appWindowWidth);
                    float ccwNext = firstWidget->getComputedContentWidth();
                    float beforeMove = windowPosition.x;

                    // is windowPosition.x offscreen
                    if (windowPosition.x + ccwNext + xAdjust >= max_width)
                    {
                        // adjust as windowPosition.x can include offscreen co-ords, so move back onscreen
                        windowPosition.x = max_width - ccwNext + xAdjust;

                        // will the menu submenu overlap current menu
                        if ((int)(windowPosition.x - cursor.x) < (int)ccwNext)
                        {
                            // move submenu to be behind current menu
                            windowPosition.x = cursor.x - ccwNext;
                        }
                    }
                    // if new position is offscreen then the menu is just too wide put it back to original position
                    if (windowPosition.x < 0)
                        windowPosition.x = beforeMove;

                }
            }
        }
    }

    // OM-92372: Need to test whether menu is actually enabled or not to avoid showing sub-menu when not enabled.
    // This check should probably be a lot higher to avoid excessive logic above, but the exactl flow of that logic
    // and what needs to happen is not really clear.
    if (wantOpenPopup && !this->isEnabled())
    {
        wantOpenPopup = false;
    }

    if (wantOpenPopup)
    {
        // It should be called only once. Otherwise whole UI is frozen.
        ImGui::OpenPopupEx(id);
    }

    if (!wantWindowPosition && data.m_useCustomPosition)
    {
        // Don't override the position for the menu
        // The position is set programmatically
        windowPosition = ImFloor(ImVec2{ data.m_menuPositionX * dpiScale, data.m_menuPositionY * dpiScale });
        wantWindowPosition = true;

        if (needWindowType != _WindowType::eMenu)
        {
            // We only need to set the position once. And don't let the menu to discard the position.
            data.m_useCustomPosition = false;
        }
    }

    if (needWindowType == _WindowType::eMenu && !this->getText().empty())
    {
        // It's a sub-menu or a pull-down menu in a menu bar. Draw the widgets
        // of the item.
        this->_menuHelperDraw(*this, elapsedTime);
    }

    // The window

    bool windowIsVisible = false;
    if (wantSkipMenu)
    {
        // Nothing to do
    }
    else if (needWindowType == _WindowType::eNoWindow)
    {
        windowIsVisible = true;
    }
    else if (needWindowType == _WindowType::eNormal)
    {
        if (wantWindowPosition)
        {
            ImGui::SetNextWindowPos(windowPosition, ImGuiCond_Always);
        }

        // It's possible that we called
        // `imguiInterface->setNextWindowBgAlpha(0.f);` in Hacks.cpp. We need to
        // deactivate it.
        ctx->NextWindowData.HasFlags &= ~ImGuiNextWindowDataFlags_HasBgAlpha;

        // This is a regular window
        ImGuiWindowFlags flags = ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoTitleBar |
                                 ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoNavFocus |
                                 ImGuiWindowFlags_NoDocking;
        bool open = true;
        windowIsVisible = ImGui::Begin(data.m_popupUniqueId.c_str(), &open, flags);

        if (!open)
        {
            wantClosePopup = true;
        }
    }
    else if (popupWindowWasOpen || wantOpenPopup)
    {
        if (wantWindowPosition)
        {
            ImGui::SetNextWindowPos(windowPosition, ImGuiCond_Always);
        }

        // Sub-menus are ChildWindow so that mouse can be hovering across them (otherwise top-most popup menu would
        // steal focus and not allow hovering on parent menu)
        ImGuiWindowFlags flags = ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoMove |
                                 ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoSavedSettings |
                                 ImGuiWindowFlags_NoNavFocus;
        // We don't use the flag ImGuiWindowFlags_ChildWindow here because the
        // window with this flag is never on the top. Thus any other window will
        // be on the top of the menu. (OM-58158)

        windowIsVisible = ImGui::BeginPopupEx(id, flags);

        if (!windowIsVisible && needWindowType == _WindowType::ePopup)
        {
            wantClosePopup = true;
        }
    }
    else if (needWindowType == _WindowType::ePopup)
    {
        // We are here the next frame after popup window is closed.
        wantClosePopup = true;
    }

    if (windowIsVisible)
    {
        if (needWindowType != _WindowType::eNormal)
        {
            // Set it only for regular menus. Ignore teared menus.
            this->_setShown(true);
        }

        const auto& children = _getChildren();
        std::shared_ptr<Widget> firstWidget;
        if (!children.empty())
        {
            firstWidget = children.front();
            if (OMNIUI_LIKELY(firstWidget))
            {
                firstWidget->setChecked(needWindowType == _WindowType::eNormal);
            }
            else
            {
                OMNIUI_LOG_ERROR("Menu::_drawMenu had empty first widget");
            }
        }

        // The window content
        Stack::_drawContent(elapsedTime);

        // Title is a part of the layout. But we can check the bounds here.
        bool titleExists = firstWidget && firstWidget->isVisible() &&
                           firstWidget->getComputedWidth() > 0.0f &&
                           firstWidget->getComputedHeight() > 0.0f;
        if (titleExists)
        {
            bool titleHovered = firstWidget->isHovered();

            if (needWindowType == _WindowType::eNormal)
            {
                if (titleHovered && ImGui::IsMouseDoubleClicked(0))
                {
                    // Double click: close it
                    wantClosePopup = true;
                }
            }
            else if (needWindowType == _WindowType::eMenu)
            {
                if (!data.m_windowIsMoving && titleHovered && ImGui::IsMouseClicked(0))
                {
                    // Start moving the window
                    data.m_windowIsMoving = true;
                    data.m_windowMovedDistanceX = 0.0f;
                    data.m_windowMovedDistanceY = 0.0f;

                    ImVec2 windowPosition = ImGui::GetWindowPos();
                    data.m_windowPosBeforeMoveX = windowPosition.x;
                    data.m_windowPosBeforeMoveY = windowPosition.y;
                }
                else if (data.m_windowIsMoving && ImGui::IsMouseDown(0))
                {
                    // Move the window
                    ImVec2 moved = ctx->IO.MouseDelta;

                    if (moved.x != 0.0f || moved.y != 0.0f)
                    {
                        data.m_windowMovedDistanceX += moved.x / dpiScale;
                        data.m_windowMovedDistanceY += moved.y / dpiScale;
                        float mouseMovedDistance = sqrtf(data.m_windowMovedDistanceX * data.m_windowMovedDistanceX +
                                                         data.m_windowMovedDistanceY * data.m_windowMovedDistanceY);
                        if (mouseMovedDistance > kStickDistance)
                        {
                            ImVec2 windowPosition = ImGui::GetWindowPos();
                            ImGui::SetWindowPos(
                                { windowPosition.x + moved.x, windowPosition.y + moved.y }, ImGuiCond_Always);
                        }
                        else
                        {
                            // Stick it back to the original location
                            ImGui::SetWindowPos({ data.m_windowPosBeforeMoveX, data.m_windowPosBeforeMoveY }, ImGuiCond_Always);
                        }
                    }
                }
                else if (data.m_windowIsMoving)
                {
                    // Stop moving
                    data.m_windowIsMoving = false;

                    float mouseMovedDistance = sqrtf(data.m_windowMovedDistanceX * data.m_windowMovedDistanceX +
                                                     data.m_windowMovedDistanceY * data.m_windowMovedDistanceY);

                    if (mouseMovedDistance > kStickDistance && released)
                    {
                        // Tear it off
                        this->_setTeared(true);
                        ImGuiWindow* current = ctx->CurrentWindow;
                        this->_showMenuWindow(current->Pos.x / dpiScale, current->Pos.y / dpiScale);
                        ImGui::CloseCurrentPopup();
                    }
                }
            }
        }

        if (needWindowType != _WindowType::eNormal && needWindowType != _WindowType::eNoWindow)
        {
            // End popup only if it's visible
            ImGui::EndPopup();
        }
    }
    else
    {
        const bool isTornAndVisible = m_tearable && m_teared && data.m_uiWindow;
        if (!isTornAndVisible)
        {
            this->_setTeared(false);
        }
        this->_setShown(false);

        if (popupWindowWasOpen)
        {
            // There is no ImGui::ClosePopup. If we don't close it, the text
            // frame ImGui::IsPopupOpen will be true. To close it we create
            // another popup window. It's very small and it's created for one
            // frame only.
            const ImGuiID id = window->GetID("##Dummy");
            ImGui::OpenPopupEx(id);
            ImGuiWindowFlags flags = ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoTitleBar |
                                     ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoNavFocus;
            if (window->Flags & (ImGuiWindowFlags_Popup | ImGuiWindowFlags_ChildMenu))
                flags |= ImGuiWindowFlags_ChildWindow;

            ImGui::SetNextWindowPos({ 0.0f, 0.0f }, ImGuiCond_Always);
            ImGui::SetNextWindowSize({ 0.0f, 0.0f }, ImGuiCond_Always);
            if (ImGui::BeginPopupEx(id, flags))
            {
                ImGui::EndPopup();
            }
        }
    }

    // Window is done

    if (!wantSkipMenu && needWindowType == _WindowType::eNormal)
    {
        // Unlike the popup window, we need to end normal window even if it's
        // invisible.
        ImGui::End();
    }

    if (wantClosePopup)
    {
        // The user closed popup. We need to remove the popup window.
        this->_removeMenuWindowDeferred(true);
    }

    // Style
    ImGui::PopStyleColor(popColorCount);
    ImGui::PopStyleVar(popFloatCount);
}

void Menu::show()
{
    auto& data = _getData<MenuData>();
    if (!this->getParent())
    {
        Style::getInstance().connectToGlobalStyle(this->shared_from_this());
    }

    g_requestedMenu = this;
    data.m_useCustomPosition = false;

    this->_createMenuWindow(true);
}

void Menu::showAt(float x, float y)
{
    auto& data = _getData<MenuData>();
    if (!this->getParent())
    {
        Style::getInstance().connectToGlobalStyle(this->shared_from_this());
    }

    g_requestedMenu = this;
    data.m_useCustomPosition = true;
    data.m_menuPositionX = x;
    data.m_menuPositionY = y;

    this->_createMenuWindow(true);
}

void Menu::tearAt(float x, float y)
{
    this->_setTeared(true);
    this->_showMenuWindow(x, y);
}

void Menu::hide()
{
    this->_setTeared(false);
    this->_setShown(false);
    this->_removeMenuWindowDeferred(true);
}

void Menu::invalidate()
{
    auto& data = _getData<MenuData>();
    data.m_childrenDirty = true;
    this->_menuHelperInvalidate();
}

std::shared_ptr<Menu> Menu::getCurrent()
{
    return g_currentMenu;
}

void Menu::_showMenuWindow(float x, float y)
{
    g_requestedMenu = this;

    auto& data = _getData<MenuData>();
    data.m_useCustomPosition = true;
    data.m_menuPositionX = x;
    data.m_menuPositionY = y;

    this->_createMenuWindow(false);
}

void Menu::_createMenuWindow(bool isPopupWindow)
{
    auto& data = _getData<MenuData>();
    if (!data.m_uiWindow)
    {
        // Reset width/height
        this->setComputedWidth(0.0f);
        this->setComputedHeight(0.0f);
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);

        auto uiWindowManager = PlatformRegistry::instance().windowCallbackManager();
        data.m_appWindow = Workspace::AppWindow::instance().getCurrent();
        data.m_uiWindow = ui::windowmanager::createAppWindowCallback(data.m_appWindow, uiWindowManager, data.m_popupUniqueId.c_str(),
                                                                0, 0, ui::windowmanager::DockPreference::eDisabled,
                                                                [this, isPopupWindow](float elapsedTime) {
                                                                    // It's OK to call it every frame. If the
                                                                    // width/height is not dirty, it will return right
                                                                    // away.
                                                                    this->setComputedWidth(0.0f);
                                                                    this->setComputedHeight(0.0f);

                                                                    this->_drawMenu(elapsedTime, true, isPopupWindow);
                                                                });
    }
}

void Menu::_removeMenuWindow(bool removeCurrent)
{
    auto& data = _getData<MenuData>();
    if (data.m_appWindow && data.m_uiWindow)
    {
        ui::windowmanager::IWindowCallbackManager* uiWindowManager =
            PlatformRegistry::instance().windowCallbackManager();
        uiWindowManager->removeAppWindowCallback(data.m_appWindow, data.m_uiWindow.get());
    }
    data.m_appWindow = nullptr;
    data.m_uiWindow = nullptr;

    if (removeCurrent && g_currentMenu.get() == this)
    {
        g_currentMenu = nullptr;
    }
}

void Menu::_removeMenuWindowDeferred(bool removeCurrent)
{
    auto& data = _getData<MenuData>();
    if (!data.m_appWindow || !data.m_uiWindow)
    {
        return;
    }

    auto* platform = PlatformRegistry::instance().platform();
    if (!platform)
    {
        // No platform available, remove immediately
        this->_removeMenuWindow(removeCurrent);
        return;
    }

    data.m_deferredOsWindowReleaseSubs = platform->deferToEndOfFrame(
        [weak_ref = this->weak_from_this(), removeCurrent]() {
            if (auto menu = std::static_pointer_cast<Menu>(weak_ref.lock()))
            {
                menu->_getData<MenuData>().m_deferredOsWindowReleaseSubs.reset();
                menu->_removeMenuWindow(removeCurrent);
            }
        });
}

void Menu::_verifyTitleFrame()
{
    auto& data = _getData<MenuData>();
    if (!data.m_titleDirty)
    {
        return;
    }
    data.m_titleDirty = false;

    if (this->isTearable())
    {
        OMNIKIT_WITH_CONTAINER(data.m_title)
        {
            this->_obtainDelegate(*this)->buildTitle(this);
        }
        OMNIKIT_WITH_CONTAINER(data.m_status)
        {
            this->_obtainDelegate(*this)->buildStatus(this);
        }
    }
    else
    {
        if (OMNIUI_LIKELY(data.m_title))
        {
            data.m_title->clear();
        }
        if (OMNIUI_LIKELY(data.m_status))
        {
            data.m_status->clear();
        }
    }
}

void Menu::_verifyChildren()
{
    auto& data = _getData<MenuData>();
    if (!data.m_childrenDirty || !this->hasOnBuildFn())
    {
        return;
    }
    data.m_childrenDirty = false;

    this->clear();

    OMNIKIT_WITH_CONTAINER(this->castShared())
    {
        this->callOnBuildFn();
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
