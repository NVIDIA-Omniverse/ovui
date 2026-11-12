/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#if defined(_WIN32) && !defined(NOMINMAX)
#  define NOMINMAX
#endif

#include "NativeFramePacing.h"

#include "NativeFramePacingHooks.h"
#include "NativeFrameReady.h"
#include "NativeTiming.h"
#include "VulkanBackend.h"
#include "VulkanByteImageGpu.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_vulkan.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <deque>
#include <limits>
#include <mutex>
#include <new>
#include <thread>
#include <utility>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

namespace {

using Clock = std::chrono::steady_clock;
constexpr size_t kSlotCount = 12; // three complete maximum-size ordered groups
constexpr uint64_t kMaxFramePixels = 16'777'216; // bounded 4K-class slot-ring allocation

uint64_t rgbaFingerprint(const uint8_t* pixels, uint64_t size)
{
    // FNV-1a over the bounded mapped RGBA result. Hashing happens once while
    // the CPU copy is already hot and proves pixel-content change separately
    // from slot/group identity.
    uint64_t hash = 1469598103934665603ull;
    for (uint64_t index = 0; pixels && index < size; ++index)
    {
        const uint8_t value = pixels[index];
        hash ^= value;
        hash *= 1099511628211ull;
    }
    return hash;
}

class SavedDrawData
{
public:
    SavedDrawData(const ImDrawData* source, void* presentationKey)
    {
        if (!source || !source->Valid)
            return;
        const ImTextureID key = static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(presentationKey));
        ImVec4 viewportBounds{};
        bool hasViewportBounds = false;
        size_t lastViewportCommand = 0;
        size_t ordinal = 0;
        for (int listIndex = 0; listIndex < source->CmdListsCount; ++listIndex)
        {
            const ImDrawList* list = source->CmdLists[listIndex];
            if (!list)
                continue;
            for (int cmdIndex = 0; cmdIndex < list->CmdBuffer.Size; ++cmdIndex, ++ordinal)
            {
                const ImDrawCmd& cmd = list->CmdBuffer[cmdIndex];
                if (cmd.GetTexID() != key)
                    continue;
                ImVec4 bounds{};
                if (!commandBounds(*list, cmd, bounds))
                    continue;
                if (!hasViewportBounds)
                    viewportBounds = bounds;
                else
                {
                    viewportBounds.x = std::min(viewportBounds.x, bounds.x);
                    viewportBounds.y = std::min(viewportBounds.y, bounds.y);
                    viewportBounds.z = std::max(viewportBounds.z, bounds.z);
                    viewportBounds.w = std::max(viewportBounds.w, bounds.w);
                }
                hasViewportBounds = true;
                lastViewportCommand = ordinal;
            }
        }
        if (!hasViewportBounds)
            return;

        m_data = *source;
        m_data.CmdLists.clear();
        m_data.Textures = nullptr; // texture uploads remain owned by the UI thread
        m_lists.reserve(static_cast<size_t>(source->CmdListsCount));
        ordinal = 0;
        for (int i = 0; i < source->CmdListsCount; ++i)
        {
            ImDrawList* clone = source->CmdLists[i]->CloneOutput();
            if (!clone)
                continue;
            m_lists.emplace_back(clone);
            m_data.CmdLists.push_back(clone);
            for (int cmdIndex = 0; cmdIndex < clone->CmdBuffer.Size; ++cmdIndex)
            {
                ImDrawCmd& cmd = clone->CmdBuffer[cmdIndex];
                const bool afterViewport = ordinal > lastViewportCommand;
                ++ordinal;
                if (cmd.UserCallback && cmd.UserCallback != ImDrawCallback_ResetRenderState)
                {
                    // Callback data can point into UI-owned storage and a
                    // callback may draw outside its declared geometry. A
                    // post-viewport callback therefore makes this generation
                    // unsafe to replay; no callback ever crosses threads.
                    if (afterViewport)
                        m_unsafeCallback = true;
                    cmd.UserCallback = nullptr;
                    cmd.UserCallbackData = nullptr;
                    cmd.ElemCount = 0;
                    cmd.TexRef = ImTextureRef(key);
                    m_viewportCommands.push_back(&cmd); // resolves zero-count bind to a live slot
                    continue;
                }
                const bool imguiOwnedAtlas = cmd.TexRef._TexData != nullptr;
                const ImTextureID textureId = cmd.GetTexID();
                if (textureId == key)
                {
                    cmd.TexRef = ImTextureRef(textureId);
                    m_viewportCommands.push_back(&cmd);
                }
                else if (afterViewport && imguiOwnedAtlas && intersects(cmd.ClipRect, viewportBounds))
                {
                    // Text and solid-color primitives use the ImGui-owned
                    // atlas, whose descriptor remains alive until backend
                    // shutdown. Clip replay to the viewport so nonviewport UI
                    // remains exactly as composed on the UI thread.
                    cmd.TexRef = ImTextureRef(textureId);
                    cmd.ClipRect.x = std::max(cmd.ClipRect.x, viewportBounds.x);
                    cmd.ClipRect.y = std::max(cmd.ClipRect.y, viewportBounds.y);
                    cmd.ClipRect.z = std::min(cmd.ClipRect.z, viewportBounds.z);
                    cmd.ClipRect.w = std::min(cmd.ClipRect.w, viewportBounds.w);
                }
                else
                {
                    if (afterViewport && !imguiOwnedAtlas && intersects(cmd.ClipRect, viewportBounds))
                    {
                        ImVec4 bounds{};
                        if (commandBounds(*clone, cmd, bounds))
                        {
                            bounds.x = std::max(bounds.x, viewportBounds.x);
                            bounds.y = std::max(bounds.y, viewportBounds.y);
                            bounds.z = std::min(bounds.z, viewportBounds.z);
                            bounds.w = std::min(bounds.w, viewportBounds.w);
                            appendCopyRegion(bounds, source);
                        }
                    }
                    // External descriptors are never dereferenced by the
                    // presenter. Their final UI-rate pixels (including correct
                    // translucent blending and later overlaps) are restored
                    // from VulkanBackend's native base snapshot instead.
                    cmd.UserCallback = nullptr;
                    cmd.UserCallbackData = nullptr;
                    cmd.ElemCount = 0;
                    cmd.TexRef = ImTextureRef(key);
                    m_viewportCommands.push_back(&cmd); // backend binds even for a zero-count draw
                }
            }
        }
        m_data.CmdListsCount = m_data.CmdLists.Size;
        m_valid = !m_unsafeCallback && !m_viewportCommands.empty();
    }

    bool valid() const { return m_valid; }
    ImDrawData* selectViewportImage(void* descriptor)
    {
        const ImTextureRef texture(static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(descriptor)));
        for (ImDrawCmd* cmd : m_viewportCommands)
            cmd->TexRef = texture;
        return &m_data;
    }

    const std::vector<NativeFramePacingCopyRegion>& copyRegions() const { return m_copyRegions; }

private:
    static bool intersects(const ImVec4& a, const ImVec4& b)
    {
        return a.x < b.z && a.y < b.w && a.z > b.x && a.w > b.y;
    }

    static bool commandBounds(const ImDrawList& list, const ImDrawCmd& cmd, ImVec4& bounds)
    {
        if (!cmd.ElemCount || cmd.IdxOffset > static_cast<unsigned int>(list.IdxBuffer.Size) ||
            cmd.ElemCount > static_cast<unsigned int>(list.IdxBuffer.Size) - cmd.IdxOffset)
            return false;
        float minX = std::numeric_limits<float>::max();
        float minY = std::numeric_limits<float>::max();
        float maxX = std::numeric_limits<float>::lowest();
        float maxY = std::numeric_limits<float>::lowest();
        for (unsigned int i = 0; i < cmd.ElemCount; ++i)
        {
            const size_t vertex = static_cast<size_t>(cmd.VtxOffset) + list.IdxBuffer[cmd.IdxOffset + i];
            if (vertex >= static_cast<size_t>(list.VtxBuffer.Size))
                return false;
            const ImVec2& position = list.VtxBuffer[static_cast<int>(vertex)].pos;
            minX = std::min(minX, position.x);
            minY = std::min(minY, position.y);
            maxX = std::max(maxX, position.x);
            maxY = std::max(maxY, position.y);
        }
        bounds = { std::max(minX, cmd.ClipRect.x), std::max(minY, cmd.ClipRect.y),
                   std::min(maxX, cmd.ClipRect.z), std::min(maxY, cmd.ClipRect.w) };
        return bounds.x < bounds.z && bounds.y < bounds.w;
    }

    void appendCopyRegion(const ImVec4& bounds, const ImDrawData* source)
    {
        const float x0 = (bounds.x - source->DisplayPos.x) * source->FramebufferScale.x;
        const float y0 = (bounds.y - source->DisplayPos.y) * source->FramebufferScale.y;
        const float x1 = (bounds.z - source->DisplayPos.x) * source->FramebufferScale.x;
        const float y1 = (bounds.w - source->DisplayPos.y) * source->FramebufferScale.y;
        const int framebufferWidth = static_cast<int>(source->DisplaySize.x * source->FramebufferScale.x);
        const int framebufferHeight = static_cast<int>(source->DisplaySize.y * source->FramebufferScale.y);
        const int left = std::max(0, std::min(framebufferWidth, static_cast<int>(std::floor(x0))));
        const int top = std::max(0, std::min(framebufferHeight, static_cast<int>(std::floor(y0))));
        const int right = std::max(0, std::min(framebufferWidth, static_cast<int>(std::ceil(x1))));
        const int bottom = std::max(0, std::min(framebufferHeight, static_cast<int>(std::ceil(y1))));
        if (left < right && top < bottom)
        {
            m_copyRegions.push_back({ static_cast<uint32_t>(left), static_cast<uint32_t>(top),
                                      static_cast<uint32_t>(right - left),
                                      static_cast<uint32_t>(bottom - top) });
        }
    }

    struct DrawListDeleter
    {
        void operator()(ImDrawList* drawList) const { IM_DELETE(drawList); }
    };
    ImDrawData m_data;
    std::vector<std::unique_ptr<ImDrawList, DrawListDeleter>> m_lists;
    std::vector<ImDrawCmd*> m_viewportCommands;
    std::vector<NativeFramePacingCopyRegion> m_copyRegions;
    bool m_valid = false;
    bool m_unsafeCallback = false;
};

/// Point a provider at an externally owned ImGui texture reference without
/// releasing its byte-image GPU storage.
///
/// ImageProvider::setImageData() calls _releaseImage(), but an ImGui draw list
/// assembled earlier in the same UI frame can still contain one of this
/// provider's Vulkan descriptor sets. The retained GPU state is reused by the
/// next synchronous byte upload and is released normally with the provider.
/// ByteImageProvider is shared with Kit, so the standalone backend reaches the
/// protected fields through this derived type instead of adding a method there.
struct PresentationKeyAccess : ByteImageProvider
{
    static void install(ByteImageProvider& provider, void* imGuiReference, UInt2 size, PixelFormat format)
    {
        if (provider.*(&PresentationKeyAccess::m_isShutdown))
            return;
        provider.*(&PresentationKeyAccess::m_imGuiReference) = imGuiReference;
        provider.*(&PresentationKeyAccess::m_imageSize) = size;
        provider.*(&PresentationKeyAccess::m_imageFormat) = format;
        provider.*(&PresentationKeyAccess::m_imageMipCount) = 1;
    }
};

void installPresentationKey(ByteImageProvider& provider, void* imGuiReference, UInt2 size, PixelFormat format)
{
    PresentationKeyAccess::install(provider, imGuiReference, size, format);
}

bool patchViewportImage(ImDrawData* drawData, void* presentationKey, void* descriptor)
{
    if (!drawData || !presentationKey || !descriptor)
        return false;
    const ImTextureID key = static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(presentationKey));
    const ImTextureRef selected(static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(descriptor)));
    bool patched = false;
    for (int listIndex = 0; listIndex < drawData->CmdListsCount; ++listIndex)
    {
        ImDrawList* list = drawData->CmdLists[listIndex];
        if (!list)
            continue;
        for (int cmdIndex = 0; cmdIndex < list->CmdBuffer.Size; ++cmdIndex)
        {
            ImDrawCmd& cmd = list->CmdBuffer[cmdIndex];
            if (cmd.GetTexID() == key)
            {
                cmd.TexRef = selected;
                patched = true;
            }
        }
    }
    return patched;
}

