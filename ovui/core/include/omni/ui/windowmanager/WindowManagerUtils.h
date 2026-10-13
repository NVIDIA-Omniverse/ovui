/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
    // The manager retains the listener; the temporary owns the initial reference.
    return windowCallbackManager->createWindowCallback(
        title, width, height, dockPreference, takeCallbackReference(new LambdaEventListener(onDrawFn)).get());
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
        windowSet, title, width, height, dockPreference, takeCallbackReference(new LambdaEventListener(onDrawFn)).get());
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
        appWindow, title, width, height, dockPreference, takeCallbackReference(new LambdaEventListener(onDrawFn)).get());
}

}
}
}
