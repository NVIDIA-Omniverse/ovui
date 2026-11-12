/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

// Thread check of the changing calls of image providers. Internal: not part of the public API.

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <thread>

namespace omni
{
namespace ui
{

class ImageProvider;

/**
 * @brief Removes the changes of a provider that is destroyed, from the queue of publishOnUiThread().
 *
 * When a change of the provider runs on another thread, it waits until that change has ended, with no time
 * limit (a change can still use the provider). It also forgets the off-UI-thread report of providerId, so
 * the set of reported providers does not grow. Call it at the start of the destructor of a provider class,
 * before the destructor releases anything that a change can use. A second call does nothing.
 */
void forgetImageProviderPublications(const ImageProvider* provider, uint32_t providerId);

/**
 * @brief The frame boundary of ImageProvider::publishOnUiThread(): runs the waiting changes at most once in
 *        an ImGui frame.
 *
 * ImageWithProvider calls it before it draws. It does nothing when ImageProvider::applyPublishedUpdates()
 * already ran in this ImGui frame: the standalone platforms call that after ImGui::NewFrame() and before any
 * window is drawn, so in them the changes run once, before anything is drawn. A host that does not call it
 * gets one pass here, at the first ImageWithProvider of the frame.
 */
size_t applyPublishedUpdatesOncePerFrame();

/// The thread that last called ImageProvider::applyPublishedUpdates(). A default id: no UI frame ran yet.
extern std::atomic<std::thread::id> g_imageProviderUiThread;

/**
 * @brief Checks one changing call of an image provider against the UI thread.
 *
 * Put one at the start of each public changing function. Only the outermost scope on a thread checks,
 * so a changing function that calls another one is reported once. A scope with no function name checks
 * nothing and also stops the checks of the calls inside it: destructors use it, because a provider that
 * nothing can draw any more can be destroyed on any thread.
 */
class ImageProviderChangeScope
{
public:
    ImageProviderChangeScope(uint32_t providerId, const char* function)
    {
        if (!function)
        {
            _enterWithoutCheck();
            return;
        }
        // The usual case costs one atomic load and no thread-local access: a call on the UI thread, or
        // a call before the first UI frame.
        const std::thread::id uiThread = g_imageProviderUiThread.load(std::memory_order_relaxed);
        if (uiThread == std::thread::id() || uiThread == std::this_thread::get_id())
            return;
        _enterOffUiThread(providerId, function);
    }

    ~ImageProviderChangeScope()
    {
        if (m_entered)
            _exitScope();
    }

    ImageProviderChangeScope(const ImageProviderChangeScope&) = delete;
    ImageProviderChangeScope& operator=(const ImageProviderChangeScope&) = delete;

private:
    void _enterWithoutCheck();
    void _enterOffUiThread(uint32_t providerId, const char* function);
    // Not "_leave": MSVC reads that name as its keyword __leave.
    void _exitScope();

    bool m_entered = false;
};

} // namespace ui
} // namespace omni