struct CameraPublication
{
    uint32_t width = 0;
    uint32_t height = 0;
    std::array<double, 16> world{};
    uint64_t serial = 0;
};

/// A GPU-resident image keeps the renderer mapping behind it live so the device
/// pointer stays valid until the Vulkan upload has consumed it. The upload path
/// queues its device-to-device copy and its CUDA-to-Vulkan semaphore signal on
/// the legacy default stream. publishGroup() hands that stream to the render
/// worker, which releases the mapping on it, so the renderer holds its
/// allocation without a CPU hard wait.
/// Stream ids: 0 = no synchronisation, 1 = the legacy default CUDA stream.
constexpr uint64_t kCudaDefaultStream = 1;

/// A number for the calling thread, unique for the life of the process on
/// every platform. A system thread id can be given again to a later thread.
uint64_t currentThreadIdentity()
{
    static std::atomic<uint64_t> s_lastIdentity{ 0 };
    thread_local const uint64_t identity = ++s_lastIdentity;
    return identity;
}

/// Outcome of publishing one completed renderer result.
enum class PublishResult
{
    ePublished,        ///< the group reached the slot ring
    eSkippedRetryable, ///< this frame was dropped; the session stays alive
    eFailed,           ///< unrecoverable; the session must stop
};

struct Slot
{
    IByteImageGpu::Handle gpuState = nullptr;
    void* descriptor = nullptr;
    uint32_t width = 0;
    uint32_t height = 0;
    uint64_t imageSerial = 0;
    uint64_t contentFingerprint = 0;
    uint64_t ownershipGeneration = 0;
    uint32_t references = 0;
    uint32_t readers = 0;
};

struct FrameGroup
{
    std::vector<size_t> slots;
    std::vector<double> frameEndTimes;
    size_t next = 0;
    uint64_t rendererFrameSerial = 0;
    uint64_t ownershipGeneration = 0;
    std::array<double, 16> cameraWorld{};
};


class NativeFramePacingService
{
public:
    ~NativeFramePacingService() { shutdown(); }

