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

    Int2 m_mouseDragPoint = {};
    Int2 m_mouseDelta = {};

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

    // we have some marker to tack os window move and timing
    bool m_osWindowMoving = false;
    bool m_mouseWasDragging = false;

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
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
