/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/ImageProvider/PresentationKeyGuard.h>

#include "PresentationKeyState.h"

#include "../platform/IImageProviderRenderer.h"
#include "../platform/Log.h"
#include "../platform/PlatformRegistry.h"

#include <imgui.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <deque>
#include <map>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace omni
{
namespace ui
{

namespace
{
// The state of one presentation key. A record exists while a provider holds the key. When the last
// provider lets the key go, the feed is done: a record whose key was given out stays for
// kReleasedPresentationKeyPasses guard passes and is then freed; any other record is freed at once.
struct KeyRecord
{
    size_t holders = 0;           // providers that hold the key now
    bool retired = false;         // the feeder retired the key; a new hold clears it
    std::vector<void*> renderers; // renderers with which getImGuiReference() gave the key out
    uint64_t releasedPass = 0;    // guard pass of the last release; used while holders == 0
};

// A released record that waits for its last passes.
struct Released
{
    uint64_t key;
    uint64_t pass; // guard pass of the release
    int frame;     // ImGui frame of the release, -1 without an ImGui context
};

std::mutex s_keyMutex;
std::unordered_map<uint64_t, KeyRecord> s_keys;
// Released records that wait for their last passes, oldest first.
std::deque<Released> s_released;
uint64_t s_guardPass = 0; // number of guard passes that started
// Keys whose commands were removed in the last pass. Used to write one log line for each transition.
std::map<uint64_t, PresentationKeyFallback> s_droppingKeys;

// The ImGui frame that is being built, or -1 when there is no ImGui context.
int currentImGuiFrame()
{
    return ImGui::GetCurrentContext() ? ImGui::GetFrameCount() : -1;
}

// Frees a released record, unless a provider holds the key again or it was released again later.
void freeReleasedLocked(const Released& entry)
{
    auto it = s_keys.find(entry.key);
    if (it != s_keys.end() && it->second.holders == 0 && it->second.releasedPass == entry.pass)
        s_keys.erase(it);
}

// A record may be freed before its last passes only when no draw data that waits for the guard can hold its
// key. A host that calls the guard in each frame frees the record after its passes, within
// kReleasedPresentationKeyPasses frames. So when more ImGui frames than that started after the release, the
// host draws its frames without the guard. Without an ImGui context, no frame is being built.
bool mayFreeBeforeLastPassesLocked(const Released& entry)
{
    const int frame = currentImGuiFrame();
    return entry.frame < 0 || frame < 0 || frame - entry.frame > static_cast<int>(kReleasedPresentationKeyPasses);
}

void addReleasedLocked(uint64_t key, KeyRecord& record)
{
    record.releasedPass = s_guardPass;
    s_released.push_back({ key, s_guardPass, currentImGuiFrame() });
    // A host that never calls the guard never ends the passes, so the count has a limit too. The limit never
    // frees a record whose key can still be in draw data that waits for the guard: then there are more records
    // for a short time, and the guard frees them after their passes.
    while (s_released.size() > kMaxReleasedPresentationKeys && mayFreeBeforeLastPassesLocked(s_released.front()))
    {
        freeReleasedLocked(s_released.front());
        s_released.pop_front();
    }
}

std::atomic<uint64_t (*)()> s_clock{ nullptr };
// 0: no lease (the default). A key stays in use until it is retired or the renderer reports it
// unmapped, however slowly its feed delivers frames. A host can opt in to a lease.
std::atomic<uint32_t> s_leaseMs{ 0 };
}

const char* presentationKeyFallbackText(PresentationKeyFallback reason)
{
    switch (reason)
    {
    case PresentationKeyFallback::eRetired:
        return "the key was retired";
    case PresentationKeyFallback::eUnmapped:
        return "the renderer reports the key as unmapped";
    case PresentationKeyFallback::eNotMapped:
        return "the renderer does not report the key as mapped";
    case PresentationKeyFallback::eExpired:
        return "the key expired (no new frame within the lease)";
    default:
        return "none";
    }
}

void setPresentationKeyClock(uint64_t (*nowNs)())
{
    s_clock.store(nowNs);
}

uint64_t presentationKeyNowNs()
{
    auto* clock = s_clock.load();
    if (clock)
        return clock();
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch())
            .count());
}

void setPresentationKeyLeaseMs(uint32_t ms)
{
    s_leaseMs.store(ms);
}

uint32_t getPresentationKeyLeaseMs()
{
    return s_leaseMs.load();
}

void holdPresentationKey(uint64_t key)
{
    std::lock_guard<std::mutex> g(s_keyMutex);
    KeyRecord& record = s_keys[key];
    ++record.holders;
    record.retired = false;
}

void releasePresentationKey(uint64_t key)
{
    std::lock_guard<std::mutex> g(s_keyMutex);
    auto it = s_keys.find(key);
    if (it == s_keys.end() || it->second.holders == 0 || --it->second.holders != 0)
        return;
    // The feed of the key is done. A key that was never given out cannot be drawn: free it now.
    // Otherwise the guard checks it in the next passes, for a widget that drew it in this frame.
    if (it->second.renderers.empty())
        s_keys.erase(it);
    else
        addReleasedLocked(key, it->second);
}

