/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/ImageProvider/ImageProvider.h>
#include "../platform/Assert.h"
#include "../platform/Log.h"
#include "../platform/PlatformRegistry.h"
#include "../platform/IImageProviderRenderer.h"
#include "ImageProviderThreads.h"
#include "PresentationKeyState.h"

#include <imgui/imgui.h>

#include <atomic>
#include <climits>
#include <condition_variable>
#include <deque>
#include <exception>
#include <mutex>
#include <list>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace omni
{
namespace ui
{

std::mutex s_mutex;
std::list<ImageProvider*> s_list;

namespace
{

std::atomic<uint64_t> s_offUiThreadCalls{ 0 };
// Depth of the change scopes on this thread. Used only off the UI thread and by destructors.
thread_local int t_changeDepth = 0;

// Changes given with publishOnUiThread(), and the provider whose change runs now. The state lives here,
// keyed by provider, and not in new data members: code built against an older header has the old size
// of the class.
struct PendingPublication
{
    ImageProvider* provider = nullptr;
    ImageProvider::PublishedUpdate update;
    uint64_t id = 0;
    uint64_t sequence = 0;
    bool replaceable = false;
};

struct PublicationCounters
{
    uint64_t lastId = 0;
    uint64_t appliedId = 0;
};

struct PublicationState
{
    std::mutex mutex;
    std::condition_variable done;
    std::deque<PendingPublication> queue;
    std::unordered_map<const ImageProvider*, PublicationCounters> counters;
    uint64_t sequence = 0;
    const ImageProvider* runningProvider = nullptr;
    std::thread::id runningThread;
    bool runningProviderDestroyed = false;
    std::mutex reportMutex;
    std::unordered_set<uint32_t> reported; // providers with an off-UI-thread report
};

// Never destroyed: a provider can be destroyed at process exit, after the static objects of this file.
PublicationState& publicationState()
{
    static PublicationState* state = new PublicationState();
    return *state;
}

// Lets applyPublishedUpdates() return without a lock when nothing waits.
std::atomic<size_t> s_pendingPublications{ 0 };

// The ImGui frame of the last applyPublishedUpdates(), or INT_MIN. One pass per frame: see
// applyPublishedUpdatesOncePerFrame().
std::atomic<int> s_publicationFrame{ INT_MIN };

void runPublication(PendingPublication& publication)
{
    // A failing change must not stop the changes after it. Its failure is reported here.
    try
    {
        publication.update(*publication.provider);
    }
    catch (const std::exception& e)
    {
        OMNIUI_LOG_ERROR("ImageProvider %p: a change given with publishOnUiThread failed: %s. The next changes still run.",
                         static_cast<void*>(publication.provider), e.what());
    }
    catch (...)
    {
        OMNIUI_LOG_ERROR("ImageProvider %p: a change given with publishOnUiThread failed with an exception that is not "
                         "a std::exception. The next changes still run.",
                         static_cast<void*>(publication.provider));
    }
}

} // namespace

std::atomic<std::thread::id> g_imageProviderUiThread{};

void forgetImageProviderPublications(const ImageProvider* provider, uint32_t providerId)
{
    PublicationState& st = publicationState();
    // Destroyed after the lock is released: a change can hold Python state, whose release takes the GIL.
    std::vector<ImageProvider::PublishedUpdate> removed;
    std::unique_lock<std::mutex> lock(st.mutex);
    if (st.runningProvider == provider)
    {
        if (st.runningThread != std::this_thread::get_id())
        {
            st.done.wait(lock, [&st, provider]() { return st.runningProvider != provider; });
        }
        else
        {
            // The change of this provider dropped the last owner of the provider.
            st.runningProviderDestroyed = true;
        }
    }
    for (auto it = st.queue.begin(); it != st.queue.end();)
    {
        if (it->provider == provider)
        {
            removed.push_back(std::move(it->update));
            it = st.queue.erase(it);
            s_pendingPublications.fetch_sub(1, std::memory_order_relaxed);
        }
        else
        {
            ++it;
        }
    }
    st.counters.erase(provider);
    lock.unlock();
    std::lock_guard<std::mutex> reportLock(st.reportMutex);
    st.reported.erase(providerId);
}

void ImageProviderChangeScope::_enterWithoutCheck()
{
    ++t_changeDepth;
    m_entered = true;
}

void ImageProviderChangeScope::_enterOffUiThread(uint32_t providerId, const char* function)
{
    m_entered = true;
    // A changing call inside another one, or inside a destructor, is not reported again.
    if (t_changeDepth++ != 0)
        return;
    s_offUiThreadCalls.fetch_add(1, std::memory_order_relaxed);
    bool first = false;
    {
        PublicationState& st = publicationState();
        std::lock_guard<std::mutex> lock(st.reportMutex);
        first = st.reported.insert(providerId).second;
    }
    if (first)
    {
        OMNIUI_LOG_ERROR("ImageProvider %u: %s was called on a thread that is not the UI thread. The UI thread can draw "
                         "the image while it changes. Call it on the UI thread, or give the change with "
                         "publishOnUiThread() (Python: publish_on_ui_thread). This line is written once for each "
                         "provider; getOffUiThreadCallCount() counts every such call.",
                         providerId, function);
    }
    OMNIUI_ASSERT(false, "an ImageProvider was changed on a thread that is not the UI thread");
}

void ImageProviderChangeScope::_exitScope()
{
    --t_changeDepth;
}

ImageProvider::ImageProvider()
{
    {
        std::lock_guard<std::mutex> g(s_mutex);
        s_list.push_back(this);

        static uint32_t idCounter = 0;
        m_id = idCounter++;
    }

    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();
    if (ipr)
    {
        m_kitRenderer = ipr->acquireRenderer();
        if (!m_kitRenderer)
        {
            OMNIUI_LOG_ERROR("Renderer must be present!");
        }
    }
}

ImageProvider::~ImageProvider()
{
    forgetImageProviderPublications(this, m_id);
    // Nothing can draw this provider any more, so it can be destroyed on any thread.
    ImageProviderChangeScope noCheck(m_id, nullptr);
    _setPresentationKey(0);
    setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
    {
        std::lock_guard<std::mutex> g(s_mutex);
        s_list.remove(this);
    }
}

void ImageProvider::setImageData(void* imGuiReference, UInt2 size, PixelFormat format, GpuResource* rpRsrc)
{
    ImageProviderChangeScope check(m_id, "setImageData");
    if (m_isShutdown)
        return;

    _releaseImage();
    m_imGuiReference = imGuiReference;
    m_imageSize = size;
    m_imageFormat = format;
    _setManagedResource(rpRsrc);
}

void* ImageProvider::getImGuiReference()
{
    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();
    // The key is used only while it has a drawable. The global present setting alone is not
    // enough: another live feed keeps it on. So a key is skipped when the feeder retired it or
    // when the renderer reports it unmapped. A key that the renderer reports mapped is valid and
    // stays in use, however slowly its feed delivers frames. When the renderer has no per-key
    // state (unknown), the key stays in use, unless the host opted in to a lease (see
    // setPresentationKeyLeaseMs): then it lapses when its feed stops calling setImageData.
    // Key mode applies only to the present thread. While it is off, the texture reference is the normal
    // reference: this is not a fallback, so no line is written.
    if (!ipr || !m_presentationKey || !ipr->isPresentThreadEnabled(m_kitRenderer))
    {
        return m_imGuiReference;
    }

    using Reason = PresentationKeyFallback;
    Reason reason = Reason::eNone;
    if (isPresentationKeyRetired(m_presentationKey))
    {
        reason = Reason::eRetired;
    }
    else
    {
        const auto state = ipr->presentationKeyState(m_kitRenderer, m_presentationKey);
        using State = IImageProviderRenderer::PresentationKeyState;
        if (state == State::eUnmapped)
            reason = Reason::eUnmapped;
        else if (state == State::eUnknown && !_isPresentationKeyLeased())
            reason = Reason::eExpired;
    }

    if (reason == Reason::eNone)
    {
        if (m_presentationKeyFallback)
        {
            OMNIUI_LOG_INFO("ImageProvider %u uses presentation key %llu again.", m_id,
                            static_cast<unsigned long long>(m_presentationKey));
            m_presentationKeyFallback = 0;
        }
        recordIssuedPresentationKey(m_kitRenderer, m_presentationKey);
        uintptr_t intPtr = static_cast<uintptr_t>(m_presentationKey);
        return reinterpret_cast<void*>(intPtr);
    }

    // One line for each change from the key to the texture reference, not one for each frame.
    if (m_presentationKeyFallback != static_cast<uint8_t>(reason))
    {
        OMNIUI_LOG_WARN("ImageProvider %u uses its texture instead of presentation key %llu: %s.", m_id,
                        static_cast<unsigned long long>(m_presentationKey), presentationKeyFallbackText(reason));
        m_presentationKeyFallback = static_cast<uint8_t>(reason);
    }
    return m_imGuiReference;
}

void ImageProvider::clearPresentationKey()
{
    ImageProviderChangeScope check(m_id, "clearPresentationKey");
    _setPresentationKey(0);
}

void ImageProvider::setPresentationKeyLeaseMs(uint32_t ms)
{
    omni::ui::setPresentationKeyLeaseMs(ms);
}

bool ImageProvider::_isPresentationKeyLeased() const
{
    const uint32_t leaseMs = getPresentationKeyLeaseMs();
    if (!leaseMs)
        return true;
    const uint64_t now = presentationKeyNowNs();
    return now < m_presentationKeyArmedNs || now - m_presentationKeyArmedNs <= uint64_t(leaseMs) * 1000000ull;
}

void ImageProvider::retirePresentationKey(uint64_t key)
{
    omni::ui::retirePresentationKey(key);
}

void ImageProvider::_setPresentationKey(uint64_t key)
{
    if (key)
        holdPresentationKey(key);
    if (m_presentationKey)
        releasePresentationKey(m_presentationKey);
    m_presentationKey = key;
    m_presentationKeyArmedNs = key ? presentationKeyNowNs() : 0;
    // The renderer may also have changed its answer for the new key; the next call decides again.
    if (!key)
        m_presentationKeyFallback = 0;
}


bool ImageProvider::setImageData(GpuResource& rpRsrc, uint64_t presentationKey)
{
    ImageProviderChangeScope check(m_id, "setImageData");
    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();
    if (!ipr)
        return false;

    if (reinterpret_cast<void*>(&rpRsrc) != reinterpret_cast<void*>(m_managedRsrc))
    {
        auto result = ipr->ensureResourceWithTextureInfo(
            m_kitRenderer, reinterpret_cast<void*>(&rpRsrc), m_id);
        if (!result.resource)
        {
            // Nothing was set. The key and the mode stay as they were.
            return false;
        }

        setImageData(result.textureHandlePtr, { result.width, result.height }, result.format, nullptr);
        m_managedRsrc = reinterpret_cast<GpuResource*>(result.resource);
    }

    // Store the key only after the resource is known to be good. This also covers
    // the same-resource case, which skips the ensure call above.
    _setPresentationKey(presentationKey);
    return true;
}

void ImageProvider::prepareDraw(float widgetWidth, float widgetHeight)
{
}

bool ImageProvider::setImageData(GpuResource& resource, uint64_t presentationKey, carb::imaging::IMetadata* metadata)
{
    ImageProviderChangeScope check(m_id, "setImageData");
    if (!setImageData(resource, presentationKey)) return false;
    auto* renderer = PlatformRegistry::instance().imageProviderRenderer();
    if (metadata && renderer) renderer->getMetadataDisplayWindow(metadata, m_imageDisplayWindow);
    return true;
}

bool ImageProvider::setImageData(GpuResource& rpRsrc)
{
    return setImageData(rpRsrc, 0);
}

void ImageProvider::shutdown()
{
    std::lock_guard<std::mutex> g(s_mutex);
    for (auto* entry : s_list)
    {
        entry->_shutdown();
    }
}

void ImageProvider::_shutdown()
{
    m_isShutdown = true;
}

ImageProvider::GpuResource* ImageProvider::getManagedResource()
{
    return m_managedRsrc;
}

uint64_t ImageProvider::publishOnUiThread(PublishedUpdate update, bool replacePending)
{
    if (!update)
        return 0;
    // Destroyed after the lock is released, for the same reason as in forgetImageProviderPublications().
    PublishedUpdate replaced;
    PublicationState& st = publicationState();
    std::lock_guard<std::mutex> lock(st.mutex);
    const uint64_t id = ++st.counters[this].lastId;
    if (replacePending)
    {
        for (auto it = st.queue.rbegin(); it != st.queue.rend(); ++it)
        {
            if (it->provider != this)
                continue;
            if (it->replaceable)
            {
                // The new change takes the place of the waiting one at the end of the queue, with a new
                // sequence number: like an appended change, it waits for the next pass when a pass runs now.
                // The waiting one was the last change of this provider, so its order does not change.
                replaced = std::move(it->update);
                st.queue.erase(std::next(it).base());
                st.queue.push_back({ this, std::move(update), id, ++st.sequence, true });
                return id;
            }
            // The last waiting change of this provider is kept: it was not given as replaceable.
            break;
        }
    }
    st.queue.push_back({ this, std::move(update), id, ++st.sequence, replacePending });
    s_pendingPublications.fetch_add(1, std::memory_order_release);
    return id;
}

uint64_t ImageProvider::getAppliedPublicationId() const
{
    PublicationState& st = publicationState();
    std::lock_guard<std::mutex> lock(st.mutex);
    auto it = st.counters.find(this);
    return it == st.counters.end() ? 0 : it->second.appliedId;
}

size_t applyPublishedUpdatesOncePerFrame()
{
    if (ImGui::GetCurrentContext() &&
        s_publicationFrame.load(std::memory_order_relaxed) == ImGui::GetFrameCount())
        return 0;
    return ImageProvider::applyPublishedUpdates();
}

size_t ImageProvider::applyPublishedUpdates()
{
    g_imageProviderUiThread.store(std::this_thread::get_id(), std::memory_order_relaxed);
    if (ImGui::GetCurrentContext())
        s_publicationFrame.store(ImGui::GetFrameCount(), std::memory_order_relaxed);
    if (s_pendingPublications.load(std::memory_order_acquire) == 0)
        return 0;

    PublicationState& st = publicationState();
    uint64_t lastSequence = 0;
    {
        std::lock_guard<std::mutex> lock(st.mutex);
        lastSequence = st.sequence;
    }
    size_t ran = 0;
    for (;;)
    {
        PendingPublication next;
        {
            std::lock_guard<std::mutex> lock(st.mutex);
            // Changes given while this pass runs wait for the next pass.
            if (st.queue.empty() || st.queue.front().sequence > lastSequence)
                break;
            next = std::move(st.queue.front());
            st.queue.pop_front();
            s_pendingPublications.fetch_sub(1, std::memory_order_relaxed);
            st.runningProvider = next.provider;
            st.runningThread = std::this_thread::get_id();
            st.runningProviderDestroyed = false;
        }
        runPublication(next);
        // The change can own the last reference to its provider.
        next.update = nullptr;
        {
            std::lock_guard<std::mutex> lock(st.mutex);
            if (!st.runningProviderDestroyed)
            {
                auto it = st.counters.find(next.provider);
                if (it != st.counters.end() && it->second.appliedId < next.id)
                    it->second.appliedId = next.id;
            }
            st.runningProvider = nullptr;
            st.runningThread = std::thread::id();
        }
        st.done.notify_all();
        ++ran;
    }
    return ran;
}

uint64_t ImageProvider::getOffUiThreadCallCount()
{
    return s_offUiThreadCalls.load(std::memory_order_relaxed);
}

bool ImageProvider::_setManagedResource(GpuResource* rpRsrc)
{
    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();

    auto* rsrc = reinterpret_cast<void*>(rpRsrc);
    auto* managed = reinterpret_cast<void*>(m_managedRsrc);

    if (rsrc == managed)
    {
        return true;
    }

    if (ipr)
    {
        if (rsrc)
        {
            rsrc = ipr->ensureResourceSimple(m_kitRenderer, rsrc, m_id);
        }
        if (managed)
        {
            ipr->releaseResource(m_kitRenderer, managed);
        }
    }

    m_managedRsrc = reinterpret_cast<GpuResource*>(rsrc);
    return true;
}

bool ImageProvider::mergeTextureOptions(ImageProvider::TextureOptions& textureOptions) const
{
    return true;
}

bool ImageProvider::setTextureOptions(TextureOptions textureOptions)
{
    OMNIUI_LOG_ERROR("ImageProvider::setTextureOptions is not implemented");
    return false;
}

}
}
