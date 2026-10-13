/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

// Optional native timing scopes. Each scope calls the hooks that an optional
// package installs with setNativeTimingHooks(); without hooks a scope does
// nothing. The standalone Python module exposes the setter as
// `_set_native_timing_hooks(capsule)`.

#include <omni/ui/Api.h>

#include <cstdint>

namespace omni::ui::standalone
{

inline constexpr uint32_t kNativeTimingHooksVersion = 1U;
inline constexpr char kNativeTimingHooksCapsuleName[] = "omni.ui.native_timing_hooks";

/** Function table for optional native timing. Every function may be null. */
struct NativeTimingHooks
{
    uint32_t structSize;
    uint32_t version;
    /** Start a scope on this thread. `cachedId` is 0 the first time at each call site and thread. */
    bool (*beginScope)(const char* name, uint32_t* cachedId);
    void (*endScope)(uint32_t cachedId);
    /** Start and end the time of one render-thread iteration. */
    bool (*beginRenderThreadScope)();
    void (*endRenderThreadScope)();
    /** Start and end a named initialization phase. */
    bool (*beginPhase)(const char* name);
    void (*endPhase)(const char* name);
};

/** Install `hooks` (or remove them with nullptr). The table must stay alive. */
OMNIUI_API void setNativeTimingHooks(const NativeTimingHooks* hooks);
OMNIUI_API const NativeTimingHooks* getNativeTimingHooks();

inline constexpr char kOvuiInitPhaseName[] = "OVUI Init";
inline constexpr char kGlfwInitPhaseName[] = "GLFW Init";
inline constexpr char kVulkanInitPhaseName[] = "Vulkan Init";
inline constexpr char kOpenGlInitPhaseName[] = "OpenGL Init";
inline constexpr char kImGuiInitPhaseName[] = "ImGui Init";
inline constexpr char kOvrtxIntegrationInitPhaseName[] = "OVRTX Integration Init";

class NativeTimingScope final
{
public:
    NativeTimingScope(const char* name, uint32_t& cachedId)
    {
        const NativeTimingHooks* hooks = getNativeTimingHooks();
        if (hooks && hooks->beginScope && hooks->endScope && name && hooks->beginScope(name, &cachedId))
        {
            m_hooks = hooks;
            m_id = cachedId;
        }
    }

    ~NativeTimingScope()
    {
        if (m_hooks)
        {
            m_hooks->endScope(m_id);
        }
    }

    NativeTimingScope(const NativeTimingScope&) = delete;
    NativeTimingScope& operator=(const NativeTimingScope&) = delete;

private:
    const NativeTimingHooks* m_hooks = nullptr;
    uint32_t m_id = 0;
};

class NativeRenderThreadScope final
{
public:
    NativeRenderThreadScope()
    {
        const NativeTimingHooks* hooks = getNativeTimingHooks();
        if (hooks && hooks->beginRenderThreadScope && hooks->endRenderThreadScope &&
            hooks->beginRenderThreadScope())
        {
            m_hooks = hooks;
        }
    }

    ~NativeRenderThreadScope()
    {
        if (m_hooks)
        {
            m_hooks->endRenderThreadScope();
        }
    }

    NativeRenderThreadScope(const NativeRenderThreadScope&) = delete;
    NativeRenderThreadScope& operator=(const NativeRenderThreadScope&) = delete;

private:
    const NativeTimingHooks* m_hooks = nullptr;
};

class NativePhaseScope final
{
public:
    explicit NativePhaseScope(const char* name) : m_name(name)
    {
        const NativeTimingHooks* hooks = getNativeTimingHooks();
        if (hooks && hooks->beginPhase && hooks->endPhase && hooks->beginPhase(name))
        {
            m_hooks = hooks;
        }
    }

    ~NativePhaseScope()
    {
        stop();
    }

    void stop()
    {
        if (m_hooks)
        {
            m_hooks->endPhase(m_name);
            m_hooks = nullptr;
        }
    }

    NativePhaseScope(const NativePhaseScope&) = delete;
    NativePhaseScope& operator=(const NativePhaseScope&) = delete;

private:
    const NativeTimingHooks* m_hooks = nullptr;
    const char* m_name = nullptr;
};

// Older name used by shared core sources.
using OvuiDevelopmentMetricTimeScope = NativeTimingScope;

} // namespace omni::ui::standalone

#define OVUI_DEVELOPMENT_TIME_SCOPE(variableName, metricName)                                         \
    static thread_local uint32_t variableName##TimingId = 0;                                          \
    ::omni::ui::standalone::NativeTimingScope variableName                                            \
    {                                                                                                  \
        metricName, variableName##TimingId                                                             \
    }
#define OVUI_NESTED_DEVELOPMENT_TIME_SCOPE(variableName, metricName) \
    OVUI_DEVELOPMENT_TIME_SCOPE(variableName, metricName)
#define OVUI_RENDER_THREAD_TIME_SCOPE(variableName) ::omni::ui::standalone::NativeRenderThreadScope variableName
#define OVUI_PERFORMANCE_PHASE_SCOPE(variableName, phaseName) \
    ::omni::ui::standalone::NativePhaseScope variableName{ phaseName }
#define OVUI_PERFORMANCE_PHASE_STOP(variableName) variableName.stop()