void retirePresentationKey(uint64_t key)
{
    // A key without a record has no provider and no reference that the guard still checks.
    std::lock_guard<std::mutex> g(s_keyMutex);
    auto it = s_keys.find(key);
    if (it != s_keys.end())
        it->second.retired = true;
}

bool isPresentationKeyRetired(uint64_t key)
{
    std::lock_guard<std::mutex> g(s_keyMutex);
    auto it = s_keys.find(key);
    return it != s_keys.end() && it->second.retired;
}

void recordIssuedPresentationKey(void* renderer, uint64_t key)
{
    std::lock_guard<std::mutex> g(s_keyMutex);
    auto it = s_keys.find(key);
    const bool held = it != s_keys.end();
    if (!held)
        it = s_keys.emplace(key, KeyRecord{}).first;
    auto& renderers = it->second.renderers;
    if (std::find(renderers.begin(), renderers.end(), renderer) == renderers.end())
        renderers.push_back(renderer);
    // No provider holds the key: keep it only for the passes of a released key.
    if (!held)
        addReleasedLocked(key, it->second);
}

void resetPresentationKeyGuardForTest()
{
    {
        std::lock_guard<std::mutex> g(s_keyMutex);
        s_keys.clear();
        s_released.clear();
        s_droppingKeys.clear();
        s_guardPass = 0;
    }
    s_clock.store(nullptr);
}

size_t dropUnmappedPresentationKeys(ImDrawData* drawData)
{
    if (!drawData)
    {
        return 0;
    }

    // Each pass checks every key that was given out and is still held, so a reference that a client
    // kept is checked too. The records of done feeds are freed after their last passes.
    struct Issued
    {
        void* renderer;
        uint64_t key;
        bool retired;
    };
    std::vector<Issued> issued;
    {
        std::lock_guard<std::mutex> g(s_keyMutex);
        ++s_guardPass;
        while (!s_released.empty() && s_guardPass - s_released.front().pass > kReleasedPresentationKeyPasses)
        {
            freeReleasedLocked(s_released.front());
            s_released.pop_front();
        }
        for (const auto& entry : s_keys)
        {
            for (void* renderer : entry.second.renderers)
                issued.push_back({ renderer, entry.first, entry.second.retired });
        }
        if (issued.empty())
        {
            s_droppingKeys.clear();
            return 0;
        }
    }

    std::map<uint64_t, PresentationKeyFallback> unmapped;
    {
        auto* ipr = PlatformRegistry::instance().imageProviderRenderer();
        for (const auto& entry : issued)
        {
            // A key is safe only if it is not retired and the renderer replaces it before the back end.
            // Without a renderer nothing can do that.
            PresentationKeyFallback reason = PresentationKeyFallback::eNone;
            if (!ipr)
            {
                reason = PresentationKeyFallback::eNotMapped;
            }
            else if (entry.retired)
            {
                reason = PresentationKeyFallback::eRetired;
            }
            else
            {
                const auto state = ipr->presentationKeyState(entry.renderer, entry.key);
                if (state == IImageProviderRenderer::PresentationKeyState::eUnmapped)
                    reason = PresentationKeyFallback::eUnmapped;
                else if (state != IImageProviderRenderer::PresentationKeyState::eMapped)
                    reason = PresentationKeyFallback::eNotMapped;
            }
            if (reason != PresentationKeyFallback::eNone)
            {
                // Retired and unmapped are more exact than "not mapped" when two renderers disagree.
                auto it = unmapped.find(entry.key);
                if (it == unmapped.end() || it->second == PresentationKeyFallback::eNotMapped)
                    unmapped[entry.key] = reason;
            }
        }
    }
    if (unmapped.empty())
    {
        std::lock_guard<std::mutex> g(s_keyMutex);
        s_droppingKeys.clear();
        return 0;
    }

    size_t dropped = 0;
    std::map<uint64_t, PresentationKeyFallback> removedNow;
    for (int listIndex = 0; listIndex < drawData->CmdListsCount; ++listIndex)
    {
        ImDrawList* list = drawData->CmdLists[listIndex];
        if (!list)
        {
            continue;
        }
        for (int cmdIndex = list->CmdBuffer.Size - 1; cmdIndex >= 0; --cmdIndex)
        {
            const ImDrawCmd& cmd = list->CmdBuffer[cmdIndex];
            if (cmd.UserCallback || cmd.TexRef._TexData != nullptr)
            {
                continue;
            }
            const uint64_t id = static_cast<uint64_t>(cmd.TexRef._TexID);
            auto found = unmapped.find(id);
            if (found != unmapped.end())
            {
                removedNow[id] = found->second;
                list->CmdBuffer.erase(list->CmdBuffer.Data + cmdIndex);
                ++dropped;
            }
        }
    }

    // One log line when the commands of a key start to be removed. A key that is not removed in
    // this pass is forgotten, so a later removal writes a line again.
    std::lock_guard<std::mutex> g(s_keyMutex);
    for (const auto& entry : removedNow)
    {
        if (!s_droppingKeys.count(entry.first))
        {
            OMNIUI_LOG_WARN("Removed the draw commands of presentation key %llu: %s. The key has no drawable.",
                            static_cast<unsigned long long>(entry.first), presentationKeyFallbackText(entry.second));
        }
    }
    s_droppingKeys.swap(removedNow);
    return dropped;
}

} // namespace ui
} // namespace omni
