/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "NativeTiming.h"

#include <atomic>

namespace omni::ui::standalone
{

namespace
{
std::atomic<const NativeTimingHooks*> g_nativeTimingHooks{ nullptr };
} // namespace

void setNativeTimingHooks(const NativeTimingHooks* hooks)
{
    if (hooks && (hooks->structSize < sizeof(NativeTimingHooks) || hooks->version != kNativeTimingHooksVersion))
    {
        hooks = nullptr;
    }
    g_nativeTimingHooks.store(hooks, std::memory_order_release);
}

const NativeTimingHooks* getNativeTimingHooks()
{
    return g_nativeTimingHooks.load(std::memory_order_acquire);
}

} // namespace omni::ui::standalone