    bool setPresentRate(double rate)
    {
        if (!std::isfinite(rate) || rate < -1.0 || rate > 1000.0)
            return false;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            if (rate != 0.0 && (!m_platformBackend || !m_platformBackend->isInitialized()))
            {
                failLocked("native presentation requires a registered standalone Vulkan backend");
                m_stats.statusReason = "backend_unavailable";
                return false;
            }
            m_presentRate = rate;
            if (!m_active && m_stats.statusReason == "backend_unavailable")
            {
                m_stats.statusReason = "inactive";
                m_stats.lastError.clear();
            }
            if (m_active && m_provider)
            {
                // The stable identity is itself a valid black descriptor, so
                // both active replay and the rate-zero handoff can expose the
                // same key without borrowing a producer slot into UI geometry.
                installPresentationKey(*m_provider, m_presentationKey, {m_providerWidth, m_providerHeight}, PixelFormat::eRGBA8_UNORM);
            }
        }
        m_cv.notify_all();
        return true;
    }

    double presentRate() const
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        return m_presentRate;
    }

    uint64_t start(uintptr_t renderer,
                   const char* libraryPath,
                   uint32_t renderVarStride,
                   uint32_t renderVarNameOffset,
                   uint32_t renderVarHandleOffset,
                   std::shared_ptr<ByteImageProvider> provider,
                   const char* renderProductPath,
                   const char* cameraPath,
                   uint32_t width,
                   uint32_t height)
    {
        const NativeFramePacingHooks* hooks = getNativeFramePacingHooks();
        if (!hooks)
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            const std::string message =
                "native frame pacing has no renderer hooks installed";
            ++m_stats.errors;
            m_stats.lastError = message;
            m_stats.statusReason = "hooks_unavailable";
            // Callers retry start every frame; report the absence one time.
            if (!m_missingHooksReported)
            {
                m_missingHooksReported = true;
                // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
                fprintf(stderr, "NativeFramePacing: %s\n", message.c_str());
            }
            return 0;
        }
        // Rules 24.8 to 24.10: check what the frame source can do before any
        // thread starts. A frame source that cannot do all of it presents on
        // the UI tick.
        NativeFramePacingCapabilities capabilities{};
        capabilities.structSize = sizeof(capabilities);
        hooks->queryCapabilities(&capabilities);
        if (!capabilities.operatesOffUiThread || !capabilities.usesOwnQueue || !capabilities.presentReadsImages)
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            // Rule 24.15: name each check that failed.
            std::string failed;
            if (!capabilities.operatesOffUiThread)
                failed += "; it cannot operate on a thread other than the UI thread (rule 24.8)";
            if (!capabilities.usesOwnQueue)
                failed += "; the rendering and presentation threads cannot each get their own queue (rule 24.9)";
            if (!capabilities.presentReadsImages)
                failed += "; the presentation thread cannot read its images and their completion signals (rule 24.10)";
            const std::string message =
                "the frame source does not meet the conditions for threaded frame pacing" + failed;
            const bool repeated = m_stats.lastError == message;
            m_stats.lastError = message;
            m_stats.statusReason = "frame_source_capability";
            if (!repeated)
                // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
                fprintf(stderr, "NativeFramePacing: %s\n", message.c_str());
            return 0;
        }
        if (!ensureWorkerThreads())
        {
            fail("failed to start persistent native frame-pacing workers");
            return 0;
        }
        if (!renderer || !provider || !renderProductPath || !renderProductPath[0] || !cameraPath || !cameraPath[0] ||
            !width || !height || static_cast<uint64_t>(width) * height > kMaxFramePixels)
        {
            fail("native frame pacing start received an invalid borrow or path");
            return 0;
        }
        std::unique_lock<std::mutex> lock(m_mutex);
        auto* gpu = PlatformRegistry::instance().byteImageGpu();
        VulkanBackend* backend = m_platformBackend;
        if (!gpu || !backend || !backend->isInitialized())
        {
            failLocked("native frame pacing requires the active standalone Vulkan backend");
            m_stats.statusReason = "backend_unavailable";
            return 0;
        }

        if (m_active)
        {
            failLocked("a native frame pacing borrow is already active");
            return 0;
        }
        if (!ensureStablePresentationKeyLocked(gpu, backend))
        {
            failLocked("failed to create the persistent Vulkan presentation key");
            return 0;
        }
        // The hooks borrow the renderer under the token this session will use.
        const uint64_t token = m_nextToken + 1;
        NativeFramePacingOpenDesc openDesc{};
        openDesc.structSize = sizeof(openDesc);
        openDesc.renderer = renderer;
        openDesc.libraryPath = libraryPath;
        openDesc.renderVarStride = renderVarStride;
        openDesc.renderVarNameOffset = renderVarNameOffset;
        openDesc.renderVarHandleOffset = renderVarHandleOffset;
        openDesc.renderProductPath = renderProductPath;
        openDesc.cameraPath = cameraPath;
        openDesc.host = &m_host;
        const uint32_t openStatus = hooks->openRenderer(token, &openDesc);
        if (openStatus != eNativeFramePacingOk)
        {
            const std::string message = hookError(
                hooks, "the renderer hooks could not borrow the renderer");
            if (openStatus == eNativeFramePacingIncompatible)
            {
                // Callers retry start every frame; report a persistent mismatch once.
                const bool repeated = m_stats.lastError == message;
                ++m_stats.errors;
                m_stats.lastError = message;
                m_stats.statusReason = "runtime_incompatible";
                if (!repeated)
                    // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
                    fprintf(stderr, "NativeFramePacing: %s\n", message.c_str());
            }
            else
            {
                failLocked(message);
            }
            return 0;
        }
        m_hooks = hooks;
        m_gpu = gpu;
        m_backend = backend;
        m_provider = std::move(provider);
        // The key is a dedicated valid Vulkan descriptor, separate from the
        // 12 producer slots. Saved UI geometry can match it by identity while
        // an input callback may safely stop pacing mid-widget-walk: draw
        // commands already emitted in that walk still bind a live descriptor.
        m_presentationKey = m_stablePresentationDescriptor;
        m_providerKeyInstalled = false;
        m_ownershipWidth = width;
        m_ownershipHeight = height;
        m_stopRequested = false;
        m_renderPauseRequested = false;
        m_renderPaused = false;
        m_sessionReady = false;
        m_active = true;
        m_renderExited = false;
        m_presentExited = false;
        m_renderFatal = false;
        m_lastSelected = invalidSlot();
        m_lastReal = invalidSlot();
        m_hasSelectedCameraWorld = false;
        m_selectedImageGenerated = false;
        m_lastPresentedImageSerial = 0;
        m_lastPresentedRendererFrameSerial = 0;
        m_hasLastPresentedRendererFrameSerial = false;
        m_nextRendererFrameSerial = 0;
        m_hasLastSuccessfulPresentTime = false;
        m_hasLastScheduledPresentationTime = false;
        m_hasLastPresentedFrameEndTime = false;
        m_lastPresentedFrameEndTime = 0.0;
        m_hasLastAcceptedRealEndTime = false;
        m_lastAcceptedRealEndTime = 0.0;
        m_lastPresentedContentFingerprint = 0;
        m_hasLastPresentedContentFingerprint = false;
        m_token = ++m_nextToken;
        m_stats = {};
        m_stats.metricsEpoch = ++m_nextMetricsEpoch;
        m_stats.supported = true;
        m_stats.active = true;
        m_stats.ownershipGeneration = 1;
        m_stats.statusReason = "active";
        refreshRendererInfoLocked();

        std::vector<uint8_t> initialPixels;
        try
        {
            m_slots.resize(kSlotCount);
            initialPixels.assign(static_cast<size_t>(width) * height * 4, 0);
        }
        catch (...)
        {
            failLocked("failed to allocate bounded initial frame-slot storage");
            lock.unlock();
            // stop() also ends the session the hooks' render worker was given.
            while (!stop(token))
            {
                // The renderer borrow cannot return to Python while the hooks
                // still hold a result or a map. There is no cancellation call.
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            return 0;
        }
        const uint8_t* initialData = initialPixels.data();
        size_t initialStride = static_cast<size_t>(width) * 4;
        try
        {
            for (Slot& slot : m_slots)
            {
                slot.gpuState = m_gpu->createState();
                if (!slot.gpuState)
                    throw std::bad_alloc();
                const IByteImageGpu::UpdateResult initialized = m_gpu->updateImage(
                    slot.gpuState, &initialData, &initialStride, 1, {width, height},
                    PixelFormat::eRGBA8_UNORM, false, 0, 0, 0);
                if (!initialized.imGuiReference)
                {
                    failLocked("failed to pre-create Vulkan frame slot image/view/sampler/descriptor");
                    lock.unlock();
                    stop(m_token);
                    return 0;
                }
                slot.descriptor = initialized.imGuiReference;
                slot.width = width;
                slot.height = height;
            }
        }
        catch (...)
        {
            failLocked("failed to allocate a Vulkan presentation slot");
            lock.unlock();
            stop(m_token);
            return 0;
        }

        // This stable valid descriptor is what saved draw data records. Only
        // the presenter resolves it to the selected ring slot; UI ticks never
        // install produced frames. Ordinary Vulkan may safely sample its black
        // pixel during a rate change or re-entrant stop.
        // The previous synchronous provider image may still be referenced by
        // the UI submission from the preceding tick. Drain that submission
        // before switching the visible provider reference to the stable key;
        // the provider-owned descriptor storage itself remains allocated.
        {
            std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
            if (vkDeviceWaitIdle(m_backend->getDevice()) != VK_SUCCESS)
            {
                failLocked("failed to drain Vulkan before installing the stable viewport key");
                lock.unlock();
                stop(m_token);
                return 0;
            }
        }
        installPresentationKey(*m_provider, m_presentationKey, {width, height}, PixelFormat::eRGBA8_UNORM);
        m_providerKeyInstalled = true;
        m_providerWidth = width;
        m_providerHeight = height;
        m_sessionReady = true;
        m_renderOnChange = false;
        m_renderKick = true;
        m_cv.notify_all();
        return m_token;
    }

    bool publish(uint64_t token,
                 uint32_t width,
                 uint32_t height,
                 const std::array<double, 16>& world,
                 const std::array<double, 3>& velocity,
                 double timestamp)
    {
        if (!width || !height || !std::isfinite(timestamp))
            return false;
        for (double value : world)
            if (!std::isfinite(value)) return false;
        for (double value : velocity)
            if (!std::isfinite(value)) return false;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_active || token != m_token || m_stopRequested ||
            m_renderPauseRequested || m_renderPaused || m_renderExited ||
            !m_backend || !m_backend->isInitialized())
            return false;
        m_camera.width = width;
        m_camera.height = height;
        m_camera.world = world;
        ++m_camera.serial;
        ++m_stats.cameraPublications;
        // Safe because publish is called on the UI thread and the provider's
        // texture reference remains the same stable key.
        if (width != m_providerWidth || height != m_providerHeight)
        {
            installPresentationKey(*m_provider, m_presentationKey, {width, height}, PixelFormat::eRGBA8_UNORM);
            m_providerWidth = width;
            m_providerHeight = height;
        }
        m_cv.notify_all();
        return true;
    }

    bool pauseRender(uint64_t token)
    {
        bool paused = false;
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait(lock, [this]() { return !m_stopCallActive; });
            if (!m_active || token != m_token || m_stopRequested)
            {
                return false;
            }
            if (m_renderPaused)
            {
                return true;
            }
            m_stopCallActive = true;
            m_renderPauseRequested = true;
            m_cv.notify_all();
        }
        cancelHook(token);

        // The render worker belongs to the hooks. They wait until it has
        // parked or left the session, then release every retained renderer
        // handle. The worker reports the park through renderLoopEnded().
        const bool released = pauseRenderWorkerHook(token);
        std::unique_lock<std::mutex> lock(m_mutex);
        m_cv.wait(lock, [this, token]() {
            return !m_active || token != m_token || m_stopRequested ||
                m_renderPaused || m_renderExited;
        });
        paused = released && m_active && token == m_token &&
            m_renderPaused && !m_stopRequested;
        if (paused)
        {
            // A render pause is the ownership boundary used before a Stage,
            // camera, RenderProduct, or extent mutation.  No queued image or
            // renderer-time anchor from the old state may be interpreted as
            // part of the resumed state.  The renderer may restart its
            // frame-time origin after such a mutation (and does so for the
            // selection/picking path), so preserve the last displayed image
            // but retire every unpublished old-state image and begin a new
            // cadence/ownership generation on resume.
            discardGroupLocked(m_currentGroup, true);
            discardGroupLocked(m_pendingGroup, true);
            ++m_stats.ownershipGeneration;
            if (m_lastSelected < m_slots.size())
                m_slots[m_lastSelected].ownershipGeneration = m_stats.ownershipGeneration;
            m_hasLastAcceptedRealEndTime = false;
            m_lastAcceptedRealEndTime = 0.0;
            m_hasLastPresentedFrameEndTime = false;
            m_lastPresentedFrameEndTime = 0.0;
            m_hasLastPresentedRendererFrameSerial = false;
            m_hasLastScheduledPresentationTime = false;
            m_hasLastSuccessfulPresentTime = false;
        }
        if (!released)
        {
            m_stats.statusReason = "cleanup_retry_required";
        }
        m_stopCallActive = false;
        m_cv.notify_all();
        return paused;
    }

    bool resumeRender(uint64_t token, bool render)
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_cv.wait(lock, [this]() { return !m_stopCallActive; });
        if (!m_active || token != m_token || m_stopRequested)
        {
            return false;
        }
        if (!m_renderPaused)
        {
            return !m_renderPauseRequested && !m_renderExited;
        }
        m_stopCallActive = true;
        m_renderPauseRequested = false;
        m_cv.notify_all();
        lock.unlock();
        // Wake the parked worker of the hooks. It reports the resume through
        // renderResumed(), which clears m_renderPaused.
        const bool woken = m_hooks && m_hooks->resumeRenderWorker(token);
        lock.lock();
        if (!woken)
        {
            // The worker has left the session; the caller stops it.
            if (m_active && token == m_token)
            {
                m_renderPaused = false;
                m_renderExited = true;
                m_stats.renderLoopExited = true;
            }
            m_stopCallActive = false;
            m_cv.notify_all();
            return false;
        }
        m_cv.wait(lock, [this, token]() {
            return !m_active || token != m_token || m_stopRequested ||
                !m_renderPaused || m_renderExited;
        });
        const bool resumed = m_active && token == m_token &&
            !m_stopRequested && !m_renderPauseRequested && !m_renderPaused &&
            !m_renderExited;
        // What changed during the pause is rendered, unless the caller says
        // that its change does not change the picture.
        if (render)
            m_renderKick = true;
        m_stopCallActive = false;
        m_cv.notify_all();
        return resumed;
    }

    bool setRenderPolicy(uint64_t token, bool onChange, uint32_t settleFrames)
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_active || token != m_token || m_stopRequested)
            return false;
        m_renderOnChange = onChange;
        m_renderSettleFrames = settleFrames;
        m_renderKick = true;
        m_cv.notify_all();
        return true;
    }

    bool requestRender(uint64_t token)
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_active || token != m_token || m_stopRequested)
            return false;
        m_renderKick = true;
        m_cv.notify_all();
        return true;
    }

    bool stop(uint64_t token)
    {
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait(lock, [this]() { return !m_stopCallActive; });
            // Platform shutdown may have already drained this exact borrow
            // before the Python adapter gets its own lifecycle callback. Treat
            // revocation of the most recently issued token as idempotent; a
            // stale token can never acknowledge a newer active borrow.
            if (!m_active)
                return token != 0 && token == m_token;
            if (token != m_token)
                return false;
            m_stopCallActive = true;
            m_stopRequested = true;
            m_cv.notify_all();
        }
        cancelHook(token);

        // The hooks wake their render worker if it is parked, wait until it
        // has left the session, then drain the renderer results and maps.
        // Work the renderer already queued cannot be cancelled, so a failed
        // release is retried by a later stop(token).
        const bool closed = closeRendererHook(token);
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            if (m_sessionReady)
            {
                m_cv.wait(lock, [this, token]() {
                    return !m_active || token != m_token || m_presentExited;
                });
            }
        }
        if (!closed)
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_stats.active = true;
            m_stats.statusReason = "cleanup_retry_required";
            // Keep the borrowed renderer, hooks, slots, provider, and token
            // pinned. A later stop(token) call retries only the failed releases.
            m_stopCallActive = false;
            m_cv.notify_all();
            return false;
        }

        std::unique_lock<std::mutex> lock(m_mutex);
        m_cv.wait(lock, [this]() { return !m_uiSubmitting; });
        discardGroupLocked(m_currentGroup);
        discardGroupLocked(m_pendingGroup);
        if (m_lastSelected != invalidSlot())
        {
            releaseSlotReferenceLocked(m_lastSelected);
            m_lastSelected = invalidSlot();
        }
        if (m_lastReal != invalidSlot())
        {
            releaseSlotReferenceLocked(m_lastReal);
            m_lastReal = invalidSlot();
        }
        // Drain every UI/presenter sample before the native slot resources are
        // destroyed. The provider mutation below preserves its byte-image
        // descriptor storage for any ImGui draw list already assembled on CPU.
        if (m_backend && m_backend->getDevice() != VK_NULL_HANDLE)
        {
            std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
            if (vkDeviceWaitIdle(m_backend->getDevice()) == VK_SUCCESS)
                m_backend->releaseNativeFramePacingBase();
        }
        // Keep the persistent key installed across the re-entrant stop. The
        // current ImGui walk may already have copied it into a draw command;
        // unlike a provider-address sentinel it remains a valid black Vulkan
        // descriptor until platform shutdown. The next synchronous image
        // upload replaces it through the provider's ordinary state.
        if (m_provider && m_providerKeyInstalled)
            installPresentationKey(*m_provider, m_stablePresentationDescriptor,
                {m_providerWidth, m_providerHeight},
                PixelFormat::eRGBA8_UNORM);
        m_providerKeyInstalled = false;
        if (m_gpu)
        {
            for (Slot& slot : m_slots)
            {
                if (slot.gpuState)
                {
                    m_gpu->destroyState(slot.gpuState);
                }
                slot = {};
            }
        }
        m_slots.clear();
        m_provider.reset();
        m_presentationKey = nullptr;
        m_gpu = nullptr;
        m_backend = nullptr;
        m_hooks = nullptr;
        m_drawData.reset();
        m_camera = {};
        m_sessionReady = false;
        m_active = false;
        m_stopRequested = false;
        m_renderPauseRequested = false;
        m_renderPaused = false;
        m_stats.active = false;
        m_stats.borrowedSlots = 0;
        m_stats.dlssGeneratedFrameEffectiveActive = false;
        m_stats.dlssGeneratedFrameEffectiveCount = 0;
        m_stats.statusReason = "inactive";
        m_stopCallActive = false;
        m_cv.notify_all();
        return true;
    }

    void shutdown()
    {
        uint64_t token = 0;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            token = m_active ? m_token : 0;
        }
        while (token && !stop(token))
        {
            // Platform teardown must not revoke the borrowed renderer or
            // destroy descriptors while the renderer still owns a result/map.
            // Queued renderer work cannot be cancelled, so retry the release.
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        std::thread presentThread;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_workerShutdownRequested = true;
            presentThread = std::move(m_presentThread);
        }
        m_cv.notify_all();
        // The hooks join their render worker, ovui joins its present worker.
        if (const NativeFramePacingHooks* hooks = getNativeFramePacingHooks())
        {
            hooks->shutdownWorker();
        }
        if (presentThread.joinable())
        {
            presentThread.join();
        }
        std::lock_guard<std::mutex> lock(m_mutex);
        releaseStablePresentationKeyLocked();
        // The renderer borrow is back, both workers are joined and the stable
        // key is gone. Only now may the slot be cleared; doing it earlier would
        // strand renderer results and destroy live descriptors.
        setNativeFramePacingHooks(nullptr);
    }

    NativeFramePacingStats stats()
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_active)
            refreshRendererInfoLocked();
        NativeFramePacingStats result = m_stats;
        result.supported = getNativeFramePacingHooks() != nullptr;
        result.active = m_active;
        result.sessionToken = m_active ? m_token : 0;
        result.presentRate = m_presentRate;
        result.borrowedSlots = 0;
        for (const Slot& slot : m_slots)
            if (slot.references || slot.readers) ++result.borrowedSlots;
        result.renderLoopExited = m_renderExited;
        result.renderLoopFatal = m_renderFatal;
        result.renderPaused = m_renderPaused;
        result.renderIdle = m_active && m_workerWaiting && !m_pendingGroup && !renderDueLocked();
        if (m_platformBackend)
        {
            result.windowSurfaceActive = m_platformBackend->hasWindowSurface();
            result.windowPresents = m_platformBackend->getWindowPresentCount();
            result.windowPresentDeferrals = m_platformBackend->getWindowPresentDeferralCount();
            result.swapchainRecreations = m_platformBackend->getSwapchainRecreationCount();
            result.swapchainWidth = m_platformBackend->getSwapchainWidth();
            result.swapchainHeight = m_platformBackend->getSwapchainHeight();
            result.backend = "vulkan";
            result.presentPolicy = "immediate_preferred";
            switch (m_platformBackend->getWindowPresentMode())
            {
                case VK_PRESENT_MODE_IMMEDIATE_KHR: result.activePresentMode = "IMMEDIATE"; break;
                case VK_PRESENT_MODE_MAILBOX_KHR: result.activePresentMode = "MAILBOX"; break;
                case VK_PRESENT_MODE_FIFO_KHR: result.activePresentMode = "FIFO"; break;
                default: result.activePresentMode = "unavailable"; break;
            }
        }
        if (!result.supported)
            result.statusReason = "hooks_unavailable";
        else if (!m_active && result.lastError.empty())
            result.statusReason = "inactive";
        else if (!m_active && !result.lastError.empty() && result.statusReason != "backend_unavailable" &&
                 result.statusReason != "runtime_incompatible" &&
                 result.statusReason != "frame_source_capability")
            result.statusReason = "runtime_error";
        if (result.dlssGeneratedFrameCapability.empty())
            result.dlssGeneratedFrameCapability =
                "DLSS-G runtime capability has not been evaluated for a native pacing session";
        return result;
    }

    void resetThroughputMetrics()
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        // A second viewport may be constructed while another viewport owns
        // the native session. It must not reset the active owner's epoch or
        // counters merely by attaching its synchronous telemetry hooks.
        if (m_active)
            return;
        m_stats.metricsEpoch = ++m_nextMetricsEpoch;
        m_stats.rendererCompletions = 0;
        m_stats.selectedContentChanges = 0;
    }

    void recordSynchronousRendererCompletion()
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_active)
            ++m_stats.rendererCompletions;
    }

    void recordSynchronousContentSelection()
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_active)
            ++m_stats.selectedContentChanges;
    }

    bool submitDrawData(VulkanBackend* backend,
                        const ImDrawData* drawData,
                        int width,
                        int height,
                        uint64_t* outGeneration,
                        bool forceFresh)
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        if (!m_active || m_stopRequested || m_presentRate == 0.0 || backend != m_backend)
        {
            m_uiGeometryUpdating = false;
            m_cv.notify_all();
            return false;
        }

        // The widget walk already completed even if retaining its replay copy
        // fails. Count that real boundary separately from replay-snapshot
        // publication so the UI tick rate remains observable when snapshots
        // are coalesced.
        ++m_stats.uiGeometryGenerations;
        if (!forceFresh && width == m_drawWidth && height == m_drawHeight &&
            m_drawData && m_presentedUiGeneration < m_uiGeneration)
        {
            // A complete snapshot is already waiting for the presenter. Avoid
            // serializing another full UI composition/base-image copy ahead
            // of it; the next UI tick publishes the latest geometry after the
            // outstanding snapshot is visible.
            if (outGeneration) *outGeneration = m_uiGeneration;
            m_uiGeometryUpdating = false;
            m_cv.notify_all();
            return true;
        }
        // The geometry gate is held from here to the end of this function, not
        // for the whole UI tick: the presenter replays m_drawData against the
        // base image, and both are replaced below.
        m_uiGeometryUpdating = true;
        m_cv.wait(lock, [this]() { return !m_active || !m_presenterComposing; });
        if (!m_active || m_stopRequested || backend != m_backend)
        {
            m_uiGeometryUpdating = false;
            m_cv.notify_all();
            return false;
        }
        ++m_uiGeneration;
        if (outGeneration) *outGeneration = m_uiGeneration;
        if (width != m_drawWidth || height != m_drawHeight)
        {
            // beginFrame may transactionally replace the main framebuffer and
            // the base snapshot below replaces its matching source image. No
            // prior generation may survive across that extent boundary.
            m_drawData.reset();
        }

        std::shared_ptr<SavedDrawData> saved;
        try
        {
            if (drawData)
                saved = std::make_shared<SavedDrawData>(drawData, m_presentationKey);
        }
        catch (...)
        {
            // Treat allocation failure like an unsafe snapshot below: retain
            // the last complete geometry and keep native ownership until a
            // complete replacement snapshot can be published.
        }
        size_t uiSlot = m_lastSelected != invalidSlot() ? m_lastSelected :
            (m_lastReal != invalidSlot() ? m_lastReal : 0);
        void* descriptor = uiSlot < m_slots.size() ? m_slots[uiSlot].descriptor : nullptr;
        const bool patched = patchViewportImage(
            const_cast<ImDrawData*>(drawData), m_presentationKey, descriptor);
        if (!patched)
        {
            // The viewport is hidden or absent in this generation, for example
            // behind another tab of its dock node. Do not replay stale viewport
            // geometry, and return false so the platform composes and presents
            // this UI itself. The presenter waits until a later generation
            // shows the viewport again.
            m_drawData.reset();
            m_uiGeometryUpdating = false;
            m_cv.notify_all();
            return false;
        }

        // Render the complete live UI once at the Python/UI cadence. This is
        // the only point that samples arbitrary external texture descriptors.
        // Before releasing the UI/presenter gate, snapshot those final pixels
        // into a persistent transfer-only native image.
        //
        // The GPU work runs without m_mutex, so the render and present threads
        // never wait for the UI's queue lock or frame fence. What it reads stays
        // valid: the gate keeps the presenter from composing, the sampled slot
        // is pinned as a reader, and stop() waits for m_uiSubmitting.
        const bool pinned = uiSlot < m_slots.size() && descriptor;
        if (pinned)
            ++m_slots[uiSlot].readers;
        VulkanBackend* gpuBackend = m_backend;
        m_uiSubmitting = true;
        lock.unlock();
        bool uiComposed = false;
        bool baseCaptured = false;
        if (width > 0 && height > 0 && drawData)
        {
            std::lock_guard<std::mutex> queueLock(gpuBackend->getQueueMutex());
            if (gpuBackend->beginFrame(width, height))
            {
                ImGui_ImplVulkan_RenderDrawData(
                    const_cast<ImDrawData*>(drawData), gpuBackend->getCommandBuffer());
                if (saved && saved->valid())
                    uiComposed = baseCaptured = gpuBackend->snapshotNativeFramePacingBase(width, height);
                else
                    uiComposed = gpuBackend->endFrame();
            }
        }
        lock.lock();
        m_uiSubmitting = false;
        if (pinned && uiSlot < m_slots.size() && m_slots[uiSlot].readers)
            --m_slots[uiSlot].readers;
        if (!m_active || m_stopRequested || backend != m_backend)
        {
            m_uiGeometryUpdating = false;
            m_cv.notify_all();
            return false;
        }

        if (!uiComposed)
            failLocked("UI-rate Vulkan composition failed during native frame pacing");
        if (!saved || !saved->valid() || !baseCaptured)
        {
            // Never associate this new UI generation with the previous saved
            // geometry/base pair. A presenter may resume only after one
            // complete matching snapshot is published.
            m_drawData.reset();
            if (!saved)
                failLocked("failed to retain a complete saved draw-data generation");
            else if (!saved->valid())
                failLocked("saved draw data contains no stable viewport key or has an unsafe post-viewport callback");
            else
                failLocked("failed to snapshot the complete UI-rate Vulkan base image");
        }
        else
        {
            m_drawData = std::move(saved);
            m_drawWidth = width;
            m_drawHeight = height;
        }
        m_uiGeometryUpdating = false;
        m_cv.notify_all();
        return true;
    }

    void beginUiUpdate(VulkanBackend* /*backend*/)
    {
        // The UI tick takes no gate and waits for no presenter here: the
        // presenter may compose the newest renderer image while the UI polls
        // input and builds its widgets. submitDrawData takes the gate.
    }

    bool waitPresentation(uint64_t generation, uint64_t timeoutNanoseconds)
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        return m_cv.wait_for(lock, std::chrono::nanoseconds(timeoutNanoseconds), [this, generation]() {
            return !m_active || m_presentedUiGeneration >= generation;
        });
    }

    void setActiveBackend(VulkanBackend* backend)
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_platformBackend = backend;
    }

