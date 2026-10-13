/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/bind/PlatformHooks.h>
#include <omni/ui/platform/WidgetHost.h>

#include <atomic>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{
std::atomic<const PlatformHooks*> s_platformHooks{ nullptr };
std::atomic<WidgetSurfaceFactory> s_widgetHost{ nullptr };
}

void setPlatformHooks(const PlatformHooks* hooks)
{
    s_platformHooks.store(hooks);
}

void resetPlatformHooks()
{
    s_platformHooks.store(nullptr);
}

const PlatformHooks* getPlatformHooks()
{
    return s_platformHooks.load();
}

void setWidgetHost(WidgetSurfaceFactory factory)
{
    s_widgetHost.store(factory);
}

WidgetSurfaceFactory getWidgetHost()
{
    return s_widgetHost.load();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
