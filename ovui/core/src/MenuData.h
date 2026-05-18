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
#include <omni/ui/Menu.h>
#include "platform/IUiPlatform.h"

#include "StackData.h"

#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct Menu::MenuData : public Stack::StackData
{
    ~MenuData() override;

    // The pointer to the popup window in the underlying windowing system.
    omni::ui::windowmanager::IWindowCallbackPtr m_uiWindow;
    AppWindowHandle m_appWindow = nullptr;

    Menu* m_parentMenu = nullptr;

    // Internal unique name of the popup window. It should never be expanded to the user.
    std::string m_menuUniqueId;
    std::string m_popupUniqueId;

    DeferHandle m_deferredOsWindowReleaseSubs;

    std::shared_ptr<Frame> m_title;
    std::shared_ptr<Frame> m_status;

    float m_menuPositionX = 0.0f;
    float m_menuPositionY = 0.0f;

    float m_windowMovedDistanceX = 0.0f;
    float m_windowMovedDistanceY = 0.0f;
    float m_windowPosBeforeMoveX = 0.0f;
    float m_windowPosBeforeMoveY = 0.0f;

    float m_computedWindowWidth = 0.0f;
    float m_computedWindowHeight = 0.0f;

    bool m_titleDirty = true;

    bool m_childrenDirty = true;

    // For specific Menu Positioning. Unit: points.
    bool m_useCustomPosition = false;

    // Internal flags for drawing in popup window.
    bool m_isPopupBasedCompatibility = false;
    bool m_requestToPopupCompatibility = false;

    // True when the user is moving the window.
    bool m_windowIsMoving = false;

    bool m_deprecatedWarningShown = false;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
