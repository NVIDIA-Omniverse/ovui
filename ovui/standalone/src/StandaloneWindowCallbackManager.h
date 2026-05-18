/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

// Minimal IWindowCallbackManager for standalone mode.
#pragma once

#include <omni/ui/windowmanager/IWindowCallbackManager.h>
#include <algorithm>
#include <string>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

/// A concrete IWindowCallback that wraps an IEventListener.
class StandaloneWindowCallback final : public windowmanager::IWindowCallback
{
public:
    StandaloneWindowCallback(const char* title, uint32_t width, uint32_t height,
                             windowmanager::DockPreference dockPref,
                             windowmanager::IEventListener* listener,
                             windowmanager::WindowSet* windowSet)
        : m_title(title ? title : "")
        , m_width(width)
        , m_height(height)
        , m_dockPref(dockPref)
        , m_listener(listener)
        , m_windowSet(windowSet)
    {
    }

    const char* getTitle() override { return m_title.c_str(); }
    uint32_t getWidth() override { return m_width; }
    uint32_t getHeight() override { return m_height; }
    windowmanager::DockPreference getDockPreference() override { return m_dockPref; }
    windowmanager::WindowSet* getWindowSet() override { return m_windowSet; }
    omni::ui::AppWindowHandle getAppWindow() override { return nullptr; }

    void draw(float elapsedTime) override
    {
        if (m_listener)
            m_listener->onDraw(elapsedTime);
    }

private:
    std::string m_title;
    uint32_t m_width;
    uint32_t m_height;
    windowmanager::DockPreference m_dockPref;
    windowmanager::IEventListenerPtr m_listener;
    windowmanager::WindowSet* m_windowSet;
};

/// Minimal IWindowCallbackManager. Uses a single default WindowSet.
/// All appWindow-based lookups map to the default set (since standalone has one window).
class StandaloneWindowCallbackManager final : public windowmanager::IWindowCallbackManager
{
public:
    StandaloneWindowCallbackManager()
    {
        // Create the default window set (just a tag; we use a sentinel pointer)
        m_defaultWindowSet = reinterpret_cast<windowmanager::WindowSet*>(&m_sentinel);
    }

    ~StandaloneWindowCallbackManager() = default;

    // ---- IWindowCallbackManager pure virtuals ----

    windowmanager::IWindowCallback* createWindowCallbackPtr(
        const char* title, uint32_t width, uint32_t height,
        windowmanager::DockPreference dockPreference,
        windowmanager::IEventListener* listener) override
    {
        return createWindowSetCallbackPtr(m_defaultWindowSet, title, width, height, dockPreference, listener);
    }

    void removeWindowCallback(windowmanager::IWindowCallback* windowCallback) override
    {
        removeWindowSetCallback(m_defaultWindowSet, windowCallback);
    }

    size_t getWindowCallbackCount() override
    {
        return getWindowSetCallbackCount(m_defaultWindowSet);
    }

    windowmanager::IWindowCallback* getWindowCallbackAt(size_t index) override
    {
        return getWindowSetCallbackAt(m_defaultWindowSet, index);
    }

    // ---- WindowSet management ----

    windowmanager::WindowSet* createWindowSet() override
    {
        // Standalone only supports one window set
        return m_defaultWindowSet;
    }

    void destroyWindowSet(windowmanager::WindowSet* /*windowSet*/) override
    {
        // No-op for standalone
    }

    windowmanager::WindowSet* getDefaultWindowSet() override
    {
        return m_defaultWindowSet;
    }

    void attachWindowSetToAppWindow(windowmanager::WindowSet* /*windowSet*/,
                                    omni::ui::AppWindowHandle /*appWindow*/) override
    {
        // No-op: standalone has one window set
    }

    windowmanager::WindowSet* getWindowSetByAppWindow(omni::ui::AppWindowHandle /*appWindow*/) override
    {
        // Always return the default set
        return m_defaultWindowSet;
    }

    omni::ui::AppWindowHandle getAppWindowFromWindowSet(windowmanager::WindowSet* /*windowSet*/) override
    {
        return nullptr;
    }

    size_t getWindowSetCount() override { return 1; }

    windowmanager::WindowSet* getWindowSetAt(size_t index) override
    {
        return (index == 0) ? m_defaultWindowSet : nullptr;
    }

    windowmanager::IWindowCallback* createWindowSetCallbackPtr(
        windowmanager::WindowSet* windowSet,
        const char* title, uint32_t width, uint32_t height,
        windowmanager::DockPreference dockPreference,
        windowmanager::IEventListener* listener) override
    {
        auto* cb = new StandaloneWindowCallback(title, width, height, dockPreference, listener,
                                                 windowSet ? windowSet : m_defaultWindowSet);
        m_callbacks.push_back(cb);
        return cb;
    }

    void addWindowSetCallback(windowmanager::WindowSet* /*windowSet*/,
                              windowmanager::IWindowCallback* windowCallback) override
    {
        if (windowCallback)
        {
            // Avoid duplicates
            auto it = std::find(m_callbacks.begin(), m_callbacks.end(), windowCallback);
            if (it == m_callbacks.end())
                m_callbacks.push_back(windowCallback);
        }
    }

    void removeWindowSetCallback(windowmanager::WindowSet* /*windowSet*/,
                                 windowmanager::IWindowCallback* windowCallback) override
    {
        auto it = std::find(m_callbacks.begin(), m_callbacks.end(), windowCallback);
        if (it != m_callbacks.end())
            m_callbacks.erase(it);
    }

    size_t getWindowSetCallbackCount(windowmanager::WindowSet* /*windowSet*/) override
    {
        return m_callbacks.size();
    }

    windowmanager::IWindowCallback* getWindowSetCallbackAt(windowmanager::WindowSet* /*windowSet*/,
                                                           size_t index) override
    {
        if (index < m_callbacks.size())
            return m_callbacks[index];
        return nullptr;
    }

    size_t callbackCount() const { return m_callbacks.size(); }
    void clearCallbacks() { m_callbacks.clear(); }

    // ---- Draw all registered windows (called from tick) ----
    void drawAllWindows(float elapsedTime)
    {
        for (size_t i = 0; i < m_callbacks.size(); ++i)
        {
            if (m_callbacks[i])
            {
                m_callbacks[i]->draw(elapsedTime);
            }
        }
    }

private:
    int m_sentinel = 0; // Address used as WindowSet* tag
    windowmanager::WindowSet* m_defaultWindowSet = nullptr;
    std::vector<windowmanager::IWindowCallback*> m_callbacks;
};

/// Global accessor for the standalone window callback manager.
/// Set during init(), cleared during shutdown().
StandaloneWindowCallbackManager* getStandaloneWindowCallbackManager();
void setStandaloneWindowCallbackManager(StandaloneWindowCallbackManager* mgr);

} // namespace standalone
} // namespace ui
} // namespace omni