private:
    static size_t invalidSlot() { return std::numeric_limits<size_t>::max(); }

    /// The present worker is ovui's and persists across sessions; it parks on
    /// m_sessionReady between them. The render worker belongs to the hooks.
    bool ensureWorkerThreads()
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        if (m_presentThread.joinable())
        {
            return true;
        }

        m_workerShutdownRequested = false;
        try
        {
            m_presentThread = std::thread([this]() { presentWorkerLoop(); });
        }
        catch (...)
        {
            m_workerShutdownRequested = true;
            return false;
        }
        return true;
    }

    bool hasPendingUiRepeatLocked() const
    {
        return m_presentedUiGeneration < m_uiGeneration &&
            m_lastSelected < m_slots.size() &&
            m_slots[m_lastSelected].descriptor &&
            m_slots[m_lastSelected].ownershipGeneration ==
                m_stats.ownershipGeneration;
    }

    bool ensureStablePresentationKeyLocked(IByteImageGpu* gpu, VulkanBackend* backend)
    {
        if (m_stablePresentationGpuState)
            return m_stablePresentationGpu == gpu && m_stablePresentationBackend == backend &&
                m_stablePresentationDescriptor;
        if (!gpu || !backend || !backend->isInitialized())
            return false;

        IByteImageGpu::Handle state = gpu->createState();
        if (!state)
            return false;
        const uint8_t black[] = {0, 0, 0, 255};
        const uint8_t* data = black;
        size_t stride = sizeof(black);
        const IByteImageGpu::UpdateResult result = gpu->updateImage(
            state, &data, &stride, 1, {1, 1}, PixelFormat::eRGBA8_UNORM,
            false, 0, 0, 0);
        if (!result.imGuiReference)
        {
            gpu->destroyState(state);
            return false;
        }
        m_stablePresentationGpu = gpu;
        m_stablePresentationBackend = backend;
        m_stablePresentationGpuState = state;
        m_stablePresentationDescriptor = result.imGuiReference;
        return true;
    }

    void releaseStablePresentationKeyLocked()
    {
        if (!m_stablePresentationGpuState)
            return;
        if (m_stablePresentationBackend &&
            m_stablePresentationBackend->getDevice() != VK_NULL_HANDLE)
        {
            std::lock_guard<std::mutex> queueLock(m_stablePresentationBackend->getQueueMutex());
            vkDeviceWaitIdle(m_stablePresentationBackend->getDevice());
        }
        if (m_stablePresentationGpu)
        {
            m_stablePresentationGpu->destroyState(m_stablePresentationGpuState);
        }
        m_stablePresentationGpu = nullptr;
        m_stablePresentationBackend = nullptr;
        m_stablePresentationGpuState = nullptr;
        m_stablePresentationDescriptor = nullptr;
    }

    void fail(const std::string& message)
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        failLocked(message);
    }

    void fail(const std::string& message, const char* statusReason)
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        failLocked(message);
        m_stats.statusReason = statusReason;
    }

    void failLocked(const std::string& message)
    {
        ++m_stats.errors;
        m_stats.lastError = message;
        m_stats.statusReason = "runtime_error";
        fprintf(stderr, "NativeFramePacing: %s\n", message.c_str());
    }

    bool stopRequested(uint64_t token) const
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        return !m_active || m_token != token || m_stopRequested ||
            m_renderPauseRequested;
    }

    /// The last message of the renderer hooks, or `fallback` when they have none.
    static std::string hookError(const NativeFramePacingHooks* hooks, const char* fallback)
    {
        if (hooks && hooks->lastError)
        {
            const size_t length = hooks->lastError(nullptr, 0);
            if (length)
            {
                std::string message(length, '\0');
                const size_t written = hooks->lastError(message.data(), message.size() + 1);
                message.resize(std::min(written, length));
                if (!message.empty())
                    return message;
            }
        }
        return fallback;
    }

    /// ovui's render worker has parked. Let the hooks give every retained
    /// renderer handle back, so Python owns the renderer alone.
    /// Cancel the outstanding request of the hooks. Safe from each thread.
    void cancelHook(uint64_t token) const
    {
        sendNativeFramePacingCancel(token);
    }

    bool pauseRenderWorkerHook(uint64_t token)
    {
        if (!m_hooks)
            return true;
        if (m_hooks->pauseRenderWorker(token))
            return true;
        fail(hookError(m_hooks, "renderer cleanup release must be retried"));
        return false;
    }

    /// End the session in the hooks. They keep their worker state for the next
    /// session, which is what keeps the per-resize retention down.
    bool closeRendererHook(uint64_t token)
    {
        if (!m_hooks)
            return true;
        if (m_hooks->closeRenderer(token))
            return true;
        fail(hookError(m_hooks, "renderer cleanup release must be retried"));
        return false;
    }

    size_t acquireSlot(uint64_t token)
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_cv.wait(lock, [this, token]() {
            if (!m_active || token != m_token || m_stopRequested ||
                m_renderPauseRequested) return true;
            return std::any_of(m_slots.begin(), m_slots.end(), [](const Slot& slot) {
                return slot.references == 0 && slot.readers == 0;
            });
        });
        if (!m_active || token != m_token || m_stopRequested ||
            m_renderPauseRequested)
            return invalidSlot();
        for (size_t i = 0; i < m_slots.size(); ++i)
        {
            if (m_slots[i].references == 0 && m_slots[i].readers == 0)
            {
                m_slots[i].references = 1; // prospective group ownership
                return i;
            }
        }
        return invalidSlot();
    }

    void releaseSlotReferenceLocked(size_t index)
    {
        if (index < m_slots.size() && m_slots[index].references)
            --m_slots[index].references;
        m_cv.notify_all();
    }

    void releaseGroupLocked(std::shared_ptr<FrameGroup>& group)
    {
        if (!group) return;
        for (size_t slot : group->slots)
            releaseSlotReferenceLocked(slot);
        group.reset();
    }

    void discardGroupLocked(
        std::shared_ptr<FrameGroup>& group, bool replaced = false)
    {
        if (!group) return;
        if (group->next < group->slots.size())
        {
            if (replaced)
                ++m_stats.replacedFrameGroups;
            m_stats.droppedImages += group->slots.size() - group->next;
        }
        releaseGroupLocked(group);
    }

    /// Copy the renderer facts of the hooks into the published statistics.
    /// Without hooks, or outside a session, the renderer-owned counters keep
    /// their last values and the capability sentence says why.
    void refreshRendererInfoLocked()
    {
        if (!m_hooks || !m_active)
        {
            if (m_stats.dlssGeneratedFrameCapability.empty())
                m_stats.dlssGeneratedFrameCapability =
                    "no native frame pacing session has evaluated generated-frame capability";
            return;
        }
        NativeFramePacingRendererInfo info{};
        info.structSize = sizeof(info);
        m_hooks->readRendererInfo(m_token, &info);
        m_stats.rendererVersionMajor = info.versionMajor;
        m_stats.rendererVersionMinor = info.versionMinor;
        m_stats.rendererVersionPatch = info.versionPatch;
        m_stats.liveStepResults = info.liveStepResults;
        m_stats.liveMappings = info.liveMappings;
        m_stats.fetchPolls = info.fetchPolls;
        m_stats.fetchBoundedWaits = info.fetchBoundedWaits;
        m_stats.dlssGeneratedFrameRuntimeSupported = info.generatedFrameRuntimeSupported != 0;
        m_stats.dlssGeneratedFrameX3X4Supported = info.generatedFrameX3X4Supported != 0;
        m_stats.dlssGeneratedFrameGlobalEnableOpinionPresent =
            info.generatedFrameGlobalEnableOpinionPresent != 0;
        m_stats.dlssGeneratedFrameRequestedEnabled = info.generatedFrameRequestedEnabled != 0;
        m_stats.dlssGeneratedFrameRequestedCount = info.generatedFrameRequestedCount;
        m_stats.dlssGeneratedFrameActivationSupported = info.generatedFrameActivationSupported != 0;
        if (!m_stats.dlssGeneratedFrameRuntimeSupported)
        {
            m_stats.dlssGeneratedFrameEffectiveActive = false;
            m_stats.dlssGeneratedFrameEffectiveCount = 0;
        }
        info.generatedFrameCapability[sizeof(info.generatedFrameCapability) - 1] = '\0';
        m_stats.dlssGeneratedFrameCapability = info.generatedFrameCapability;
        // Only ovui knows how many images the last complete group carried.
        if (m_stats.dlssGeneratedFrameRuntimeSupported &&
            m_stats.dlssGeneratedFrameActivationSupported)
            m_stats.dlssGeneratedFrameCapability += "; effective_output_count=" +
                std::to_string(m_stats.dlssGeneratedFrameEffectiveCount);
    }

    PublishResult uploadGroup(uint64_t token,
                     const NativeFramePacingGroup& produced,
                     uint64_t rendererFrameSerial)
    {
        const size_t imageCount = static_cast<size_t>(produced.imageCount);
        const uint32_t width = produced.images[0].width;
        const uint32_t height = produced.images[0].height;
        std::shared_ptr<FrameGroup> group;
        try
        {
            group = std::make_shared<FrameGroup>();
            group->slots.reserve(imageCount);
            group->frameEndTimes.assign(
                produced.frameEndTimes, produced.frameEndTimes + imageCount);
        }
        catch (...)
        {
            fail("failed to allocate bounded Vulkan frame-group metadata");
            return PublishResult::eFailed;
        }
        std::copy(std::begin(produced.cameraWorld), std::end(produced.cameraWorld),
                  group->cameraWorld.begin());
        group->rendererFrameSerial = rendererFrameSerial;
        uint64_t targetOwnershipGeneration = 0;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            targetOwnershipGeneration = m_stats.ownershipGeneration +
                ((width != m_ownershipWidth || height != m_ownershipHeight) ? 1 : 0);
            group->ownershipGeneration = targetOwnershipGeneration;
        }
        // The provider of this session: its upload failure hook applies here.
        std::shared_ptr<ByteImageProvider> provider;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            provider = m_provider;
        }
        for (size_t imageIndex = 0; imageIndex < imageCount; ++imageIndex)
        {
            const NativeFramePacingImage& image = produced.images[imageIndex];
            const size_t slotIndex = acquireSlot(token);
            if (slotIndex == invalidSlot())
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                releaseGroupLocked(group);
                return PublishResult::eFailed;
            }
            group->slots.push_back(slotIndex);
            Slot& slot = m_slots[slotIndex];
            IByteImageGpu::UpdateResult update{};
            const char* hostRefusal = nullptr;
            if (image.gpuResident && !waitForPacedImage(image.readyStream, image.readyEvent))
            {
                // The upload is queued on the legacy default stream. It waits
                // for the image's completion event. Without one it can only
                // follow the legacy default stream, so drop this frame.
                std::lock_guard<std::mutex> lock(m_mutex);
                ++m_stats.gpuPublicationFailures;
                releaseGroupLocked(group);
                return PublishResult::eSkippedRetryable;
            }
            if (image.gpuResident)
            {
                const uint8_t* data = static_cast<const uint8_t*>(image.devicePtr);
                size_t stride = static_cast<size_t>(image.deviceRowStride);
                VulkanByteImageGpu* nativeGpu = dynamic_cast<VulkanByteImageGpu*>(m_gpu);
                bool accepted = false;
                const char* refusal = nullptr;
                // The checked result is the answer. The plain result also
                // holds the OLD texture reference when the upload was
                // refused, so it cannot tell success from a refusal.
                if (!nativeGpu)
                {
                    refusal = "the GPU backend is not the Vulkan backend";
                }
                else if (provider && provider->takeInjectedUploadFailure())
                {
                    refusal = "refused on purpose by injectUploadFailures";
                }
                else
                {
                    const UploadResult checked = nativeGpu->updateImageFromGpuAsyncChecked(
                        slot.gpuState, data, stride, {width, height}, PixelFormat::eRGBA8_UNORM);
                    accepted = checked.status != UploadStatus::eFailed && checked.update.imGuiReference;
                    if (accepted)
                        update = checked.update;
                    else if (checked.status != UploadStatus::eFailed)
                        refusal = "the backend returned no texture";
                    else
                        refusal = checked.cause ? checked.cause : "the backend refused the upload and gave no reason";
                }
                if (accepted)
                {
                    std::lock_guard<std::mutex> lock(m_mutex);
                    ++m_stats.gpuResidentPublications;
                    m_consecutiveGpuRefusals = 0;
                }
                else
                {
                    // The device pair cannot carry this frame (no visible CUDA
                    // device, a mismatched adapter, an unsupported format), or
                    // the upload was refused. Drop only this frame and keep
                    // pacing alive. One refusal can be short-lived, so GPU
                    // publication is latched off after three in a row, and
                    // at once when there is no Vulkan backend. Later frames
                    // then map on the host.
                    std::lock_guard<std::mutex> lock(m_mutex);
                    if (!nativeGpu || ++m_consecutiveGpuRefusals >= kGpuRefusalsBeforeFallback)
                    {
                        if (!m_gpuPublishDisabled)
                            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
                            fprintf(stderr,
                                    "NativeFramePacing: GPU publication refused (%s); later frames use the host copy "
                                    "(fallback)\n",
                                    refusal);
                        m_gpuPublishDisabled = true;
                    }
                    ++m_stats.gpuPublicationFailures;
                    releaseGroupLocked(group);
                    return PublishResult::eSkippedRetryable;
                }
            }
            else
            {
                const uint8_t* data = image.pixels;
                size_t stride = static_cast<size_t>(width) * 4;
                if (provider && provider->takeInjectedUploadFailure())
                {
                    // Test hook: this upload is refused before the backend.
                    hostRefusal = "refused on purpose by injectUploadFailures";
                }
                else if (auto* checkedGpu = dynamic_cast<IByteImageGpuChecked*>(m_gpu))
                {
                    const UploadResult checked = checkedGpu->updateImageChecked(
                        slot.gpuState, &data, &stride, 1, {width, height}, PixelFormat::eRGBA8_UNORM, false, 0, 0, 0);
                    if (checked.status != UploadStatus::eFailed)
                        update = checked.update;
                    else
                        hostRefusal = checked.cause;
                }
                else
                {
                    update = m_gpu->updateImage(slot.gpuState, &data, &stride, 1, {width, height},
                                                PixelFormat::eRGBA8_UNORM, false, 0, 0, 0);
                }
                if (update.imGuiReference)
                {
                    std::lock_guard<std::mutex> lock(m_mutex);
                    ++m_stats.hostFallbackPublications;
                }
            }
            if (!update.imGuiReference)
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                failLocked(std::string("failed to upload an ordered image into the Vulkan slot ring: ") +
                           (hostRefusal ? hostRefusal : "the backend returned no texture"));
                releaseGroupLocked(group);
                return PublishResult::eFailed;
            }
            // A GPU-resident image is never read back, so distinct content
            // cannot be hashed without defeating the point. Use its unique
            // serial instead: content-distinctness degrades to
            // image-distinctness rather than reporting a false match.
            const uint64_t fingerprint = image.gpuResident
                ? ++m_nextContentFingerprint
                : rgbaFingerprint(image.pixels, image.pixelsSize);
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                slot.descriptor = update.imGuiReference;
                slot.width = width;
                slot.height = height;
                slot.imageSerial = ++m_nextImageSerial;
                slot.contentFingerprint = fingerprint;
                slot.ownershipGeneration = targetOwnershipGeneration;
            }
        }

        std::unique_lock<std::mutex> lock(m_mutex);
        if (!m_active || token != m_token || m_stopRequested ||
            m_renderPauseRequested)
        {
            releaseGroupLocked(group);
            return PublishResult::eFailed;
        }
        const size_t realSlot = group->slots.back();
        ++m_slots[realSlot].references; // valid UI-tick fallback while active
        if (m_lastReal != invalidSlot())
            releaseSlotReferenceLocked(m_lastReal);
        m_lastReal = realSlot;
        if (width != m_ownershipWidth || height != m_ownershipHeight)
        {
            m_cv.wait(lock, [this, token]() {
                return !m_active || token != m_token || m_stopRequested ||
                    m_renderPauseRequested ||
                    std::none_of(m_slots.begin(), m_slots.end(), [](const Slot& slot) {
                        return slot.readers != 0;
                    });
            });
            if (!m_active || token != m_token || m_stopRequested ||
                m_renderPauseRequested)
            {
                releaseGroupLocked(group);
                return PublishResult::eFailed;
            }
            ++m_stats.ownershipGeneration;
            if (m_lastSelected < m_slots.size())
                m_slots[m_lastSelected].ownershipGeneration = m_stats.ownershipGeneration;
            m_hasLastPresentedRendererFrameSerial = false;
            m_ownershipWidth = width;
            m_ownershipHeight = height;
            // The replacement generation is complete before publication.
            // Retire any unshown images from the old generation atomically.
            discardGroupLocked(m_currentGroup, true);
        }
        // renderLoop starts a result only while no complete group is pending.
        // Keep the defensive boundary work-conserving as well: a completed
        // result waits for its FIFO slot instead of replacing useful work.
        m_cv.wait(lock, [this, token]() {
            return !m_active || token != m_token || m_stopRequested ||
                m_renderPauseRequested || !m_pendingGroup;
        });
        if (!m_active || token != m_token || m_stopRequested ||
            m_renderPauseRequested)
        {
            releaseGroupLocked(group);
            return PublishResult::eFailed;
        }
        m_pendingGroup = std::move(group);
        ++m_stats.completedFrameGroups;
        switch (imageCount)
        {
            case 1: ++m_stats.completedFrameGroupsSize1; break;
            case 2: ++m_stats.completedFrameGroupsSize2; break;
            case 3: ++m_stats.completedFrameGroupsSize3; break;
            case 4: ++m_stats.completedFrameGroupsSize4; break;
            default: break;
        }
        m_stats.dlssGeneratedFrameEffectiveCount =
            static_cast<int32_t>(imageCount - 1);
        m_stats.dlssGeneratedFrameEffectiveActive = imageCount > 1;
        refreshRendererInfoLocked();
        m_cv.notify_all();
        return PublishResult::ePublished;
    }

    // The host side of the render worker. The worker itself belongs to the
    // renderer hooks; these are the parts of its loop that touch ovui's state,
    // and the worker calls them from its own thread, in the order of #331's
    // renderLoop().

    /// Whether the render worker renders now: always under the continuous
    /// policy; under "on_change" for a changed camera or size, a kick, or a
    /// settle frame left.
    bool renderDueLocked() const
    {
        return !m_renderOnChange || m_renderKick || m_renderSettleLeft > 0 ||
            m_camera.world != m_lastRendered.world || m_camera.width != m_lastRendered.width ||
            m_camera.height != m_lastRendered.height;
    }

    static NativeFramePacingService& self(void* context)
    {
        return *static_cast<NativeFramePacingService*>(context);
    }

    /// Wait for a camera publication while the slot ring can take a group.
    /// False ends the render loop: stop, pause or a new owner.
    bool hostWaitForWork(uint64_t token, double world[16])
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_workerWaiting = true;
        m_cv.wait(lock, [this, token]() {
            return !m_active || token != m_token || m_stopRequested ||
                m_renderPauseRequested ||
                (m_sessionReady && m_camera.serial != 0 && m_presentRate != 0.0 &&
                 !m_pendingGroup && renderDueLocked());
        });
        m_workerWaiting = false;
        if (!m_active || token != m_token || m_stopRequested ||
            m_renderPauseRequested)
        {
            return false;
        }
        // The "on_change" policy: a change (or a kick) renders, then the
        // settle frames, so the renderer's temporal accumulation settles.
        const bool changed = m_renderKick || m_camera.world != m_lastRendered.world ||
            m_camera.width != m_lastRendered.width || m_camera.height != m_lastRendered.height;
        m_renderSettleLeft = changed ? m_renderSettleFrames : m_renderSettleLeft - (m_renderSettleLeft > 0);
        m_renderKick = false;
        m_lastRendered = m_camera;
        m_stats.renderWorkerThread = currentThreadIdentity();
        std::copy(m_camera.world.begin(), m_camera.world.end(), world);
        return true;
    }

    void hostBeginStep(uint64_t token, const double world[16], NativeFramePacingStepDesc* desc)
    {
        (void)token;
        // Prefer the GPU-resident mapping so the displayed image never makes a
        // host round trip. The worker falls back to the host copy whenever the
        // device or tensor shape cannot supply one.
        bool wantGpu = m_gpu && m_gpu->supportsFromGpu();
        std::lock_guard<std::mutex> lock(m_mutex);
        std::copy(world, world + 16, m_stats.authoritativeCameraWorld.begin());
        m_stats.hasAuthoritativeCameraWorld = true;
        // Keep the compatibility statistics field populated with the exact
        // camera used for rendering. Native pacing no longer extrapolates
        // beyond the authoritative UI camera publication.
        m_stats.predictedCameraWorld = m_stats.authoritativeCameraWorld;
        m_stats.hasPredictedCameraWorld = true;
        refreshRendererInfoLocked();
        if (wantGpu)
            wantGpu = !m_gpuPublishDisabled;
        if (desc && desc->structSize >= sizeof(NativeFramePacingStepDesc))
        {
            desc->allowGpuMapping = wantGpu ? 1U : 0U;
            desc->hasLastAcceptedRealEndTime = m_hasLastAcceptedRealEndTime ? 1U : 0U;
            desc->lastAcceptedRealEndTime = m_lastAcceptedRealEndTime;
        }
    }

    uint32_t hostPublishGroup(uint64_t token,
                              const NativeFramePacingStepOutput* output,
                              uint64_t* cudaSyncStream)
    {
        // The upload queues its device-to-device copy and its CUDA-to-Vulkan
        // semaphore signal on the legacy default stream. The worker releases
        // the mapping on that stream, so the renderer keeps its allocation
        // without a CPU hard wait.
        if (cudaSyncStream)
            *cudaSyncStream = kCudaDefaultStream;
        if (!output || output->structSize < sizeof(NativeFramePacingStepOutput))
            return eNativeFramePacingPublishFailed;
        if (output->rendererTimestampOrderViolation)
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            ++m_stats.rendererTimestampOrderViolations;
        }
        const bool extracted = output->groupValid != 0 && output->group.imageCount > 0 &&
            output->group.images && output->group.frameEndTimes;
        if (!extracted)
            return eNativeFramePacingPublished;
        uint64_t rendererFrameSerial = 0;
        {
            // Count completed usable renderer outputs at fetch/map completion,
            // before slot pressure or a Vulkan upload can drop them.
            std::lock_guard<std::mutex> lock(m_mutex);
            // Renderer-time continuity belongs to the validated output
            // sequence, not to the later GPU/host publication transport. A
            // retryable GPU refusal drops this group before switching
            // subsequent groups to host publication, but the renderer still
            // advances its next generated timestamps from this real anchor.
            // Retaining the older published anchor would falsely reject that
            // next well-formed group as uneven and terminate pacing instead of
            // allowing the required host fallback.
            m_lastAcceptedRealEndTime = output->group.frameEndTimes[output->group.imageCount - 1];
            m_hasLastAcceptedRealEndTime = true;
            ++m_stats.realRenderCompletions;
            ++m_stats.rendererCompletions;
            rendererFrameSerial = ++m_nextRendererFrameSerial;
            m_stats.generatedImages += output->group.imageCount - 1;
        }
        if (output->status != eNativeFramePacingGroupReady)
            return eNativeFramePacingPublished;
        OVUI_NESTED_DEVELOPMENT_TIME_SCOPE(
            uploadScope, "NativeFramePacing.vulkan.uploadGroup [ovui debug]");
        switch (uploadGroup(token, output->group, rendererFrameSerial))
        {
            case PublishResult::ePublished: return eNativeFramePacingPublished;
            case PublishResult::eSkippedRetryable: return eNativeFramePacingSkippedRetryable;
            case PublishResult::eFailed: break;
        }
        return eNativeFramePacingPublishFailed;
    }

    /// The end of #331's renderLoop(): a pause parks the worker, anything else
    /// ends its part in the session.
    uint32_t hostRenderLoopEnded(uint64_t token)
    {
        uint32_t end = eNativeFramePacingLoopExited;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            if (m_active && token == m_token)
            {
                if (m_renderPauseRequested && !m_stopRequested)
                {
                    m_renderPaused = true;
                    m_renderExited = false;
                    m_renderFatal = false;
                    m_stats.renderLoopExited = false;
                    m_stats.renderLoopFatal = false;
                    end = eNativeFramePacingLoopParked;
                }
                else
                {
                    m_renderPaused = false;
                    m_renderExited = true;
                    m_renderFatal = !m_stopRequested;
                    m_stats.renderLoopExited = true;
                    m_stats.renderLoopFatal = m_renderFatal;
                    if (m_renderFatal && m_stats.lastError.empty())
                        failLocked("native render loop exited before the renderer borrow was revoked");
                }
            }
        }
        m_cv.notify_all();
        return end;
    }

    /// A parked worker woke: a resume, or a stop of the session.
    bool hostRenderResumed(uint64_t token)
    {
        bool resumed = false;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            if (!m_active || token != m_token || m_stopRequested || m_renderPauseRequested)
            {
                if (m_active && token == m_token && !m_renderExited)
                {
                    m_renderPaused = false;
                    m_renderExited = true;
                    m_renderFatal = false;
                    m_stats.renderLoopExited = true;
                    m_stats.renderLoopFatal = false;
                }
            }
            else
            {
                m_renderPaused = false;
                m_renderExited = false;
                m_renderFatal = false;
                m_stats.renderLoopExited = false;
                m_stats.renderLoopFatal = false;
                resumed = true;
            }
        }
        m_cv.notify_all();
        return resumed;
    }

    static bool hostWaitForWorkThunk(void* context, uint64_t token, double world[16])
    {
        return self(context).hostWaitForWork(token, world);
    }
    static bool hostStopRequestedThunk(void* context, uint64_t token)
    {
        return self(context).stopRequested(token);
    }
    static void hostBeginStepThunk(void* context, uint64_t token, const double world[16],
                                   NativeFramePacingStepDesc* desc)
    {
        self(context).hostBeginStep(token, world, desc);
    }
    static uint32_t hostPublishGroupThunk(void* context, uint64_t token,
                                          const NativeFramePacingStepOutput* output,
                                          uint64_t* cudaSyncStream)
    {
        return self(context).hostPublishGroup(token, output, cudaSyncStream);
    }
    static void hostReportErrorThunk(void* context, const char* message)
    {
        self(context).fail(message && message[0] ? message : "the render worker failed");
    }
    static uint32_t hostRenderLoopEndedThunk(void* context, uint64_t token)
    {
        return self(context).hostRenderLoopEnded(token);
    }
    static bool hostRenderResumedThunk(void* context, uint64_t token)
    {
        return self(context).hostRenderResumed(token);
    }

    void presentLoop(uint64_t token)
    {
        while (true)
        {
            std::shared_ptr<SavedDrawData> drawData;
            size_t slotIndex = invalidSlot();
            int width = 0;
            int height = 0;
            uint64_t generation = 0;
            double rate = 0.0;
            bool groupCandidate = false;
            bool uiRepeatCandidate = false;
            size_t candidateImageIndex = 0;
            std::array<double, 16> candidateCameraWorld{};
            bool candidateGenerated = false;
            uint64_t candidateRendererFrameSerial = 0;
            double candidateFrameEndTime = 0.0;
            uint64_t candidateOwnershipGeneration = 0;
            double candidateRendererInterval = 0.0;
            Clock::time_point candidateDeadline{};
            bool hasCandidateDeadline = false;
            {
                std::unique_lock<std::mutex> lock(m_mutex);
                m_cv.wait(lock, [this, token]() {
                    return !m_active || token != m_token || m_stopRequested ||
                        (!m_uiGeometryUpdating && m_presentRate != 0.0 && m_drawData &&
                         (m_pendingGroup ||
                          (m_currentGroup &&
                           m_currentGroup->next < m_currentGroup->slots.size()) ||
                          hasPendingUiRepeatLocked()));
                });
                if (!m_active || token != m_token || m_stopRequested)
                    break;
                rate = m_presentRate;
                if (rate == 0.0)
                    continue;
                if (!m_currentGroup || m_currentGroup->next >= m_currentGroup->slots.size())
                {
                    releaseGroupLocked(m_currentGroup);
                    if (m_pendingGroup)
                    {
                        m_currentGroup = std::move(m_pendingGroup);
                        // Moving the complete group into the consumer's FIFO
                        // position releases one producer slot immediately.
                        // Rendering the next frame can overlap presentation of
                        // this one without replacing either result.
                        m_cv.notify_all();
                    }
                }
                if (m_currentGroup && m_currentGroup->next < m_currentGroup->slots.size())
                {
                    candidateImageIndex = m_currentGroup->next;
                    slotIndex = m_currentGroup->slots[candidateImageIndex];
                    groupCandidate = true;
                    candidateRendererFrameSerial =
                        m_currentGroup->rendererFrameSerial;
                    candidateCameraWorld = m_currentGroup->cameraWorld;
                    candidateFrameEndTime =
                        m_currentGroup->frameEndTimes[candidateImageIndex];
                    // The current public ordered-output contract exposes no
                    // generated-subframe camera or pick metadata. Preserve
                    // presentation, but surface the exact boundary so Python
                    // picking fails closed instead of pretending the
                    // real-frame endpoint camera describes a generated image.
                    candidateGenerated =
                        candidateImageIndex + 1 < m_currentGroup->slots.size();
                }
                if (groupCandidate &&
                    (slotIndex == invalidSlot() || !m_slots[slotIndex].descriptor))
                    continue;
                if (groupCandidate &&
                    m_slots[slotIndex].ownershipGeneration != m_stats.ownershipGeneration)
                {
                    ++m_stats.staleGenerationRejections;
                    if (m_lastSelected == slotIndex)
                    {
                        releaseSlotReferenceLocked(m_lastSelected);
                        m_lastSelected = invalidSlot();
                    }
                    discardGroupLocked(m_currentGroup, true);
                    continue;
                }
                candidateOwnershipGeneration = m_stats.ownershipGeneration;

                // Renderer time is the cadence authority.  The configured
                // present rate only enables the native path; a lower positive
                // value is promoted so it can never cap a complete produced
                // group below its adjacent renderer-timestamp rate.
                if (groupCandidate && m_hasLastPresentedFrameEndTime)
                {
                    candidateRendererInterval =
                        candidateFrameEndTime - m_lastPresentedFrameEndTime;
                    if (!(candidateRendererInterval > 0.0) ||
                        !std::isfinite(candidateRendererInterval))
                    {
                        ++m_stats.rendererTimestampOrderViolations;
                        failLocked(
                            "next viewport image has a non-increasing renderer timestamp");
                        discardGroupLocked(m_currentGroup);
                        continue;
                    }
                    if (m_presentRate > 0.0)
                        m_presentRate = std::max(
                            m_presentRate, 1.0 / candidateRendererInterval);
                    if (m_hasLastScheduledPresentationTime)
                    {
                        candidateDeadline = m_lastScheduledPresentationTime +
                            std::chrono::duration_cast<Clock::duration>(
                                std::chrono::duration<double>(
                                    candidateRendererInterval));
                        hasCandidateDeadline = true;
                    }
                    else if (m_hasLastSuccessfulPresentTime)
                    {
                        candidateDeadline = m_lastSuccessfulPresentTime +
                            std::chrono::duration_cast<Clock::duration>(
                                std::chrono::duration<double>(
                                    candidateRendererInterval));
                        hasCandidateDeadline = true;
                    }
                }
                if (hasCandidateDeadline && Clock::now() < candidateDeadline)
                {
                    if (hasPendingUiRepeatLocked())
                    {
                        slotIndex = m_lastSelected;
                        groupCandidate = false;
                        uiRepeatCandidate = true;
                    }
                    else
                    {
                        const bool interrupted = m_cv.wait_until(
                            lock, candidateDeadline, [this, token, rate]() {
                                return !m_active || token != m_token ||
                                    m_stopRequested || m_presentRate == 0.0 ||
                                    (rate > 0.0 && m_presentRate < rate) ||
                                    hasPendingUiRepeatLocked();
                            });
                        if (interrupted)
                        {
                            if (!m_active || token != m_token || m_stopRequested)
                                break;
                            continue;
                        }
                    }
                }
                else if (!groupCandidate && hasPendingUiRepeatLocked())
                {
                    slotIndex = m_lastSelected;
                    uiRepeatCandidate = true;
                }
                if ((!groupCandidate && !uiRepeatCandidate) ||
                    slotIndex == invalidSlot() || !m_slots[slotIndex].descriptor)
                    continue;
                if (m_slots[slotIndex].ownershipGeneration != m_stats.ownershipGeneration)
                {
                    ++m_stats.staleGenerationRejections;
                    if (uiRepeatCandidate && m_lastSelected == slotIndex)
                    {
                        releaseSlotReferenceLocked(m_lastSelected);
                        m_lastSelected = invalidSlot();
                    }
                    continue;
                }
                if (m_uiGeometryUpdating)
                {
                    m_cv.wait(lock, [this, token]() {
                        return !m_active || token != m_token || m_stopRequested ||
                            !m_uiGeometryUpdating;
                    });
                    if (!m_active || token != m_token || m_stopRequested)
                        break;
                }
                ++m_slots[slotIndex].readers;
                m_presenterComposing = true;
                drawData = m_drawData;
                width = m_drawWidth;
                height = m_drawHeight;
                generation = m_uiGeneration;
            }
            OVUI_DEVELOPMENT_TIME_SCOPE(
                nativePresentFrameScope, "NativeFramePacing.presentFrame [ovui debug]");
            const void* descriptor = nullptr;
            uint64_t imageSerial = 0;
            uint64_t contentFingerprint = 0;
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                if (slotIndex < m_slots.size())
                {
                    descriptor = m_slots[slotIndex].descriptor;
                    imageSerial = m_slots[slotIndex].imageSerial;
                    contentFingerprint = m_slots[slotIndex].contentFingerprint;
                    if (m_slots[slotIndex].ownershipGeneration != m_stats.ownershipGeneration)
                    {
                        descriptor = nullptr;
                        ++m_stats.staleGenerationRejections;
                    }
                }
            }
            bool composed = false;
            VulkanBackend::WindowPresentResult preparedWindow =
                VulkanBackend::WindowPresentResult::eNotWindowed;
            uint32_t swapchainImage = 0;
            bool attempted = descriptor && drawData && width > 0 && height > 0 &&
                m_backend && m_backend->isInitialized();
            // A frame fence still busy with the UI's composition, or no window
            // image yet: retry after a short sleep instead of spinning on the
            // queue lock, which the render thread's uploads need.
            bool retryLater = false;
            if (attempted)
            {
                OVUI_NESTED_DEVELOPMENT_TIME_SCOPE(
                    composeScope, "NativeFramePacing.vulkan.compose [ovui debug]");
                std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
                bool frameDeferred = false;
                // The UI submits its composition and base copy without waiting
                // for them: give that GPU work up to 2 ms before deferring,
                // instead of retrying against a busy frame fence.
                if (m_backend->beginFrame(width, height, true, false, 2'000'000))
                {
                    ImGui_ImplVulkan_RenderDrawData(
                        drawData->selectViewportImage(const_cast<void*>(descriptor)),
                        m_backend->getCommandBuffer());
                    composed = m_backend->restoreNativeFramePacingBase(
                        drawData->copyRegions(), width, height);
                    if (composed)
                    {
                        preparedWindow = m_backend->prepareWindowFrame(
                            width, height, &swapchainImage);
                        if (preparedWindow == VulkanBackend::WindowPresentResult::eFailed)
                            composed = false;
                        else if (preparedWindow == VulkanBackend::WindowPresentResult::eDeferred)
                            // No WSI image is ready yet. Retain this candidate
                            // for retry instead of terminating the session.
                            attempted = false, retryLater = true;
                    }
                }
                else
                {
                    frameDeferred = m_backend->isInitialized();
                }
                if (frameDeferred)
                    attempted = false, retryLater = true;
            }
            // Composition is complete and its slot sampling is submitted. End
            // the UI exclusion here so the display hand-off below cannot pace
            // the main thread. The slot reader stays held until the frame is
            // retired, so no upload may recycle it yet.
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                m_presenterComposing = false;
                m_cv.notify_all();
            }
            // FIFO presentation may follow the compositor/monitor cadence.
            // Enqueue it only after releasing the graphics queue mutex so the
            // render thread can continue submitting slot uploads independently.
            bool presentSubmitCalled = false;
            bool presentSubmitSucceeded = false;
            uint64_t presentSubmitNanoseconds = 0;
            Clock::time_point presentStartedAt{};
            Clock::time_point presentCompletedAt{};
            if (composed && preparedWindow == VulkanBackend::WindowPresentResult::ePrepared)
            {
                presentSubmitCalled = true;
                presentStartedAt = Clock::now();
                VulkanBackend::WindowPresentResult presentResult =
                    VulkanBackend::WindowPresentResult::eFailed;
                {
                    OVUI_NESTED_DEVELOPMENT_TIME_SCOPE(
                        presentScope, "NativeFramePacing.vulkan.present [ovui debug]");
                    presentResult = m_backend->presentWindowFrame(swapchainImage);
                }
                presentSubmitNanoseconds = static_cast<uint64_t>(
                    std::chrono::duration_cast<std::chrono::nanoseconds>(
                        Clock::now() - presentStartedAt).count());
                presentCompletedAt = Clock::now();
                presentSubmitSucceeded =
                    presentResult == VulkanBackend::WindowPresentResult::ePresented;
                if (!presentSubmitSucceeded)
                {
                    composed = false;
                    if (presentResult == VulkanBackend::WindowPresentResult::eDeferred)
                        attempted = false;
                }
            }
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                if (presentSubmitCalled)
                {
                    ++m_stats.presentSubmitCalls;
                    if (presentSubmitSucceeded)
                    {
                        ++m_stats.presentSubmitSuccesses;
                        if (m_hasLastSuccessfulPresentTime)
                        {
                            const uint64_t intervalNanoseconds = static_cast<uint64_t>(
                                std::chrono::duration_cast<std::chrono::nanoseconds>(
                                    presentCompletedAt - m_lastSuccessfulPresentTime).count());
                            ++m_stats.successfulPresentIntervals;
                            m_stats.successfulPresentIntervalTotalNanoseconds += intervalNanoseconds;
                            m_stats.successfulPresentIntervalMaxNanoseconds = std::max(
                                m_stats.successfulPresentIntervalMaxNanoseconds,
                                intervalNanoseconds);
                            if (intervalNanoseconds > 40'000'000)
                                ++m_stats.successfulPresentIntervalsOver40ms;
                            if (intervalNanoseconds > 100'000'000)
                                ++m_stats.successfulPresentIntervalsOver100ms;
                            if (intervalNanoseconds > 1'000'000'000)
                                ++m_stats.successfulPresentIntervalsOver1s;
                        }
                        m_lastSuccessfulPresentTime = presentCompletedAt;
                        m_hasLastSuccessfulPresentTime = true;
                    }
                    m_stats.presentSubmitTotalNanoseconds += presentSubmitNanoseconds;
                    m_stats.presentSubmitMaxNanoseconds = std::max(
                        m_stats.presentSubmitMaxNanoseconds, presentSubmitNanoseconds);
                }
                // A composed offscreen frame is not a delivered window frame
                // when swapchain preparation deferred before vkQueuePresentKHR.
                if (composed && preparedWindow != VulkanBackend::WindowPresentResult::eNotWindowed &&
                    !presentSubmitSucceeded)
                    composed = false;
                if (slotIndex < m_slots.size() && m_slots[slotIndex].readers)
                    --m_slots[slotIndex].readers;
                if (composed && groupCandidate && m_currentGroup &&
                    m_currentGroup->next == candidateImageIndex &&
                    candidateImageIndex < m_currentGroup->slots.size() &&
                    m_currentGroup->slots[candidateImageIndex] == slotIndex)
                {
                    // Commit selection only after a successful presentation.
                    // A transient swapchain deferral retries this same newest
                    // complete candidate without releasing producer credit.
                    ++m_currentGroup->next;
                    ++m_slots[slotIndex].references; // new last-selected ownership
                    if (m_lastSelected != invalidSlot())
                        releaseSlotReferenceLocked(m_lastSelected);
                    m_lastSelected = slotIndex;
                    m_selectedCameraWorld = candidateCameraWorld;
                    m_hasSelectedCameraWorld = true;
                    m_selectedImageGenerated = candidateGenerated;
                    if (candidateGenerated)
                        ++m_stats.presentedGeneratedImages;
                    if (!candidateGenerated)
                    {
                        ++m_stats.selectedRendererFrames;
                        m_stats.lastSelectedRendererFrameSerial =
                            candidateRendererFrameSerial;
                    }
                }
                if (composed && imageSerial && imageSerial != m_lastPresentedImageSerial)
                {
                    ++m_stats.selectedViewportImageChanges;
                    m_lastPresentedImageSerial = imageSerial;
                    if (m_hasSelectedCameraWorld)
                    {
                        m_stats.selectedCameraWorld = m_selectedCameraWorld;
                        m_stats.hasSelectedCameraWorld = true;
                        m_stats.selectedImageIsGenerated = m_selectedImageGenerated;
                    }
                }
                else if (composed)
                {
                    ++m_stats.repeatedPresents;
                }
                // A render pause during the unlocked present begins a new
                // ownership generation and clears the renderer-time anchors;
                // the old-generation image just presented must not re-anchor
                // them, or every frame of the resumed (possibly rebased)
                // renderer clock is rejected as non-increasing.
                const bool sameOwnership =
                    candidateOwnershipGeneration == m_stats.ownershipGeneration;
                if (composed && groupCandidate && !candidateGenerated && sameOwnership)
                {
                    ++m_stats.presentedRendererFrames;
                    if (m_hasLastPresentedRendererFrameSerial &&
                        candidateRendererFrameSerial <=
                        m_lastPresentedRendererFrameSerial)
                        ++m_stats.rendererFrameOrderViolations;
                    m_lastPresentedRendererFrameSerial = candidateRendererFrameSerial;
                    m_hasLastPresentedRendererFrameSerial = true;
                    m_stats.lastPresentedRendererFrameSerial =
                        candidateRendererFrameSerial;
                }
                if (composed && groupCandidate && sameOwnership)
                {
                    m_lastScheduledPresentationTime = hasCandidateDeadline
                        ? candidateDeadline
                        : (presentCompletedAt != Clock::time_point{}
                            ? presentCompletedAt : Clock::now());
                    m_hasLastScheduledPresentationTime = true;
                    if (m_hasLastPresentedFrameEndTime)
                    {
                        const double interval = candidateFrameEndTime -
                            m_lastPresentedFrameEndTime;
                        const uint64_t intervalNanoseconds =
                            static_cast<uint64_t>(std::llround(interval * 1e9));
                        ++m_stats.rendererTimestampIntervals;
                        m_stats.rendererTimestampIntervalTotalNanoseconds +=
                            intervalNanoseconds;
                        m_stats.rendererTimestampIntervalMaxNanoseconds =
                            std::max(
                                m_stats.rendererTimestampIntervalMaxNanoseconds,
                                intervalNanoseconds);
                    }
                    if (hasCandidateDeadline &&
                        presentStartedAt != Clock::time_point{} &&
                        presentStartedAt > candidateDeadline +
                            std::chrono::milliseconds(1))
                        ++m_stats.presentationDeadlineMisses;
                    m_lastPresentedFrameEndTime = candidateFrameEndTime;
                    m_hasLastPresentedFrameEndTime = true;
                    m_stats.lastPresentedFrameEndTime = candidateFrameEndTime;
                }
                // Generated subframes are presentation activity, not a new
                // rendered viewport update.
                if (composed && !m_selectedImageGenerated &&
                    (!m_hasLastPresentedContentFingerprint ||
                     contentFingerprint != m_lastPresentedContentFingerprint))
                {
                    ++m_stats.selectedViewportContentChanges;
                    ++m_stats.selectedContentChanges;
                    m_lastPresentedContentFingerprint = contentFingerprint;
                    m_hasLastPresentedContentFingerprint = true;
                }
                if (composed)
                {
                    ++m_stats.totalPresents;
                    m_presentedUiGeneration = std::max(m_presentedUiGeneration, generation);
                }
                else if (attempted)
                {
                    failLocked("native Vulkan saved-geometry composition failed");
                }
                m_cv.notify_all();
            }
            if (retryLater)
                std::this_thread::sleep_for(std::chrono::microseconds(250));
        }
    }

    void presentWorkerLoop()
    {
        uint64_t completedToken = 0;
        while (true)
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait(lock, [this, completedToken]() {
                return m_workerShutdownRequested ||
                    (m_active && m_sessionReady && m_token != completedToken);
            });
            if (m_workerShutdownRequested)
            {
                break;
            }

            const uint64_t token = m_token;
            m_stats.presentWorkerThread = currentThreadIdentity();
            lock.unlock();
            presentLoop(token);
            lock.lock();
            if (m_active && token == m_token)
            {
                m_presentExited = true;
            }
            completedToken = token;
            m_cv.notify_all();
        }
    }

    mutable std::mutex m_mutex;
    std::condition_variable m_cv;
    bool m_active = false;
    bool m_sessionReady = false;
    bool m_workerShutdownRequested = false;
    bool m_stopRequested = false;
    bool m_renderPauseRequested = false;
    bool m_renderPaused = false;
    bool m_presenterComposing = false;
    bool m_uiSubmitting = false;
    bool m_stopCallActive = false;
    uint64_t m_token = 0;
    uint64_t m_nextToken = 0;
    uint64_t m_nextMetricsEpoch = 0;
    double m_presentRate = 0.0;
    NativeFramePacingStats m_stats;
    VulkanBackend* m_platformBackend = nullptr;
    VulkanBackend* m_backend = nullptr;
    IByteImageGpu* m_gpu = nullptr;
    std::shared_ptr<ByteImageProvider> m_provider;
    void* m_presentationKey = nullptr;
    bool m_providerKeyInstalled = false;
    IByteImageGpu* m_stablePresentationGpu = nullptr;
    VulkanBackend* m_stablePresentationBackend = nullptr;
    IByteImageGpu::Handle m_stablePresentationGpuState = nullptr;
    void* m_stablePresentationDescriptor = nullptr;
    uint32_t m_providerWidth = 0;
    uint32_t m_providerHeight = 0;
    uint32_t m_ownershipWidth = 0;
    uint32_t m_ownershipHeight = 0;
    CameraPublication m_camera;
    // The render policy: continuous, or "on_change" (setRenderPolicy).
    bool m_renderOnChange = false;
    bool m_renderKick = true;
    uint32_t m_renderSettleFrames = 8;
    uint32_t m_renderSettleLeft = 0;
    // The render worker waits in hostWaitForWork (see NativeFramePacingStats::renderIdle).
    bool m_workerWaiting = false;
    CameraPublication m_lastRendered;
    std::thread m_presentThread;
    std::vector<Slot> m_slots;
    std::shared_ptr<FrameGroup> m_currentGroup;
    std::shared_ptr<FrameGroup> m_pendingGroup;
    size_t m_lastSelected = invalidSlot();
    size_t m_lastReal = invalidSlot();
    uint64_t m_nextImageSerial = 0;
    uint64_t m_nextContentFingerprint = 0;
    uint64_t m_nextRendererFrameSerial = 0;
    bool m_gpuPublishDisabled = false;  // latched by a real upload refusal
    uint32_t m_consecutiveGpuRefusals = 0;
    static constexpr uint32_t kGpuRefusalsBeforeFallback = 3;
    uint64_t m_lastPresentedImageSerial = 0;
    uint64_t m_lastPresentedRendererFrameSerial = 0;
    bool m_hasLastPresentedRendererFrameSerial = false;
    Clock::time_point m_lastSuccessfulPresentTime{};
    bool m_hasLastSuccessfulPresentTime = false;
    Clock::time_point m_lastScheduledPresentationTime{};
    bool m_hasLastScheduledPresentationTime = false;
    double m_lastPresentedFrameEndTime = 0.0;
    bool m_hasLastPresentedFrameEndTime = false;
    double m_lastAcceptedRealEndTime = 0.0;
    bool m_hasLastAcceptedRealEndTime = false;
    uint64_t m_lastPresentedContentFingerprint = 0;
    bool m_hasLastPresentedContentFingerprint = false;
    std::shared_ptr<SavedDrawData> m_drawData;
    int m_drawWidth = 0;
    int m_drawHeight = 0;
    uint64_t m_uiGeneration = 0;
    uint64_t m_presentedUiGeneration = 0;
    bool m_uiGeometryUpdating = false;
    bool m_renderExited = false;
    bool m_presentExited = false;
    bool m_renderFatal = false;
    bool m_hasSelectedCameraWorld = false;
    bool m_selectedImageGenerated = false;
    std::array<double, 16> m_selectedCameraWorld{};
    /// The renderer half of the session. Null without a renderer package.
    const NativeFramePacingHooks* m_hooks = nullptr;
    bool m_missingHooksReported = false;
    /// What the render worker of the hooks calls back into.
    const NativeFramePacingHost m_host{
        sizeof(NativeFramePacingHost),
        this,
        hostWaitForWorkThunk,
        hostStopRequestedThunk,
        hostBeginStepThunk,
        hostPublishGroupThunk,
        hostReportErrorThunk,
        hostRenderLoopEndedThunk,
        hostRenderResumedThunk,
    };
};

