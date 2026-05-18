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

#include "IWindowCallbackManager.h"

#include <functional>
#include <memory>

namespace omni
{
namespace ui
{
namespace windowmanager
{

class LambdaEventListener : public IEventListener
{
public:
    LambdaEventListener(const std::function<void(float)>& fn) : m_fn(fn)
    {
    }

    void onDraw(float elapsedTime) override
    {
        if (m_fn)
            m_fn(elapsedTime);
    }

private:
    std::function<void(float)> m_fn;
};

inline IWindowCallbackPtr createWindowCallback(IWindowCallbackManager* windowCallbackManager,
                                               const char* title,
                                               uint32_t width,
                                               uint32_t height,
                                               DockPreference dockPreference,
                                               const std::function<void(float)>& onDrawFn)
{
    // The listener is passed as a raw pointer; the IWindowCallbackManager implementation
    // takes ownership (wraps it in a shared_ptr or similar).
    return windowCallbackManager->createWindowCallback(
        title, width, height, dockPreference, new LambdaEventListener(onDrawFn));
}

inline IWindowCallbackPtr createWindowSetCallback(WindowSet* windowSet,
                                                  IWindowCallbackManager* windowCallbackManager,
                                                  const char* title,
                                                  uint32_t width,
                                                  uint32_t height,
                                                  DockPreference dockPreference,
                                                  const std::function<void(float)>& onDrawFn)
{
    return windowCallbackManager->createWindowSetCallback(
        windowSet, title, width, height, dockPreference, new LambdaEventListener(onDrawFn));
}

inline IWindowCallbackPtr createAppWindowCallback(omni::ui::AppWindowHandle appWindow,
                                                  IWindowCallbackManager* windowCallbackManager,
                                                  const char* title,
                                                  uint32_t width,
                                                  uint32_t height,
                                                  DockPreference dockPreference,
                                                  const std::function<void(float)>& onDrawFn)
{
    return windowCallbackManager->createAppWindowCallback(
        appWindow, title, width, height, dockPreference, new LambdaEventListener(onDrawFn));
}

}
}
}
