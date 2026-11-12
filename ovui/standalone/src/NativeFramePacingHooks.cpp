/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "NativeFramePacingHooks.h"

#include <atomic>

namespace omni::ui::standalone
{

namespace
{
std::atomic<const NativeFramePacingHooks*> g_nativeFramePacingHooks{ nullptr };

bool complete(const NativeFramePacingHooks* hooks)
{
    return hooks->openRenderer && hooks->pauseRenderWorker && hooks->resumeRenderWorker && hooks->closeRenderer &&
           hooks->shutdownWorker && hooks->readRendererInfo && hooks->lastError && hooks->queryCapabilities &&
           hooks->cancel;
}
} // namespace

bool setNativeFramePacingHooks(const NativeFramePacingHooks* hooks)
{
    bool accepted = true;
    if (hooks && (hooks->structSize < sizeof(NativeFramePacingHooks) ||
                  hooks->version != kNativeFramePacingHooksVersion || !complete(hooks)))
    {
        // A partial table would fail inside the render worker instead of at
        // installation, so refuse it here.
        hooks = nullptr;
        accepted = false;
    }
    g_nativeFramePacingHooks.store(hooks, std::memory_order_release);
    return accepted;
}

const NativeFramePacingHooks* getNativeFramePacingHooks()
{
    return g_nativeFramePacingHooks.load(std::memory_order_acquire);
}

bool sendNativeFramePacingCancel(uint64_t token)
{
    const NativeFramePacingHooks* hooks = getNativeFramePacingHooks();
    if (!hooks)
        return false;
    hooks->cancel(token);
    return true;
}

} // namespace omni::ui::standalone
