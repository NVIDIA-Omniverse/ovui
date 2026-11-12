/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include "../platform/Log.h"
#include "ImageProviderThreads.h"

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/Profile.h>

#include <atomic>
#include <cmath>
#include <algorithm>
#include <deque>
#include <exception>
#include <iterator>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace omni
{
namespace ui
{

size_t getPixelFormatSize(PixelFormat format)
{
    switch (format)
    {
        case PixelFormat::eRGBA8_UNORM:
        case PixelFormat::eRGBA8_SRGB:
        case PixelFormat::eBGRA8_UNORM:
            return 4;
        case PixelFormat::eR8_UNORM:
            return 1;
        case PixelFormat::eR16_FLOAT:
            return 2;
        case PixelFormat::eR32_FLOAT:
        case PixelFormat::eRG16_FLOAT:
            return 4;
        case PixelFormat::eRGB16_FLOAT:
            return 6;
        case PixelFormat::eRG32_FLOAT:
        case PixelFormat::eRGBA16_FLOAT:
            return 8;
        case PixelFormat::eRGB32_FLOAT:
            return 12;
        case PixelFormat::eRGBA32_FLOAT:
            return 16;
        default:
        {
            auto* gpu = PlatformRegistry::instance().byteImageGpu();
            return gpu ? gpu->getFormatSize(format) : 0;
        }
    }
}

namespace
{

/// An accepted upload whose copy is not proved finished yet. The completion
/// event of this upload reports these device masks.
struct AcceptedUpload
{
    uint64_t id = 0;
    uint32_t requestedDeviceMask = 0;
    uint32_t uploadedDeviceMask = 0;
};

/// How many accepted uploads a provider keeps while nobody asks for their
/// completion. When there are more, the oldest is dropped.
constexpr size_t kMaxNotCompletedUploads = 1024;

using UploadSubscribers = std::vector<std::pair<uint64_t, std::function<void(const ByteImageUploadEvent&)>>>;

// Upload bookkeeping lives here, keyed by provider, and not in new data
// members. Code that was built against an older header allocates a
// ByteImageProvider with ``new`` and so has the old size of the class baked in.
struct UploadState
{
    ByteImageUploadResult last;
    uint64_t failureCount = 0;
    uint64_t nextLegacyUploadId = 1;
    uint64_t completedReported = 0;
    /// Newest accepted upload id that a checked backend has not yet proved
    /// finished, or 0. While any provider has one, prepareDraw() polls.
    uint64_t pendingCompletionId = 0;
    /// Accepted uploads that a checked backend has not yet proved finished,
    /// oldest first.
    std::deque<AcceptedUpload> notCompleted;
    /// The newest upload dropped from notCompleted because it was full.
    AcceptedUpload lastDropped;
    /// Failures that injectUploadFailures() asked for, still waiting.
    uint32_t injectedFailures = 0;
    uint64_t nextSubscriptionId = 1;
    UploadSubscribers subscribers;
};

std::mutex g_uploadMutex;
std::unordered_map<const ByteImageProvider*, UploadState> g_uploadStates;
/// How many providers wait for a completion proof. Lets prepareDraw() return
/// at once, without a lock, when there is nothing to poll.
std::atomic<uint32_t> g_providersWaitingForCompletion{ 0 };
/// How many providers have injected failures waiting. Lets an upload skip the
/// lock when no test hook is armed.
std::atomic<uint32_t> g_providersWithInjectedFailures{ 0 };

// Call with g_uploadMutex held.
void setInjectedFailures(UploadState& state, uint32_t count)
{
    if (state.injectedFailures == 0 && count != 0)
    {
        g_providersWithInjectedFailures.fetch_add(1, std::memory_order_relaxed);
    }
    else if (state.injectedFailures != 0 && count == 0)
    {
        g_providersWithInjectedFailures.fetch_sub(1, std::memory_order_relaxed);
    }
    state.injectedFailures = count;
}

// Call with g_uploadMutex held.
void setPendingCompletion(UploadState& state, uint64_t uploadId)
{
    if (state.pendingCompletionId == 0 && uploadId != 0)
    {
        g_providersWaitingForCompletion.fetch_add(1, std::memory_order_relaxed);
    }
    else if (state.pendingCompletionId != 0 && uploadId == 0)
    {
        g_providersWaitingForCompletion.fetch_sub(1, std::memory_order_relaxed);
    }
    state.pendingCompletionId = uploadId;
}

// Call with g_uploadMutex held.
void rememberNotCompleted(UploadState& state, const AcceptedUpload& upload)
{
    if (state.notCompleted.size() >= kMaxNotCompletedUploads)
    {
        state.lastDropped = state.notCompleted.front();
        state.notCompleted.pop_front();
    }
    state.notCompleted.push_back(upload);
}

// Call with g_uploadMutex held. Forgets the uploads up to ``completed`` and
// returns the newest of them, so that its completion event names its own
// devices.
AcceptedUpload forgetCompleted(UploadState& state, uint64_t completed)
{
    AcceptedUpload newest;
    if (state.lastDropped.id != 0 && state.lastDropped.id <= completed)
    {
        newest = state.lastDropped;
    }
    while (!state.notCompleted.empty() && state.notCompleted.front().id <= completed)
    {
        newest = state.notCompleted.front();
        state.notCompleted.pop_front();
    }
    return newest;
}

bool takeInjectedFailure(const ByteImageProvider* self)
{
    if (g_providersWithInjectedFailures.load(std::memory_order_relaxed) == 0)
    {
        return false;
    }
    std::lock_guard<std::mutex> lock(g_uploadMutex);
    auto it = g_uploadStates.find(self);
    if (it == g_uploadStates.end() || it->second.injectedFailures == 0)
    {
        return false;
    }
    setInjectedFailures(it->second, it->second.injectedFailures - 1);
    return true;
}

void notify(const ByteImageProvider* self, const ByteImageUploadEvent& event)
{
    std::vector<std::pair<uint64_t, std::function<void(const ByteImageUploadEvent&)>>> callbacks;
    {
        std::lock_guard<std::mutex> lock(g_uploadMutex);
        auto it = g_uploadStates.find(self);
        if (it == g_uploadStates.end())
        {
            return;
        }
        callbacks = it->second.subscribers;
    }
    for (auto& callback : callbacks)
    {
        // A failing subscriber must not undo the upload or hide the event
        // from the other subscribers. Its failure is reported here.
        try
        {
            callback.second(event);
        }
        catch (const std::exception& e)
        {
            OMNIUI_LOG_ERROR("ByteImageProvider: upload event subscriber %llu failed: %s. The upload and the other "
                             "subscribers are not affected.",
                             static_cast<unsigned long long>(callback.first), e.what());
        }
        catch (...)
        {
            OMNIUI_LOG_ERROR("ByteImageProvider: upload event subscriber %llu failed with an exception that is not a "
                             "std::exception. The upload and the other subscribers are not affected.",
                             static_cast<unsigned long long>(callback.first));
        }
    }
}

} // namespace

namespace
{

// validate the structural inputs to a ByteImageProvider upload
// before they reach the renderer. The renderer (carb::graphics::uploadData ->
// ResourceLoader::loadTexture) does a memcpy of `stride * height` bytes from
// the supplied buffer without any knowledge of its size; if any of these
// arguments are inconsistent the memcpy reads past the end of the buffer and
// the process dies inside VCRUNTIME140!memcpy_repmovs.
//
// Returns true if the upload arguments are safe to forward to the renderer;
// returns false and logs an actionable error otherwise. `caller` is used in
// the log message so we can tell which entry point rejected the call.
static bool isUploadShapeValid(const char* caller, UInt2 size, size_t& stride, PixelFormat format)
{
    if (size.x == 0 || size.y == 0)
    {
        OMNIUI_LOG_ERROR("%s: rejected upload with zero-size image (size=%u x %u, format=%u). "
                       "Skipping GPU upload to avoid renderer crash.",
                       caller, size.x, size.y, static_cast<uint32_t>(format));
        return false;
    }
    if (format == PixelFormat::eUnknown)
    {
        OMNIUI_LOG_ERROR("%s: rejected upload with Format::eUnknown (size=%u x %u). "
                       "Skipping GPU upload to avoid renderer crash.",
                       caller, size.x, size.y);
        return false;
    }

    const size_t formatSize = getPixelFormatSize(format);
    if (formatSize == 0)
    {
        OMNIUI_LOG_ERROR("%s: rejected upload with unsupported format=%u (size=%u x %u). "
                       "Skipping GPU upload to avoid renderer crash.",
                       caller, static_cast<uint32_t>(format), size.x, size.y);
        return false;
    }

    const size_t minStride = static_cast<size_t>(size.x) * static_cast<size_t>(formatSize);
    if (stride == kAutoCalculateStride)
    {
        stride = minStride;
    }
    else if (stride < minStride)
    {
        OMNIUI_LOG_ERROR("%s: rejected upload with stride=%zu < width*texelSize=%zu "
                       "(size=%u x %u, format=%u). Skipping GPU upload to avoid renderer crash.",
                       caller, stride, minStride, size.x, size.y,
                       static_cast<uint32_t>(format));
        return false;
    }
    return true;
}

} // anonymous namespace

ByteImageProvider::ByteImageProvider()
{
    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (gpu)
    {
        m_gpuState = gpu->createState();
    }
}

ByteImageProvider::~ByteImageProvider()
{
    // A change of this provider that runs on the UI thread must end before the GPU state goes.
    forgetImageProviderPublications(this, m_id);
    // Nothing can draw this provider any more, so it can be destroyed on any thread.
    ImageProviderChangeScope noCheck(m_id, nullptr);
    // ImageProvider::~ImageProvider() calls _releaseImage via setImageData,
    // but since it's called from the base destructor, the derived
    // _releaseImage is never called. So we must do it here.
    this->setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);

    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (gpu && m_gpuState)
    {
        gpu->destroyState(m_gpuState);
        m_gpuState = nullptr;
    }

    // The state, and with it the subscribers, is destroyed after the lock is
    // released: a subscriber can hold Python state, whose release takes the
    // GIL, and a thread that holds the GIL can wait for this lock.
    UploadState removed;
    {
        std::lock_guard<std::mutex> lock(g_uploadMutex);
        auto it = g_uploadStates.find(this);
        if (it != g_uploadStates.end())
        {
            setPendingCompletion(it->second, 0);
            setInjectedFailures(it->second, 0);
            removed = std::move(it->second);
            g_uploadStates.erase(it);
        }
    }
}

bool ByteImageProvider::mergeTextureOptions(TextureOptions& textureOptions) const
{
    if (m_textureOptions)
    {
        const auto deviceMask = m_textureOptions->gpuDeviceMask;
        if (textureOptions.gpuDeviceMask)
        {
            if (deviceMask && deviceMask != textureOptions.gpuDeviceMask)
            {
                OMNIUI_LOG_ERROR("ByteImageProvider has exiting texture options that do not match input. (%u, %u)",
                    textureOptions.gpuDeviceMask, deviceMask);
                return false;
            }
        }
        else if (deviceMask)
        {
            textureOptions.gpuDeviceMask = deviceMask;
        }

        textureOptions.textureUsageFlags |= m_textureOptions->textureUsageFlags;
        textureOptions.resourceUsageFlags |= m_textureOptions->resourceUsageFlags;
    }
    return true;
}

bool ByteImageProvider::setTextureOptions(TextureOptions textureOptions)
{
    if (!m_textureOptions)
    {
        m_textureOptions = std::make_unique<TextureOptions>(textureOptions);
    }
    else
    {
        *m_textureOptions = textureOptions;
    }
    return true;
}

void ByteImageProvider::_updateImage(const uint8_t* const* mipMapBuffers,
                                     size_t* mipMapStrides,
                                     size_t mipMapCount,
                                     UInt2 size,
                                     PixelFormat format,
                                     bool fromGpu)
{
    _uploadImage(mipMapBuffers, mipMapStrides, mipMapCount, size, format, fromGpu);
}

ByteImageUploadResult ByteImageProvider::_uploadImage(const uint8_t* const* mipMapBuffers,
                                                      size_t* mipMapStrides,
                                                      size_t mipMapCount,
                                                      UInt2 size,
                                                      PixelFormat format,
                                                      bool fromGpu)
{
    OMNIUI_PROFILE_VERBOSE_ZONE("ByteImageProvider::_updateImage");

    ByteImageUploadResult out;
    uint32_t optDeviceMask = m_textureOptions ? m_textureOptions->gpuDeviceMask : 0;
    uint32_t optTexFlags = m_textureOptions ? m_textureOptions->textureUsageFlags : 0;
    uint32_t optRsrcFlags = m_textureOptions ? m_textureOptions->resourceUsageFlags : 0;
    out.requestedDeviceMask = optDeviceMask;

    auto* registry = &PlatformRegistry::instance();
    auto* gpu = registry->byteImageGpu();
    auto* checked = registry->byteImageGpuChecked();

    IByteImageGpu::UpdateResult update;
    if (takeInjectedFailure(this))
    {
        out.cause = "refused on purpose by injectUploadFailures";
    }
    else if (!gpu)
    {
        // No backend means no renderer, so nothing can be uploaded. A missing
        // renderer is not a failure: it is not counted, sends no event and is
        // not an error.
        out.status = UploadStatus::eNoBackend;
        out.cause = "no GPU backend is registered";
    }
    else if (!m_gpuState)
    {
        out.cause = "the provider has no GPU state: it was made before the GPU backend, or the backend could not make "
                    "one";
    }
    else if (checked)
    {
        UploadResult r = checked->updateImageChecked(m_gpuState, mipMapBuffers, mipMapStrides, mipMapCount, size,
                                                     format, fromGpu, optDeviceMask, optTexFlags, optRsrcFlags);
        out.requestedDeviceMask = r.requestedDeviceMask;
        out.uploadedDeviceMask = r.uploadedDeviceMask;
        // A result that says "accepted" but has no texture is not an upload.
        if (r.status != UploadStatus::eFailed && r.update.imGuiReference)
        {
            out.status = r.status;
            out.uploadId = r.uploadId;
            update = r.update;
        }
        else if (r.status != UploadStatus::eFailed)
        {
            out.cause = "the backend reported success but returned no texture";
        }
        else
        {
            out.cause = r.cause ? r.cause : "the backend refused the upload and gave no reason";
        }
    }
    else
    {
        update = gpu->updateImage(m_gpuState, mipMapBuffers, mipMapStrides, mipMapCount, size, format, fromGpu,
                                  optDeviceMask, optTexFlags, optRsrcFlags);
        if (update.imGuiReference)
        {
            out.status = UploadStatus::eEnqueued;
        }
        else
        {
            out.cause = "the backend returned no texture";
        }
    }

    bool completedNow = false;
    {
        std::lock_guard<std::mutex> lock(g_uploadMutex);
        UploadState& state = g_uploadStates[this];
        if (out.accepted())
        {
            if (!checked || out.uploadId == 0)
            {
                // The backend gave no id. Number the uploads here.
                out.uploadId = state.nextLegacyUploadId++;
            }
            completedNow = out.status == UploadStatus::eComplete;
            if (completedNow)
            {
                state.completedReported = std::max(state.completedReported, out.uploadId);
                if (!state.notCompleted.empty())
                {
                    forgetCompleted(state, state.completedReported);
                }
                if (state.pendingCompletionId != 0 && state.pendingCompletionId <= state.completedReported)
                {
                    setPendingCompletion(state, 0);
                }
            }
            else if (checked)
            {
                // Only a checked backend can prove the end later.
                setPendingCompletion(state, out.uploadId);
                rememberNotCompleted(state, { out.uploadId, out.requestedDeviceMask, out.uploadedDeviceMask });
            }
        }
        else if (out.status == UploadStatus::eFailed)
        {
            ++state.failureCount;
        }
        state.last = out;
    }

    if (out.status == UploadStatus::eNoBackend)
    {
        OMNIUI_LOG_INFO("No GPU backend for byte images. Upload not done. [%u x %u, %zu mips]", size.x, size.y,
                        mipMapCount);
        return out;
    }

    if (!out.accepted())
    {
        OMNIUI_LOG_ERROR("ByteImageProvider upload refused [%u x %u, %zu mips, devices requested 0x%x, accepted 0x%x]: "
                         "%s. The previous pixels stay.",
                         size.x, size.y, mipMapCount, out.requestedDeviceMask, out.uploadedDeviceMask, out.cause);
        notify(this, { ByteImageUploadEvent::Kind::eFailed, 0, out.requestedDeviceMask, out.uploadedDeviceMask });
        return out;
    }

    if (update.managedResource)
    {
        _setManagedResource(reinterpret_cast<GpuResource*>(update.managedResource));
    }

    m_imageSize = size;
    m_imageFormat = format;
    m_imageMipCount = mipMapCount;
    m_imGuiReference = update.imGuiReference;
    // A successful upload is an explicit return to texture mode. A failed upload
    // returned above, so it keeps the earlier mode and the reference stays valid.
    _setPresentationKey(0);

    notify(this, { ByteImageUploadEvent::Kind::eEnqueued, out.uploadId, out.requestedDeviceMask,
                   out.uploadedDeviceMask });
    if (completedNow)
    {
        notify(this, { ByteImageUploadEvent::Kind::eCompleted, out.uploadId, out.requestedDeviceMask,
                       out.uploadedDeviceMask });
    }
    return out;
}

ByteImageUploadResult ByteImageProvider::rejectUpload(const char* cause)
{
    ByteImageUploadResult out;
    out.requestedDeviceMask = m_textureOptions ? m_textureOptions->gpuDeviceMask : 0;
    out.cause = cause ? cause : "the input was refused and no reason was given";
    {
        std::lock_guard<std::mutex> lock(g_uploadMutex);
        UploadState& state = g_uploadStates[this];
        ++state.failureCount;
        state.last = out;
    }
    OMNIUI_LOG_ERROR("ByteImageProvider upload refused before the backend: %s. The previous pixels stay.", out.cause);
    notify(this, { ByteImageUploadEvent::Kind::eFailed, 0, out.requestedDeviceMask, 0 });
    return out;
}

ByteImageUploadResult ByteImageProvider::getLastUploadResult() const
{
    std::lock_guard<std::mutex> lock(g_uploadMutex);
    auto it = g_uploadStates.find(this);
    return it == g_uploadStates.end() ? ByteImageUploadResult{} : it->second.last;
}

uint64_t ByteImageProvider::getUploadFailureCount() const
{
    std::lock_guard<std::mutex> lock(g_uploadMutex);
    auto it = g_uploadStates.find(this);
    return it == g_uploadStates.end() ? 0 : it->second.failureCount;
}

uint64_t ByteImageProvider::getCompletedUploadId()
{
    {
        std::lock_guard<std::mutex> lock(g_uploadMutex);
        if (g_uploadStates.find(this) == g_uploadStates.end())
        {
            return 0;
        }
    }

    // The backend is asked outside the lock.
    // Without IByteImageGpuChecked the backend cannot prove that a copy has
    // finished, so no id is ever reported as completed. Ordering before later
    // sampling is not proof that the copy ended, and a source must not be
    // released on it.
    uint64_t completed = 0;
    auto* checked = PlatformRegistry::instance().byteImageGpuChecked();
    if (checked && m_gpuState)
    {
        completed = checked->getCompletedUploadId(m_gpuState);
    }

    ByteImageUploadEvent event;
    {
        std::lock_guard<std::mutex> lock(g_uploadMutex);
        auto it = g_uploadStates.find(this);
        if (it == g_uploadStates.end() || completed <= it->second.completedReported)
        {
            return completed;
        }
        it->second.completedReported = completed;
        if (it->second.pendingCompletionId != 0 && it->second.pendingCompletionId <= completed)
        {
            setPendingCompletion(it->second, 0);
        }
        // The devices of the upload that completed, not of a later attempt.
        const AcceptedUpload upload = forgetCompleted(it->second, completed);
        event = { ByteImageUploadEvent::Kind::eCompleted, completed, upload.requestedDeviceMask,
                  upload.uploadedDeviceMask };
    }
    notify(this, event);
    return completed;
}

uint64_t ByteImageProvider::subscribeUploadEvents(std::function<void(const ByteImageUploadEvent&)> callback)
{
    if (!callback)
    {
        return 0;
    }
    std::lock_guard<std::mutex> lock(g_uploadMutex);
    UploadState& state = g_uploadStates[this];
    const uint64_t id = state.nextSubscriptionId++;
    state.subscribers.emplace_back(id, std::move(callback));
    return id;
}

void ByteImageProvider::unsubscribeUploadEvents(uint64_t subscriptionId)
{
    // The removed callback is destroyed after the lock is released, for the
    // same reason as in the destructor.
    UploadSubscribers removed;
    {
        std::lock_guard<std::mutex> lock(g_uploadMutex);
        auto it = g_uploadStates.find(this);
        if (it == g_uploadStates.end())
        {
            return;
        }
        auto& subs = it->second.subscribers;
        auto keep = std::stable_partition(subs.begin(), subs.end(),
                                          [&](const auto& s) { return s.first != subscriptionId; });
        removed.assign(std::make_move_iterator(keep), std::make_move_iterator(subs.end()));
        subs.erase(keep, subs.end());
    }
}

bool ByteImageProvider::hasUploadBackend()
{
    return PlatformRegistry::instance().byteImageGpu() != nullptr;
}

bool ByteImageProvider::takeInjectedUploadFailure()
{
    return takeInjectedFailure(this);
}

uint32_t ByteImageProvider::injectUploadFailures(uint32_t count)
{
    std::lock_guard<std::mutex> lock(g_uploadMutex);
    UploadState& state = g_uploadStates[this];
    const uint32_t waiting = state.injectedFailures;
    setInjectedFailures(state, count);
    return waiting;
}

void ByteImageProvider::_releaseImage()
{
    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (gpu && m_gpuState)
    {
        gpu->releaseImage(m_gpuState);
    }
}

void ByteImageProvider::prepareDraw(float widgetWidth, float widgetHeight)
{
    // Most draws have nothing to poll. Do not take a lock for them.
    if (g_providersWaitingForCompletion.load(std::memory_order_relaxed) != 0)
    {
        getCompletedUploadId();
    }
}

ByteImageUploadResult ByteImageProvider::uploadBytesData(const uint8_t* bytes,
                                                         UInt2 size,
                                                         size_t stride,
                                                         PixelFormat format)
{
    ImageProviderChangeScope check(m_id, "uploadBytesData");
    if (bytes == nullptr)
    {
        return rejectUpload("uploadBytesData: the pixel pointer is null");
    }

    // structural validation. The renderer trusts `stride * height`
    // and memcpys that many bytes; bad arguments here translate directly into
    // an access-violation crash inside VCRUNTIME140!memcpy_repmovs.
    if (!isUploadShapeValid("ByteImageProvider::uploadBytesData", size, stride, format))
    {
        return rejectUpload("uploadBytesData: the size, format or stride is not valid");
    }
    return _uploadImage(&bytes, &stride, 1, size, format, false);
}

void ByteImageProvider::setBytesData(const uint8_t* bytes, UInt2 size, size_t stride, PixelFormat format)
{
    uploadBytesData(bytes, size, stride, format);
}

ByteImageUploadResult ByteImageProvider::uploadMipMappedBytesData(const uint8_t* const* mipMapBytes,
                                                                  size_t* mipMapStrides,
                                                                  size_t mipMapCount,
                                                                  UInt2 size,
                                                                  PixelFormat format)
{
    ImageProviderChangeScope check(m_id, "uploadMipMappedBytesData");
    if (mipMapBytes == nullptr)
    {
        return rejectUpload("uploadMipMappedBytesData: the pixel pointer is null");
    }
    if (mipMapStrides == nullptr || mipMapCount == 0)
    {
        OMNIUI_LOG_ERROR("setMipMappedBytesData: rejected upload with mipMapStrides=%p, mipMapCount=%zu. "
                       "Skipping GPU upload to avoid renderer crash.",
                       static_cast<const void*>(mipMapStrides), mipMapCount);
        return rejectUpload("uploadMipMappedBytesData: there are no mip levels or no strides");
    }
    // mipDivisor is uint32_t and doubles each iteration, so >= 32
    // iterations wraps it to 0 and the next "size.x / mipDivisor" is a divide-by-zero.
    // A real texture's mip chain tops out around 1 + log2(max_dim); even an 8K base dimension
    // is 14 levels. Cap at 32 to leave headroom but reject any path that would wrap.
    static constexpr size_t kMaxMipMapCount = 32;
    if (mipMapCount > kMaxMipMapCount)
    {
        OMNIUI_LOG_ERROR("setMipMappedBytesData: rejected upload with mipMapCount=%zu (>%zu); deep mip "
                       "chains would wrap the per-level divisor. Skipping GPU upload to avoid renderer crash.",
                       mipMapCount, kMaxMipMapCount);
        return rejectUpload("uploadMipMappedBytesData: there are more than 32 mip levels");
    }

    // validate the base mip level. The renderer derives all mip
    // sizes from `size` and reads `stride * height` bytes for each mip; bad
    // base inputs propagate to every mip.
    if (size.x == 0 || size.y == 0 || format == PixelFormat::eUnknown)
    {
        OMNIUI_LOG_ERROR("setMipMappedBytesData: rejected upload (size=%u x %u, format=%u). "
                       "Skipping GPU upload to avoid renderer crash.",
                       size.x, size.y, static_cast<uint32_t>(format));
        return rejectUpload("uploadMipMappedBytesData: the size or the format is not valid");
    }

    const size_t formatSize = getPixelFormatSize(format);
    if (formatSize == 0)
    {
        OMNIUI_LOG_ERROR("setMipMappedBytesData: rejected upload with unsupported format=%u (size=%u x %u). "
                       "Skipping GPU upload to avoid renderer crash.",
                       static_cast<uint32_t>(format), size.x, size.y);
        return rejectUpload("uploadMipMappedBytesData: the format is not supported");
    }

    uint32_t mipDivisor = 1;
    for (size_t mip = 0; mip < mipMapCount; ++mip)
    {
        const uint32_t mipMapSizeX = std::max(1U, size.x / mipDivisor);
        const size_t minMipStride = static_cast<size_t>(mipMapSizeX) * formatSize;
        if (mipMapStrides[mip] == kAutoCalculateStride)
        {
            mipMapStrides[mip] = minMipStride;
        }
        else if (mipMapStrides[mip] < minMipStride)
        {
            OMNIUI_LOG_ERROR("setMipMappedBytesData: rejected upload at mip=%zu with stride=%zu < width*texelSize=%zu "
                           "(base size=%u x %u, format=%u). Skipping GPU upload to avoid renderer crash.",
                           mip, mipMapStrides[mip], minMipStride, size.x, size.y,
                           static_cast<uint32_t>(format));
            return rejectUpload("uploadMipMappedBytesData: a mip stride is smaller than its row");
        }
        if (mipMapBytes[mip] == nullptr)
        {
            OMNIUI_LOG_ERROR("setMipMappedBytesData: rejected upload because mipMapBytes[%zu] is null "
                           "(base size=%u x %u, format=%u). Skipping GPU upload to avoid renderer crash.",
                           mip, size.x, size.y, static_cast<uint32_t>(format));
            return rejectUpload("uploadMipMappedBytesData: a mip level has no pixels");
        }
        mipDivisor *= 2;
    }

    return _uploadImage(mipMapBytes, mipMapStrides, mipMapCount, size, format, false);
}

void ByteImageProvider::setMipMappedBytesData(const uint8_t* const* mipMapBytes,
                                              size_t* mipMapStrides,
                                              size_t mipMapCount,
                                              UInt2 size,
                                              PixelFormat format)
{
    uploadMipMappedBytesData(mipMapBytes, mipMapStrides, mipMapCount, size, format);
}

void ByteImageProvider::setMipMappedBytesData(
    const uint8_t* bytes, UInt2 size, size_t stride, PixelFormat format, size_t maxMipLevels)
{
    uploadMipMappedBytesData(bytes, size, stride, format, maxMipLevels);
}

ByteImageUploadResult ByteImageProvider::uploadMipMappedBytesData(
    const uint8_t* bytes, UInt2 size, size_t stride, PixelFormat format, size_t maxMipLevels)
{
    ImageProviderChangeScope check(m_id, "uploadMipMappedBytesData");
    ByteImageUploadResult result;
    // Initialize the variables
    const uint8_t* rgbaDataMip0 = bytes;
    uint32_t width = size.x;
    uint32_t height = size.y;

    // validate shape BEFORE the log2 below — log2(0) is -infinity and the floor()+1
    // cast to size_t is undefined behaviour. The deeper guarded overload only runs once we have
    // a non-zero mip count, so the guard there cannot catch a zero base size in this entry point.
    if (bytes == nullptr)
    {
        return rejectUpload("uploadMipMappedBytesData: the pixel pointer is null");
    }
    if (width == 0 || height == 0)
    {
        OMNIUI_LOG_ERROR("setMipMappedBytesData (mip-generating overload): rejected upload with "
                       "zero-size base (size=%u x %u, format=%u). Skipping GPU upload to avoid "
                       "log2(0) and a downstream renderer crash.",
                       width, height, static_cast<uint32_t>(format));
        return rejectUpload("uploadMipMappedBytesData: the size is zero");
    }
    if (format == PixelFormat::eUnknown)
    {
        OMNIUI_LOG_ERROR("setMipMappedBytesData (mip-generating overload): rejected upload with "
                       "Format::eUnknown (size=%u x %u). Skipping GPU upload to avoid renderer crash.",
                       width, height);
        return rejectUpload("uploadMipMappedBytesData: the format is unknown");
    }

    std::vector<const uint8_t*> mipMapRgbaData;
    std::vector<size_t> mipMapStrides;

    // Calculate the maximum size of the image (either width or height)
    int maxSize = std::max(width, height);
    // Calculate the number of mipmap levels based on the maximum size
    const size_t calculatedMipMapCount = (size_t)std::floor(std::log2((double)maxSize)) + 1;
    size_t mipMapCount = std::min(maxMipLevels, calculatedMipMapCount);

    bool isMipFormatSupported = isMipGenFormatSupported(format);

    mipMapCount = isMipFormatSupported ? mipMapCount : 0;

    // If there is more than one mipmap level, generate the mipmaps
    if (mipMapCount > 1)
    {
        {
            OMNIUI_PROFILE_VERBOSE_ZONE("Mip map generation");

            // Resize the vectors to hold the mipmap data and strides
            mipMapRgbaData.resize(mipMapCount);
            mipMapStrides.resize(mipMapCount);

            // Initialize a variable to keep track of the divisor for each
            // mipmap level
            uint32_t mipDivisor = 1;
            // Loop through each mipmap level
            for (size_t mip = 0; mip < mipMapCount; ++mip)
            {
                mipMapStrides[mip] = kAutoCalculateStride;
                if (mip == 0)
                {
                    mipMapRgbaData[0] = rgbaDataMip0;
                }
                else
                {
                    // For subsequent mipmap levels, calculate the new width and
                    // height
                    uint32_t mipWidth = width / mipDivisor;
                    uint32_t mipHeight = height / mipDivisor;

                    // Calculate the width and height of the previous mipmap level
                    uint32_t prevMipWidth = width / (mipDivisor / 2);
                    uint32_t prevMipHeight = height / (mipDivisor / 2);

                    // Allocate memory for the new mipmap level and calculate
                    // the new data
                    uint8_t* mipData = (uint8_t*)::malloc(mipWidth * mipHeight * 4);
                    const uint8_t* prevMipData = mipMapRgbaData[mip - 1];

                    // Get a pointer to the previous mipmap level data
                    for (uint32_t y = 0; y < mipHeight; ++y)
                    {
                        uint32_t yp1 = 2 * y + 1;
                        if (yp1 >= prevMipHeight)
                            yp1 = prevMipHeight - 1;

                        for (uint32_t x = 0; x < mipWidth; ++x)
                        {
                            uint32_t xp1 = 2 * x + 1;
                            if (xp1 >= prevMipWidth)
                            {
                                xp1 = prevMipWidth - 1;
                            }

                            for (uint32_t ch = 0; ch < 4; ++ch)
                            {
                                int avgChannel = prevMipData[((2 * x) + (2 * y) * prevMipWidth) * 4 + ch] +
                                                 prevMipData[(xp1 + (2 * y) * prevMipWidth) * 4 + ch] +
                                                 prevMipData[(xp1 + yp1 * prevMipWidth) * 4 + ch] +
                                                 prevMipData[((2 * x) + yp1 * prevMipWidth) * 4 + ch];
                                avgChannel /= 4;
                                if (avgChannel < 0)
                                {
                                    avgChannel = 0;
                                }
                                if (avgChannel > 255)
                                {
                                    avgChannel = 255;
                                }
                                mipData[(x + y * mipWidth) * 4 + ch] = static_cast<uint8_t>(avgChannel);
                            }
                        }
                    }

                    mipMapRgbaData[mip] = mipData;
                }
                mipDivisor *= 2;
            }
        }

        result = this->uploadMipMappedBytesData((const uint8_t**)mipMapRgbaData.data(), mipMapStrides.data(),
                                                mipMapCount,
                                                { static_cast<uint32_t>(width), static_cast<uint32_t>(height) },
                                                format);

        // Delete all but the 0-th mip level
        for (size_t mip = 1; mip < mipMapCount; ++mip)
        {
            ::free((void*)mipMapRgbaData[mip]);
        }
    }
    else
    {
        result = this->uploadBytesData(bytes, size, stride, format);
    }
    return result;
}

ByteImageUploadResult ByteImageProvider::uploadBytesDataFromGPU(const uint8_t* bytes,
                                                                UInt2 size,
                                                                size_t stride,
                                                                PixelFormat format)
{
    ImageProviderChangeScope check(m_id, "uploadBytesDataFromGPU");
    if (bytes == nullptr)
    {
        return rejectUpload("uploadBytesDataFromGPU: the pixel pointer is null");
    }

    // same renderer memcpy path as the CPU upload below; validate
    // shape before forwarding to avoid an access-violation crash in
    // VCRUNTIME140!memcpy_repmovs.
    if (!isUploadShapeValid("ByteImageProvider::uploadBytesDataFromGPU", size, stride, format))
    {
        return rejectUpload("uploadBytesDataFromGPU: the size, format or stride is not valid");
    }

    return _uploadImage(&bytes, &stride, 1, size, format, /*fromGpu*/ true);
}

void ByteImageProvider::setBytesDataFromGPU(const uint8_t* bytes,
                                            UInt2 size,
                                            size_t stride,
                                            PixelFormat format)
{
    uploadBytesDataFromGPU(bytes, size, stride, format);
}

}
}