NativeFramePacingService& service()
{
    static NativeFramePacingService value;
    return value;
}

} // namespace

bool setNativeFramePacingPresentRate(double framesPerSecond)
{
    return service().setPresentRate(framesPerSecond);
}

double getNativeFramePacingPresentRate()
{
    return service().presentRate();
}

uint64_t startNativeFramePacing(uintptr_t renderer,
                                const char* libraryPath,
                                uint32_t renderVarStride,
                                uint32_t renderVarNameOffset,
                                uint32_t renderVarHandleOffset,
                                std::shared_ptr<ByteImageProvider> provider,
                                const char* renderProductPath,
                                const char* cameraPath,
                                uint32_t width,
                                uint32_t height)
{
    return service().start(
        renderer, libraryPath, renderVarStride, renderVarNameOffset,
        renderVarHandleOffset, std::move(provider), renderProductPath, cameraPath,
        width, height);
}

bool publishNativeFramePacingState(uint64_t token,
                                   uint32_t width,
                                   uint32_t height,
                                   const std::array<double, 16>& worldMatrix,
                                   const std::array<double, 3>& linearVelocity,
                                   double timestampSeconds)
{
    return service().publish(token, width, height, worldMatrix, linearVelocity, timestampSeconds);
}

bool pauseNativeFramePacingRender(uint64_t token)
{
    return service().pauseRender(token);
}

