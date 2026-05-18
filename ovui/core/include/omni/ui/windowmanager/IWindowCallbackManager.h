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

#include <omni/ui/platform/Log.h>
#include <omni/ui/Profile.h>
#include <omni/ui/Types.h>

#include <cstdint>
#include <cstring>
#include <memory>
#include <string_view>


namespace omni
{
namespace ui
{
namespace windowmanager
{

enum class DockPreference : uint32_t
{
    eDisabled,
    eMain,
    eRight,
    eLeft,
    eRightTop,
    eRightBottom,
    eLeftBottom
};

/**
 * Interface to implement for event listener.
 */
class IEventListener
{
public:
    virtual ~IEventListener() = default;
    virtual void onDraw(float elapsedTime) = 0;
};

using IEventListenerPtr = std::shared_ptr<IEventListener>;

struct WindowSet;

class IWindowCallback
{
public:
    virtual ~IWindowCallback() = default;

    virtual const char* getTitle() = 0;
    virtual uint32_t getWidth() = 0;
    virtual uint32_t getHeight() = 0;
    virtual DockPreference getDockPreference() = 0;
    virtual WindowSet* getWindowSet() = 0;
    virtual omni::ui::AppWindowHandle getAppWindow() = 0;

    virtual void draw(float elapsedTime) = 0;
};

using IWindowCallbackPtr = std::shared_ptr<IWindowCallback>;

class IWindowCallbackManager
{
public:
    virtual ~IWindowCallbackManager() = default;

    virtual IWindowCallback* createWindowCallbackPtr(
        const char* title, uint32_t width, uint32_t height, DockPreference dockPreference, IEventListener* listener) = 0;

    virtual IWindowCallbackPtr createWindowCallback(
        const char* title, uint32_t width, uint32_t height, DockPreference dockPreference, IEventListener* listener)
    {
        return IWindowCallbackPtr(this->createWindowCallbackPtr(title, width, height, dockPreference, listener));
    }

    virtual void removeWindowCallback(IWindowCallback* windowCallback) = 0;

    virtual size_t getWindowCallbackCount() = 0;
    virtual IWindowCallback* getWindowCallbackAt(size_t index) = 0;

    inline void drawWindows(float elapsedTime);
    inline IWindowCallback* findWindowCallbackByName(const char* name);


    virtual WindowSet* createWindowSet() = 0;
    virtual void destroyWindowSet(WindowSet* windowSet) = 0;
    virtual WindowSet* getDefaultWindowSet() = 0;

    virtual void attachWindowSetToAppWindow(WindowSet* windowSet, omni::ui::AppWindowHandle appWindow) = 0;
    virtual WindowSet* getWindowSetByAppWindow(omni::ui::AppWindowHandle appWindow) = 0;
    virtual omni::ui::AppWindowHandle getAppWindowFromWindowSet(WindowSet* windowSet) = 0;

    virtual size_t getWindowSetCount() = 0;
    virtual WindowSet* getWindowSetAt(size_t index) = 0;

    virtual IWindowCallback* createWindowSetCallbackPtr(WindowSet* windowSet,
                                                        const char* title,
                                                        uint32_t width,
                                                        uint32_t height,
                                                        DockPreference dockPreference,
                                                        IEventListener* listener) = 0;

    virtual IWindowCallbackPtr createWindowSetCallback(WindowSet* windowSet,
                                               const char* title,
                                               uint32_t width,
                                               uint32_t height,
                                               DockPreference dockPreference,
                                               IEventListener* listener)
    {
        return IWindowCallbackPtr(this->createWindowSetCallbackPtr(windowSet, title, width, height, dockPreference, listener));
    }

    IWindowCallbackPtr createAppWindowCallback(omni::ui::AppWindowHandle appWindow,
                                               const char* title,
                                               uint32_t width,
                                               uint32_t height,
                                               DockPreference dockPreference,
                                               IEventListener* listener)
    {
        WindowSet* windowSet = this->getWindowSetByAppWindow(appWindow);
        if (!windowSet)
        {
            OMNIUI_LOG_WARN("createAppWindowCallback: No window set attached to supplied app window!");
            return IWindowCallbackPtr();
        }
        return this->createWindowSetCallback(windowSet, title, width, height, dockPreference, listener);
    }

