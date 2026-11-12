/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "platform/IUiPlatform.h"
#include <omni/ui/Window.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Window::WindowData
{
    WindowData(Window::DockPreference dockPref) : m_dockingPreference(dockPref) {}
    virtual ~WindowData();

    const Window::DockPreference m_dockingPreference;

    AppWindowHandle m_appWindow = nullptr;
    omni::ui::windowmanager::IWindowCallbackPtr m_uiWindow = {};

    // Deferred destruction handle (cancels when released)
    DeferHandle m_deferredDestroyHandle;
    // Observer handle for app window close event (cancels when released)
    DeferHandle m_windowCloseObserverHandle;

    // Where inside the OS window the title bar drag was grabbed, in window-relative coordinates.
    // Only meaningful while m_osWindowMoving is set. See Window::_updateOSWindowDrag().
    Int2 m_osWindowGrabOffset = {};

    uint32_t m_pushedColorCount = { 0 };
    uint32_t m_pushedFloatCount = { 0 };

    float m_prevContentRegionWidth = 0.0f;
    float m_prevContentRegionHeight = 0.0f;

    // The name of the window we need to dock when it will appear.
    std::string m_deferredDocking;
    DockPolicy m_deferredDockingMakeTargetActive = DockPolicy::eDoNothing;

    // we only support this when in the new kit stack, we might also want to make it a setting
    bool m_multiOSWindowSupport = false;
    bool m_enableWindowDetach = false;

    // True while a title bar drag is moving the detached OS window.
    bool m_osWindowMoving = false;

    // True when the detached OS window this Window drives was created with window manager
    // decorations, i.e. /exts/omni.ui/Window/detachedDecorations was set at detach time. The WM
    // then owns move and resize, and omni.ui must not drive them itself. Reset by
    // Window::notifyAppWindowChange() whenever the Window changes app window.
    bool m_osWindowDecorated = false;

    bool m_positionExplicitlyChanged = false;
    bool m_sizeExplicitlyChanged = false;

    // We need it for multi-modal windows because when the modal window is just created, ImGui puts it to (60, 60) and
    // the second frame the position is correct. We need to know when it's the first frame of the modal window.
    bool m_wasModalPreviousFrame = false;
    bool m_wasVisiblePreviousFrame = false;
    bool m_firstAppearance = true;

    // True if the title bar context menu is open.
    bool m_titleMenuOpened = false;

    bool m_destroyed = false;

    // True if the previous frame is visible
    bool m_wasPreviousShowItems = false;

    // Python module name that constructed this Window, captured at Python binding time
    // (e.g. "omni.kit.window.console"). Empty when created from C++ or unattributable.
    std::string m_ownerModule;

    // First-interaction telemetry latch. Set once a user mouse-click is observed inside this
    // Window so we only fire onWindowFirstInteraction once per Window lifetime.
    bool m_firstInteractionReported = false;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