bool resumeNativeFramePacingRender(uint64_t token, bool render)
{
    return service().resumeRender(token, render);
}

bool setNativeFramePacingRenderPolicy(uint64_t token, const char* policy, uint32_t settleFrames)
{
    if (!policy || (std::strcmp(policy, "continuous") != 0 && std::strcmp(policy, "on_change") != 0))
        return false;
    return service().setRenderPolicy(token, std::strcmp(policy, "on_change") == 0, settleFrames);
}

bool requestNativeFramePacingRender(uint64_t token)
{
    return service().requestRender(token);
}

bool stopNativeFramePacing(uint64_t token)
{
    return service().stop(token);
}

NativeFramePacingStats getNativeFramePacingStats()
{
    return service().stats();
}

void resetFrameThroughputMetrics()
{
    service().resetThroughputMetrics();
}

void recordSynchronousRendererCompletion()
{
    service().recordSynchronousRendererCompletion();
}

void recordSynchronousContentSelection()
{
    service().recordSynchronousContentSelection();
}

bool submitNativeFramePacingDrawData(VulkanBackend* backend,
                                     const ImDrawData* drawData,
                                     int width,
                                     int height,
                                     uint64_t* outGeneration,
                                     bool forceFresh)
{
    service().setActiveBackend(backend);
    return service().submitDrawData(backend, drawData, width, height, outGeneration, forceFresh);
}

void beginNativeFramePacingUiUpdate(VulkanBackend* backend)
{
    service().beginUiUpdate(backend);
}

bool waitNativeFramePacingPresentation(uint64_t uiGeneration, uint64_t timeoutNanoseconds)
{
    return service().waitPresentation(uiGeneration, timeoutNanoseconds);
}

void registerNativeFramePacingBackend(VulkanBackend* backend)
{
    service().setActiveBackend(backend);
}

void shutdownNativeFramePacing()
{
    service().shutdown();
}

} // namespace standalone
} // namespace ui
} // namespace omni