    virtual void addWindowSetCallback(WindowSet* windowSet, IWindowCallback* windowCallback) = 0;

    virtual void removeWindowSetCallback(WindowSet* windowSet, IWindowCallback* windowCallback) = 0;

    void removeAppWindowCallback(omni::ui::AppWindowHandle appWindow, IWindowCallback* windowCallback)
    {
        WindowSet* windowSet = this->getWindowSetByAppWindow(appWindow);
        if (!windowSet)
        {
            OMNIUI_LOG_WARN("removeAppWindowCallback: No window set attached to supplied app window!");
            return;
        }
        this->removeWindowSetCallback(windowSet, windowCallback);
    }

    void moveCallbackToAppWindow(IWindowCallback* windowCallback, omni::ui::AppWindowHandle newAppWindow)
    {
        WindowSet* newWindowSet = this->getWindowSetByAppWindow(newAppWindow);
        if (!newWindowSet)
        {
            OMNIUI_LOG_WARN("moveCallbackToAppWindow: No window set attached to supplied app window!");
            return;
        }
        WindowSet* oldWindowSet = windowCallback->getWindowSet();
        this->removeWindowSetCallback(oldWindowSet, windowCallback);
        this->addWindowSetCallback(newWindowSet, windowCallback);
    }

    virtual size_t getWindowSetCallbackCount(WindowSet* windowSet) = 0;
    virtual IWindowCallback* getWindowSetCallbackAt(WindowSet* windowSet, size_t index) = 0;

    inline void drawWindowSet(WindowSet* windowSet, float elapsedTime);
    inline IWindowCallback* findWindowSetCallbackByName(WindowSet* windowSet, const char* name);
};

inline void IWindowCallbackManager::drawWindows(float elapsedTime)
{
    WindowSet* windowSet = getDefaultWindowSet();
    drawWindowSet(windowSet, elapsedTime);
}

inline IWindowCallback* IWindowCallbackManager::findWindowCallbackByName(const char* name)
{
    WindowSet* windowSet = getDefaultWindowSet();
    return findWindowSetCallbackByName(windowSet, name);
}

inline void IWindowCallbackManager::drawWindowSet(WindowSet* windowSet, float elapsedTime)
{
    size_t windowCallbackCount = getWindowSetCallbackCount(windowSet);
    omni::ui::windowmanager::IWindowCallback* editorMenuCallback = nullptr;

    for (size_t idx = 0; idx < windowCallbackCount; ++idx)
    {
        omni::ui::windowmanager::IWindowCallback* windowCallback = getWindowSetCallbackAt(windowSet, idx);
        if (windowCallback)
        {
            if (!editorMenuCallback && strcmp(windowCallback->getTitle(), "[editor_menu_hookup]") == 0)
            {
                // HACK, draw [editor_menu_hookup] last so MainWindow menu goes before it
                editorMenuCallback = windowCallback;
                continue;
            }
            OMNIUI_PROFILE_ZONE("'%s' ext window[new]", windowCallback->getTitle());
            windowCallback->draw(elapsedTime);
        }
    }
    if (editorMenuCallback)
    {
        OMNIUI_PROFILE_ZONE("[editor_menu_hookup] ext window[new]", editorMenuCallback->getTitle());
        editorMenuCallback->draw(elapsedTime);
    }
}

inline IWindowCallback* IWindowCallbackManager::findWindowSetCallbackByName(WindowSet* windowSet, const char* name)
{
    size_t nameLen = std::string_view(name).size();
    size_t windowCallbackCount = getWindowSetCallbackCount(windowSet);
    for (size_t idx = 0; idx < windowCallbackCount; ++idx)
    {
        omni::ui::windowmanager::IWindowCallback* windowCallback = getWindowSetCallbackAt(windowSet, idx);
        if (windowCallback && (strncmp(windowCallback->getTitle(), name, nameLen) == 0))
        {
            return windowCallback;
        }
    }
    return nullptr;
}

} // windowmanager
} // ui
} // omni
