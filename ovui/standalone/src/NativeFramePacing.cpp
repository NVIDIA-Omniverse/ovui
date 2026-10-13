/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#if defined(_WIN32) && !defined(NOMINMAX)
#  define NOMINMAX
#endif

#include "NativeFramePacing.h"

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

#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
#  include <ovrtx/ovrtx.h>
#  if defined(_WIN32)
#    include <windows.h>
#  else
#    include <dlfcn.h>
#  endif
#endif

namespace omni {
namespace ui {
namespace standalone {

namespace {

using Clock = std::chrono::steady_clock;
constexpr uint64_t kBoundedWaitNanoseconds = 5'000'000;
constexpr size_t kSlotCount = 12; // three complete maximum-size ordered groups
constexpr size_t kMaxOrderedFrames = 4;
constexpr uint64_t kMaxFramePixels = 16'777'216; // bounded 4K-class slot-ring allocation
constexpr double kPredictionFullResponseSeconds = 0.100;
constexpr double kPredictionDecaySeconds = 0.150;
constexpr char kDlssgSupportedSetting[] =
    "/rtx-transient/hashed/995bcbda752ace40e33a4d131067d270";
constexpr char kDlssgX3X4SupportedSetting[] =
    "/rtx-transient/dlssg/x3x4supported";
constexpr char kDlssgEnabledSetting[] = "/rtx-transient/dlssg/enabled";
constexpr char kDlssgRequestedCountSetting[] =
    "/rtx-transient/hashed/410cea6f0e51aa5e9f232895a3a4f74a";
constexpr char kDlssgActiveCountSetting[] =
    "/rtx-transient/hashed/b0438cc64f2f9de5ac1b749deedffd9a";

// Must share an epoch with Python's `time.perf_counter`, which produces
// `CameraPublication::timestamp` (see `writeCamera`).
double monotonicSeconds()
{
    return std::chrono::duration<double>(Clock::now().time_since_epoch()).count();
}

uint64_t rgbaFingerprint(const std::vector<uint8_t>& pixels)
{
    // FNV-1a over the bounded mapped RGBA result. Hashing happens once while
    // the CPU copy is already hot and proves pixel-content change separately
    // from slot/group identity.
    uint64_t hash = 1469598103934665603ull;
    for (uint8_t value : pixels)
    {
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
    std::array<double, 3> velocity{};
    double timestamp = 0.0;
    double maximumPredictionDistance = 0.0;
    uint64_t serial = 0;
};

/// One extracted LdrColor image, either GPU-resident or copied to host.
///
/// A GPU-resident entry keeps its ovrtx mapping live so the device pointer
/// stays valid until the Vulkan upload has consumed it. The upload path
/// queues its device-to-device copy and CUDA-to-Vulkan semaphore signal on
/// the legacy default stream. releaseMappings() supplies that stream to
/// ovrtx unmap, so the source allocation stays live without a CPU hard wait.
/// Every mapping is released exactly once through releaseMappings(), on
/// success, per-image failure, revocation, resize and shutdown alike.
/// ovrtx stream ids: 0 = no synchronisation, 1 = the legacy default
/// CUDA stream. The GPU upload consumes on the default stream.
constexpr uintptr_t kCudaDefaultStream = 1;

/// Outcome of publishing one completed renderer result.
enum class PublishResult
{
    ePublished,        ///< the group reached the slot ring
    eSkippedRetryable, ///< this frame was dropped; the session stays alive
    eFailed,           ///< unrecoverable; the session must stop
};

struct MappedImage
{
    std::vector<uint8_t> pixels;                    // host copy (fallback)
    const void* devicePtr = nullptr;                // CUDA device pointer
    size_t deviceRowStride = 0;
    uint64_t mapHandle = 0;   // ovrtx_map_handle_t is uint64_t
    bool mapped = false;                            // mapping still live
    bool gpuResident = false;
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

#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)

template <typename T>
T loadSymbol(void* library, const char* name)
{
#  if defined(_WIN32)
    return reinterpret_cast<T>(GetProcAddress(static_cast<HMODULE>(library), name));
#  else
    return reinterpret_cast<T>(dlsym(library, name));
#  endif
}

class OvrtxApi
{
public:
    enum SettingType : uint32_t
    {
        eSettingMissing = 0,
        eSettingBool = 1,
        eSettingInt = 2,
    };

    struct ReadSettingsV1
    {
        uint32_t abiVersion;
        uint32_t structSize;
        ovrtx_result_t (*getType)(ovx_string_t, SettingType*);
        ovrtx_result_t (*getBool)(ovx_string_t, bool*);
        ovrtx_result_t (*getInt)(ovx_string_t, int64_t*);
        ovrtx_result_t (*getFloat)(ovx_string_t, double*);
        ovrtx_result_t (*getString)(ovx_string_t, char*, size_t, size_t*);
    };

    using GetVersion = void (*)(uint32_t*, uint32_t*, uint32_t*);
    using QueryExtension = ovrtx_result_t (*)(const char*, const void**);
    using WriteAttribute = ovrtx_enqueue_result_t (*)(ovrtx_renderer_t*, const ovrtx_binding_desc_or_handle_t*,
                                                       const ovrtx_input_buffer_t*, ovrtx_data_access_t);
    using Step = ovrtx_enqueue_result_t (*)(ovrtx_renderer_t*, ovrtx_render_product_set_t, double,
                                             ovrtx_step_result_handle_t*);
    using WaitOp = ovrtx_result_t (*)(ovrtx_renderer_t*, ovrtx_op_id_t, ovrtx_timeout_t,
                                       ovrtx_op_wait_result_t*);
    using Fetch = ovrtx_result_t (*)(ovrtx_renderer_t*, ovrtx_step_result_handle_t, ovrtx_timeout_t,
                                      ovrtx_render_product_set_outputs_t*);
    using Map = ovrtx_result_t (*)(ovrtx_renderer_t*, ovrtx_render_var_output_handle_t,
                                    const ovrtx_map_output_description_t*, ovrtx_timeout_t,
                                    ovrtx_render_var_output_t*);
    using Unmap = ovrtx_result_t (*)(ovrtx_renderer_t*, ovrtx_render_var_output_map_handle_t, ovrtx_cuda_sync_t);
    using Destroy = ovrtx_result_t (*)(ovrtx_renderer_t*, ovrtx_step_result_handle_t);
    using GetLastError = ovx_string_t (*)();

    ~OvrtxApi() { close(); }

    bool open(const char* path, std::string& error)
    {
        if (!path || !path[0])
        {
            error = "ovrtx library path is empty";
            return false;
        }
#  if defined(_WIN32)
        m_library = static_cast<void*>(LoadLibraryA(path));
#  else
        m_library = dlopen(path, RTLD_NOW | RTLD_LOCAL);
#  endif
        if (!m_library)
        {
            error = "could not open the ovrtx library";
            return false;
        }
        getVersion = loadSymbol<GetVersion>(m_library, "ovrtx_get_version");
        queryExtension = loadSymbol<QueryExtension>(m_library, "ovrtx_query_extension");
        writeAttribute = loadSymbol<WriteAttribute>(m_library, "ovrtx_write_attribute");
        step = loadSymbol<Step>(m_library, "ovrtx_step");
        waitOp = loadSymbol<WaitOp>(m_library, "ovrtx_wait_op");
        fetch = loadSymbol<Fetch>(m_library, "ovrtx_fetch_results");
        map = loadSymbol<Map>(m_library, "ovrtx_map_render_var_output");
        unmap = loadSymbol<Unmap>(m_library, "ovrtx_unmap_render_var_output");
        destroy = loadSymbol<Destroy>(m_library, "ovrtx_destroy_results");
        getLastError = loadSymbol<GetLastError>(m_library, "ovrtx_get_last_error");
        if (!writeAttribute || !step || !fetch || !map || !unmap || !destroy)
        {
            error = "ovrtx library is missing a required native-pacing C ABI symbol";
            close();
            return false;
        }
        if (getVersion)
            getVersion(&major, &minor, &patch);
        if (queryExtension)
        {
            const void* applyTable = nullptr;
            const ovrtx_result_t applyResult =
                queryExtension("ovrtx.settings.apply_settings", &applyTable);
            applySettingsAvailable =
                applyResult.status == OVRTX_API_SUCCESS && applyTable != nullptr;

            const void* readTable = nullptr;
            const ovrtx_result_t readResult =
                queryExtension("ovrtx.settings.read_settings.v1", &readTable);
            if (readResult.status == OVRTX_API_SUCCESS && readTable)
            {
                const auto* candidate = static_cast<const ReadSettingsV1*>(readTable);
                if (candidate->abiVersion == 1u &&
                    candidate->structSize >= sizeof(ReadSettingsV1) &&
                    candidate->getType && candidate->getBool && candidate->getInt)
                    readSettings = candidate;
            }
        }
        return true;
    }

    bool readBool(const char* path, bool& value, bool& present) const
    {
        present = false;
        if (!readSettings || !path)
            return false;
        const ovx_string_t key{path, std::strlen(path)};
        SettingType type = eSettingMissing;
        if (readSettings->getType(key, &type).status != OVRTX_API_SUCCESS)
            return false;
        if (type == eSettingMissing)
            return true;
        if (type != eSettingBool)
            return false;
        if (readSettings->getBool(key, &value).status != OVRTX_API_SUCCESS)
            return false;
        present = true;
        return true;
    }

    bool readInt(const char* path, int64_t& value, bool& present) const
    {
        present = false;
        if (!readSettings || !path)
            return false;
        const ovx_string_t key{path, std::strlen(path)};
        SettingType type = eSettingMissing;
        if (readSettings->getType(key, &type).status != OVRTX_API_SUCCESS)
            return false;
        if (type == eSettingMissing)
            return true;
        if (type != eSettingInt)
            return false;
        if (readSettings->getInt(key, &value).status != OVRTX_API_SUCCESS)
            return false;
        present = true;
        return true;
    }

    bool readSettingsAvailable() const { return readSettings != nullptr; }

    std::string lastError() const
    {
        if (!getLastError)
            return {};
        const ovx_string_t value = getLastError();
        return value.ptr ? std::string(value.ptr, value.length) : std::string{};
    }

    void close()
    {
        getVersion = nullptr;
        queryExtension = nullptr;
        writeAttribute = nullptr;
        step = nullptr;
        waitOp = nullptr;
        fetch = nullptr;
        map = nullptr;
        unmap = nullptr;
        destroy = nullptr;
        getLastError = nullptr;
        readSettings = nullptr;
        applySettingsAvailable = false;
        if (m_library)
        {
#  if defined(_WIN32)
            FreeLibrary(static_cast<HMODULE>(m_library));
#  else
            dlclose(m_library);
#  endif
            m_library = nullptr;
        }
    }

    GetVersion getVersion = nullptr;
    QueryExtension queryExtension = nullptr;
    WriteAttribute writeAttribute = nullptr;
    Step step = nullptr;
    WaitOp waitOp = nullptr;
    Fetch fetch = nullptr;
    Map map = nullptr;
    Unmap unmap = nullptr;
    Destroy destroy = nullptr;
    GetLastError getLastError = nullptr;
    const ReadSettingsV1* readSettings = nullptr;
    bool applySettingsAvailable = false;
    uint32_t major = 0;
    uint32_t minor = 0;
    uint32_t patch = 0;

private:
    void* m_library = nullptr;
};

bool stringEquals(ovx_string_t value, const char* expected)
{
    const size_t length = std::strlen(expected);
    return value.ptr && value.length == length && std::memcmp(value.ptr, expected, length) == 0;
}

static_assert(sizeof(ovx_string_t) == 16, "unsupported ovx_string_t ABI");

bool renderVarLayoutUsable(uint32_t stride, uint32_t nameOffset, uint32_t handleOffset)
{
    constexpr uint32_t kMaxRenderVarStride = 4096;
    return stride >= sizeof(ovx_string_t) && stride <= kMaxRenderVarStride &&
           nameOffset <= stride - sizeof(ovx_string_t) &&
           handleOffset <= stride - sizeof(ovrtx_render_var_output_handle_t);
}

bool findRenderVarOutput(const ovrtx_render_product_frame_output_t& frame,
                         uint32_t stride,
                         uint32_t nameOffset,
                         uint32_t handleOffset,
                         const char* sourceName,
                         ovrtx_render_var_output_handle_t& outputHandle)
{
    constexpr size_t kMaxRenderVarsPerFrame = 4096;
    if (!frame.output_render_vars || !renderVarLayoutUsable(stride, nameOffset, handleOffset) ||
        frame.render_var_count > kMaxRenderVarsPerFrame)
        return false;
    const auto* entries = reinterpret_cast<const unsigned char*>(frame.output_render_vars);
    for (size_t index = 0; index < frame.render_var_count; ++index)
    {
        const unsigned char* entry = entries + index * stride;
        ovx_string_t name{};
        ovrtx_render_var_output_handle_t handle = OVRTX_INVALID_HANDLE;
        std::memcpy(&name, entry + nameOffset, sizeof(name));
        std::memcpy(&handle, entry + handleOffset, sizeof(handle));
        if (stringEquals(name, sourceName))
        {
            outputHandle = handle;
            return true;
        }
    }
    return false;
}

#endif

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
                m_provider->setImageData(
                    m_presentationKey, {m_providerWidth, m_providerHeight}, PixelFormat::eRGBA8_UNORM);
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
#if !defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        (void)renderer; (void)libraryPath; (void)renderVarStride; (void)renderVarNameOffset;
        (void)renderVarHandleOffset; (void)provider; (void)renderProductPath;
        (void)cameraPath; (void)width; (void)height;
        fail("native frame pacing was built without the required OVRTX interfaces");
        return 0;
#else
        if (!renderer || !provider || !renderProductPath || !renderProductPath[0] || !cameraPath || !cameraPath[0] ||
            !width || !height || static_cast<uint64_t>(width) * height > kMaxFramePixels ||
            !renderVarLayoutUsable(renderVarStride, renderVarNameOffset, renderVarHandleOffset))
        {
            fail("native frame pacing start received an invalid borrow, path, or RenderVar layout");
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
        std::string openError;
        if (!m_api.open(libraryPath, openError))
        {
            failLocked(openError);
            return 0;
        }
        // Results are read with the struct layouts of the ovrtx headers this
        // file was built against, and those layouts change between ovrtx
        // minor releases. Only drive a runtime whose major.minor matches them.
        if (!m_api.getVersion || m_api.major != OVRTX_VERSION_MAJOR || m_api.minor != OVRTX_VERSION_MINOR)
        {
            const std::string runtimeVersion = m_api.getVersion
                ? std::to_string(m_api.major) + "." + std::to_string(m_api.minor) + "." + std::to_string(m_api.patch)
                : std::string("of unknown version");
            const std::string message = "ovrtx runtime " + runtimeVersion +
                " does not match the ovrtx " + std::to_string(OVRTX_VERSION_MAJOR) + "." +
                std::to_string(OVRTX_VERSION_MINOR) + " interfaces native frame pacing was built against";
            m_api.close();
            // Callers retry start every frame; report a persistent mismatch once.
            const bool repeated = m_stats.lastError == message;
            ++m_stats.errors;
            m_stats.lastError = message;
            m_stats.statusReason = "runtime_incompatible";
            if (!repeated)
                // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
                fprintf(stderr, "NativeFramePacing: %s\n", message.c_str());
            return 0;
        }
        m_renderer = reinterpret_cast<ovrtx_renderer_t*>(renderer);
        m_renderVarStride = renderVarStride;
        m_renderVarNameOffset = renderVarNameOffset;
        m_renderVarHandleOffset = renderVarHandleOffset;
        m_gpu = gpu;
        m_backend = backend;
        m_provider = std::move(provider);
        // The key is a dedicated valid Vulkan descriptor, separate from the
        // 12 producer slots. Saved UI geometry can match it by identity while
        // an input callback may safely stop pacing mid-widget-walk: draw
        // commands already emitted in that walk still bind a live descriptor.
        m_presentationKey = m_stablePresentationDescriptor;
        m_providerKeyInstalled = false;
        m_renderProductPath = renderProductPath;
        m_cameraPath = cameraPath;
        m_initialWidth = width;
        m_initialHeight = height;
        m_ownershipWidth = width;
        m_ownershipHeight = height;
        m_stopRequested = false;
        m_renderPauseRequested = false;
        m_renderPaused = false;
        m_active = true;
        m_renderExited = false;
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
        m_stats.ovrtxVersionMajor = m_api.major;
        m_stats.ovrtxVersionMinor = m_api.minor;
        m_stats.ovrtxVersionPatch = m_api.patch;
        m_stats.ownershipGeneration = 1;
        m_stats.statusReason = "active";
        refreshDlssRuntimeStateLocked();

        std::vector<uint8_t> initialPixels;
        try
        {
            m_slots.resize(kSlotCount);
            m_retainedMapHandles.reserve(1);
            // The steady-state pipeline transiently owns two accepted results.
            // Both can require deferred cleanup if teardown follows a release
            // failure, so reserve the full bounded failure set up front.
            m_retainedResultHandles.reserve(2);
            initialPixels.assign(static_cast<size_t>(width) * height * 4, 0);
        }
        catch (...)
        {
            failLocked("failed to allocate bounded initial frame-slot storage");
            m_active = false;
            m_stats.active = false;
            m_slots.clear();
            m_provider.reset();
            m_gpu = nullptr;
            m_backend = nullptr;
            m_renderer = nullptr;
            m_api.close();
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
        // before setImageData releases the old provider-owned texture.
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
        m_provider->setImageData(m_presentationKey, {width, height}, PixelFormat::eRGBA8_UNORM);
        m_providerKeyInstalled = true;
        m_providerWidth = width;
        m_providerHeight = height;
        const uint64_t token = m_token;
        try
        {
            m_renderThread = std::thread([this, token]() { renderLoop(token); });
            m_presentThread = std::thread([this, token]() { presentLoop(token); });
        }
        catch (...)
        {
            failLocked("failed to start native frame-pacing threads");
            lock.unlock();
            stop(token);
            return 0;
        }
        return token;
#endif
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
        double maximumPredictionDistance = 0.0;
        if (m_camera.serial != 0)
        {
            const long double dx = static_cast<long double>(world[12]) - m_camera.world[12];
            const long double dy = static_cast<long double>(world[13]) - m_camera.world[13];
            const long double dz = static_cast<long double>(world[14]) - m_camera.world[14];
            const long double displacement = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (std::isfinite(displacement))
            {
                const double candidate = static_cast<double>(displacement);
                if (std::isfinite(candidate))
                    maximumPredictionDistance = candidate;
            }
        }
        m_camera.world = world;
        m_camera.velocity = velocity;
        m_camera.timestamp = timestamp;
        m_camera.maximumPredictionDistance = maximumPredictionDistance;
        ++m_camera.serial;
        ++m_stats.cameraPublications;
        // Safe because publish is called on the UI thread and the provider's
        // texture reference remains the same stable key.
        if (width != m_providerWidth || height != m_providerHeight)
        {
            m_provider->setImageData(m_presentationKey, {width, height}, PixelFormat::eRGBA8_UNORM);
            m_providerWidth = width;
            m_providerHeight = height;
        }
        m_cv.notify_all();
        return true;
    }

    bool pauseRender(uint64_t token)
    {
        std::thread renderThread;
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait(lock, [this]() { return !m_stopCallActive; });
            if (!m_active || token != m_token || m_stopRequested)
                return false;
            if (m_renderPaused)
                return true;
            m_stopCallActive = true;
            m_renderPauseRequested = true;
            renderThread = std::move(m_renderThread);
        }
        m_cv.notify_all();
        if (renderThread.joinable())
            renderThread.join();

        const bool released = releaseRetainedOvrtxHandles();
        std::lock_guard<std::mutex> lock(m_mutex);
        const bool paused = released && m_active && token == m_token &&
            m_renderPaused && !m_stopRequested;
        if (paused)
        {
            // A render pause is the ownership boundary used before a Stage,
            // camera, RenderProduct, or extent mutation.  No queued image or
            // renderer-time anchor from the old state may be interpreted as
            // part of the resumed state.  ovrtx is allowed to restart its
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
            m_stats.statusReason = "cleanup_retry_required";
        m_stopCallActive = false;
        m_cv.notify_all();
        return paused;
    }

    bool resumeRender(uint64_t token)
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_cv.wait(lock, [this]() { return !m_stopCallActive; });
        if (!m_active || token != m_token || m_stopRequested)
            return false;
        if (!m_renderPaused)
            return !m_renderPauseRequested && m_renderThread.joinable();
        m_stopCallActive = true;
        m_renderPauseRequested = false;
        m_renderPaused = false;
        m_renderExited = false;
        m_renderFatal = false;
        try
        {
            m_renderThread = std::thread([this, token]() { renderLoop(token); });
        }
        catch (...)
        {
            m_renderPauseRequested = true;
            m_renderPaused = true;
            m_renderExited = true;
            m_renderFatal = true;
            failLocked("failed to resume the native frame-pacing render worker");
            m_stopCallActive = false;
            m_cv.notify_all();
            return false;
        }
        m_stopCallActive = false;
        m_cv.notify_all();
        return true;
    }

    bool stop(uint64_t token)
    {
        std::thread renderThread;
        std::thread presentThread;
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
            renderThread = std::move(m_renderThread);
            presentThread = std::move(m_presentThread);
        }
        m_cv.notify_all();
        if (renderThread.joinable()) renderThread.join();
        if (presentThread.joinable()) presentThread.join();

        if (!releaseRetainedOvrtxHandles())
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_stats.active = true;
            m_stats.statusReason = "cleanup_retry_required";
            // Keep the borrowed renderer, API, slots, provider, and token pinned.
            // A later stop(token) call retries only the failed releases.
            m_stopCallActive = false;
            m_cv.notify_all();
            return false;
        }

        std::lock_guard<std::mutex> lock(m_mutex);
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
        // Drain every UI/presenter sample before provider mutation can release
        // its prior image and before slot descriptors are destroyed.
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
            m_provider->setImageData(
                m_stablePresentationDescriptor,
                {m_providerWidth, m_providerHeight},
                PixelFormat::eRGBA8_UNORM);
        m_providerKeyInstalled = false;
        if (m_gpu)
        {
            for (Slot& slot : m_slots)
            {
                if (slot.gpuState)
                    m_gpu->destroyState(slot.gpuState);
                slot = {};
            }
        }
        m_slots.clear();
        m_provider.reset();
        m_presentationKey = nullptr;
        m_gpu = nullptr;
        m_backend = nullptr;
#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        m_renderer = nullptr;
        m_api.close();
#endif
        m_drawData.reset();
        m_camera = {};
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
            // destroy descriptors while ovrtx still owns a result/map. There
            // is no cancellation API, so retry the public release calls.
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        std::lock_guard<std::mutex> lock(m_mutex);
        releaseStablePresentationKeyLocked();
    }

    NativeFramePacingStats stats()
    {
        std::lock_guard<std::mutex> lock(m_mutex);
#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        if (m_active)
            refreshDlssRuntimeStateLocked();
#endif
        NativeFramePacingStats result = m_stats;
#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        result.supported = true;
#endif
        result.active = m_active;
        result.sessionToken = m_active ? m_token : 0;
        result.presentRate = m_presentRate;
        result.borrowedSlots = 0;
        for (const Slot& slot : m_slots)
            if (slot.references || slot.readers) ++result.borrowedSlots;
        result.renderLoopExited = m_renderExited;
        result.renderLoopFatal = m_renderFatal;
        result.renderPaused = m_renderPaused;
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
#if !defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        result.statusReason = "build_unavailable";
#else
        if (!m_active && result.lastError.empty())
            result.statusReason = "inactive";
        else if (!m_active && !result.lastError.empty() && result.statusReason != "backend_unavailable" &&
                 result.statusReason != "runtime_incompatible")
            result.statusReason = "runtime_error";
#endif
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
        bool uiComposed = false;
        bool baseCaptured = false;
        if (width > 0 && height > 0 && drawData)
        {
            std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
            if (m_backend->beginFrame(width, height))
            {
                ImGui_ImplVulkan_RenderDrawData(
                    const_cast<ImDrawData*>(drawData), m_backend->getCommandBuffer());
                uiComposed = m_backend->endFrame();
                if (uiComposed && saved && saved->valid())
                    baseCaptured = m_backend->snapshotNativeFramePacingBase(width, height);
            }
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

    void beginUiUpdate(VulkanBackend* backend)
    {
        std::unique_lock<std::mutex> lock(m_mutex);
        if (!m_active || m_stopRequested || backend != m_backend)
            return;
        m_uiGeometryUpdating = true;
        // Wait only while a presenter is composing a replay. Slot readers stay
        // held across the blocking display hand-off, which the UI never needs
        // to observe: backend ordering is already established by the shared
        // queue mutex and frame fence.
        m_cv.wait(lock, [this]() { return !m_active || !m_presenterComposing; });
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
            m_stablePresentationGpu->destroyState(m_stablePresentationGpuState);
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

    bool releaseRetainedOvrtxHandles()
    {
#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        bool allReleased = true;
        for (auto it = m_retainedMapHandles.begin(); it != m_retainedMapHandles.end();)
        {
            const ovrtx_cuda_sync_t noSync{0, 0};
            const ovrtx_result_t result = m_api.unmap(m_renderer, *it, noSync);
            if (result.status == OVRTX_API_SUCCESS)
            {
                {
                    std::lock_guard<std::mutex> lock(m_mutex);
                    if (m_stats.liveMappings) --m_stats.liveMappings;
                }
                it = m_retainedMapHandles.erase(it);
            }
            else
            {
                allReleased = false;
                ++it;
            }
        }
        if (m_retainedMapHandles.empty())
        {
            for (auto it = m_retainedResultHandles.begin(); it != m_retainedResultHandles.end();)
            {
                const ovrtx_result_t result = m_api.destroy(m_renderer, *it);
                if (result.status == OVRTX_API_SUCCESS)
                {
                    {
                        std::lock_guard<std::mutex> lock(m_mutex);
                        if (m_stats.liveStepResults) --m_stats.liveStepResults;
                    }
                    it = m_retainedResultHandles.erase(it);
                }
                else
                {
                    allReleased = false;
                    ++it;
                }
            }
        }
        else
        {
            // A fetched result owns the mapped output. Do not even attempt to
            // release its container until every failed map has been unmap-retried.
            allReleased = false;
        }
        if (!allReleased)
            fail(m_api.lastError().empty() ? "ovrtx cleanup release must be retried" : m_api.lastError());
        return allReleased;
#else
        return true;
#endif
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

#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
    void refreshDlssRuntimeStateLocked()
    {
        bool supported = false;
        bool supportedPresent = false;
        bool x3x4 = false;
        bool x3x4Present = false;
        bool enabled = false;
        bool enabledPresent = false;
        int64_t requestedCount = 0;
        bool requestedCountPresent = false;
        int64_t activeCount = 0;
        bool activeCountPresent = false;

        const bool readable = m_api.readSettingsAvailable() &&
            m_api.readBool(kDlssgSupportedSetting, supported, supportedPresent) &&
            m_api.readBool(kDlssgX3X4SupportedSetting, x3x4, x3x4Present) &&
            m_api.readBool(kDlssgEnabledSetting, enabled, enabledPresent) &&
            m_api.readInt(kDlssgRequestedCountSetting, requestedCount,
                          requestedCountPresent) &&
            m_api.readInt(kDlssgActiveCountSetting, activeCount,
                          activeCountPresent);
        m_stats.dlssGeneratedFrameRuntimeSupported =
            readable && supportedPresent && supported;
        m_stats.dlssGeneratedFrameX3X4Supported =
            readable && x3x4Present && x3x4;
        m_stats.dlssGeneratedFrameGlobalEnableOpinionPresent =
            readable && enabledPresent;
        m_stats.dlssGeneratedFrameRequestedEnabled =
            readable && enabledPresent && enabled;
        const int64_t count = requestedCountPresent ? requestedCount :
            (activeCountPresent ? activeCount : 0);
        m_stats.dlssGeneratedFrameRequestedCount = static_cast<int32_t>(
            std::max<int64_t>(std::numeric_limits<int32_t>::min(),
                std::min<int64_t>(std::numeric_limits<int32_t>::max(), count)));
        m_stats.dlssGeneratedFrameActivationSupported = readable &&
            m_api.applySettingsAvailable && supportedPresent && supported;
        if (!m_stats.dlssGeneratedFrameRuntimeSupported)
        {
            m_stats.dlssGeneratedFrameEffectiveActive = false;
            m_stats.dlssGeneratedFrameEffectiveCount = 0;
        }

        if (!m_api.readSettingsAvailable())
            m_stats.dlssGeneratedFrameCapability =
                "the current ovRTX runtime does not expose settings readback v1";
        else if (!readable)
            m_stats.dlssGeneratedFrameCapability =
                "the current ovRTX runtime rejected a typed DLSS-G settings read";
        else if (!m_api.applySettingsAvailable)
            m_stats.dlssGeneratedFrameCapability =
                "the current ovRTX runtime does not expose live settings publication";
        else if (!supportedPresent || !supported)
            m_stats.dlssGeneratedFrameCapability =
                "the current GPU/driver/NGX/ovRTX runtime reports DLSS-G unsupported";
        else
            m_stats.dlssGeneratedFrameCapability =
                std::string("supported; x3/x4=") + (x3x4 ? "true" : "false") +
                "; global_enable_opinion=" + (enabledPresent ? "present" : "absent") +
                "; requested_enabled=" + (enabled ? "true" : "false") +
                "; requested_count=" + std::to_string(count) +
                "; effective_output_count=" +
                std::to_string(m_stats.dlssGeneratedFrameEffectiveCount);
    }
#endif

#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
    bool writeCamera(const CameraPublication& publication, std::array<double, 16>& predictedWorld)
    {
        ovrtx_xform_matrix44d_t transform{};
        std::copy(publication.world.begin(), publication.world.end(), transform.v);
        const double elapsed = std::max(0.0, monotonicSeconds() - publication.timestamp);
        const double hardHorizon = kPredictionFullResponseSeconds + kPredictionDecaySeconds;
        double effectiveSeconds = 0.0;
        if (elapsed > 0.0 && elapsed < hardHorizon)
        {
            if (elapsed <= kPredictionFullResponseSeconds)
            {
                effectiveSeconds = elapsed;
            }
            else
            {
                // Cubic Hermite decay from the full-response position and
                // velocity to the authoritative anchor with zero terminal
                // velocity. Position and velocity are continuous at both
                // boundaries; after the hard horizon the untouched raw matrix
                // below is bit-stable.
                const double u = (elapsed - kPredictionFullResponseSeconds) /
                    kPredictionDecaySeconds;
                const double u2 = u * u;
                const double u3 = u2 * u;
                effectiveSeconds = (2.0 * u3 - 3.0 * u2 + 1.0) *
                    kPredictionFullResponseSeconds +
                    (u3 - 2.0 * u2 + u) * kPredictionDecaySeconds;
            }
        }

        double appliedDistance = 0.0;
        const long double vx = publication.velocity[0];
        const long double vy = publication.velocity[1];
        const long double vz = publication.velocity[2];
        const long double speed = std::sqrt(vx * vx + vy * vy + vz * vz);
        if (effectiveSeconds > 0.0 && speed > 0.0L && std::isfinite(speed) &&
            publication.maximumPredictionDistance > 0.0)
        {
            const long double requestedDistance = speed * effectiveSeconds;
            const long double distance = std::min(
                requestedDistance,
                static_cast<long double>(publication.maximumPredictionDistance));
            const long double scale = distance / speed;
            transform.v[12] += static_cast<double>(vx * scale);
            transform.v[13] += static_cast<double>(vy * scale);
            transform.v[14] += static_cast<double>(vz * scale);
            appliedDistance = static_cast<double>(distance);
        }
        std::copy(std::begin(transform.v), std::end(transform.v), predictedWorld.begin());
        {
        const ovx_string_t camera{m_cameraPath.c_str(), m_cameraPath.size()};
        const size_t count = 1;
        const DLDataType dtype{kDLFloat, 64, 16};
        int64_t shape = 1;
        int64_t stride = 1;
        DLTensor tensor{};
        tensor.data = &transform;
        tensor.device = {kDLCPU, 0};
        tensor.ndim = 1;
        tensor.dtype = dtype;
        tensor.shape = &shape;
        tensor.strides = &stride;
        ovrtx_input_buffer_t input{};
        input.tensors = &tensor;
        input.tensor_count = 1;
        ovrtx_binding_desc_or_handle_t binding{};
        binding.binding_desc.prim_list = {&camera, count};
        binding.binding_desc.attribute_name.string = {"omni:xform", 10};
        binding.binding_desc.attribute_type = {dtype, false, OVRTX_SEMANTIC_XFORM_MAT4x4};
        binding.binding_desc.prim_mode = OVRTX_BINDING_PRIM_MODE_EXISTING_ONLY;
        binding.binding_desc.flags = OVRTX_BINDING_FLAG_NONE;
        const ovrtx_enqueue_result_t result = m_api.writeAttribute(
            m_renderer, &binding, &input, OVRTX_DATA_ACCESS_SYNC);
        if (result.status != OVRTX_API_SUCCESS)
        {
            fail(m_api.lastError().empty() ? "camera publication failed" : m_api.lastError());
            return false;
        }
        }
        if (appliedDistance > 0.0)
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            ++m_stats.cameraIntegrations;
            m_stats.maximumPredictionOffset = std::max(
                m_stats.maximumPredictionOffset, appliedDistance);
        }
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_stats.authoritativeCameraWorld = publication.world;
            m_stats.hasAuthoritativeCameraWorld = true;
            m_stats.predictedCameraWorld = predictedWorld;
            m_stats.hasPredictedCameraWorld = true;
        }
        return true;
    }

    bool waitFetch(ovrtx_step_result_handle_t handle,
                   ovrtx_render_product_set_outputs_t& outputs,
                   bool drainOnly)
    {
        ovrtx_timeout_t timeout{0};
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            ++m_stats.fetchPolls;
        }
        ovrtx_result_t result = m_api.fetch(m_renderer, handle, timeout, &outputs);
        while (result.status == OVRTX_API_TIMEOUT)
        {
            timeout.time_out_ns = kBoundedWaitNanoseconds;
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                ++m_stats.fetchBoundedWaits;
            }
            result = m_api.fetch(m_renderer, handle, timeout, &outputs);
        }
        if (result.status != OVRTX_API_SUCCESS)
        {
            if (!drainOnly)
                fail(m_api.lastError().empty() ? "ovrtx result fetch failed" : m_api.lastError());
            return false;
        }
        return true;
    }

    /// Release every still-live mapping exactly once. Idempotent: a released
    /// entry is marked so a later call cannot unmap it again. A failed unmap
    /// retains the handle for the shutdown drain, matching the host path.
    void releaseMappings(std::vector<MappedImage>& images)
    {
        for (MappedImage& image : images)
        {
            if (!image.mapped)
                continue;
            image.mapped = false;
            image.devicePtr = nullptr;
            // GPU-resident publication copies from the mapped tensor on the
            // legacy default CUDA stream.  Let ovrtx retain its allocation
            // until that stream reaches the copy/signal handoff; CPU mappings
            // have already been copied synchronously and need no signal.
            const ovrtx_cuda_sync_t noSync{
                image.gpuResident ? kCudaDefaultStream : 0, 0};
            const ovrtx_result_t unmapResult =
                m_api.unmap(m_renderer, image.mapHandle, noSync);
            if (unmapResult.status != OVRTX_API_SUCCESS)
            {
                fail(m_api.lastError().empty() ? "LdrColor unmap failed" : m_api.lastError());
                m_retainedMapHandles.push_back(image.mapHandle);
                continue;
            }
            std::lock_guard<std::mutex> lock(m_mutex);
            if (m_stats.liveMappings) --m_stats.liveMappings;
        }
    }

    /// Map one LdrColor output as a CUDA device pointer. Returns false without
    /// consuming the output when the runtime cannot supply a usable GPU tensor,
    /// so the caller can fall back to the host copy below.
    bool mapImageGpu(ovrtx_render_var_output_handle_t handle, MappedImage& out,
                     uint32_t& width, uint32_t& height)
    {
        // sync_stream must name the stream the consumer will read on, or the
        // map performs no synchronisation at all (ovrtx_types.h: "0 = no
        // synchronization") and the device pointer can be read while the
        // renderer is still producing it — stale or torn frames. The Vulkan
        // upload issues its device-to-device copy on the legacy default
        // stream, which is stream id 1 in this API.
        ovrtx_map_output_description_t description{OVRTX_MAP_DEVICE_TYPE_CUDA,
                                                   kCudaDefaultStream};
        ovrtx_render_var_output_t output{};
        ovrtx_timeout_t timeout{0};
        ovrtx_result_t result = m_api.map(m_renderer, handle, &description, timeout, &output);
        while (result.status == OVRTX_API_TIMEOUT)
        {
            timeout.time_out_ns = kBoundedWaitNanoseconds;
            result = m_api.map(m_renderer, handle, &description, timeout, &output);
        }
        if (result.status != OVRTX_API_SUCCESS)
            return false;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            ++m_stats.liveMappings;
        }
        out.mapHandle = output.map_handle;
        out.mapped = true;

        bool usable = false;
        if (output.status == OVRTX_EVENT_COMPLETED && output.num_tensors > 0 &&
            output.tensors && output.tensors[0].dl)
        {
            const DLTensor& tensor = *output.tensors[0].dl;
            const bool packedPixels = !tensor.strides ||
                (tensor.strides[0] >= static_cast<int64_t>(tensor.shape[1]) * 4 &&
                 tensor.strides[1] == 4 && tensor.strides[2] == 1);
            if (tensor.device.device_type == kDLCUDA && tensor.ndim == 3 && tensor.shape &&
                tensor.data && tensor.shape[0] > 0 && tensor.shape[1] > 0 &&
                tensor.shape[2] == 4 && tensor.dtype.lanes == 1 &&
                tensor.dtype.code == kDLUInt && tensor.dtype.bits == 8 && packedPixels &&
                tensor.shape[0] <= std::numeric_limits<uint32_t>::max() &&
                tensor.shape[1] <= std::numeric_limits<uint32_t>::max() &&
                static_cast<uint64_t>(tensor.shape[0]) * tensor.shape[1] <= kMaxFramePixels)
            {
                height = static_cast<uint32_t>(tensor.shape[0]);
                width = static_cast<uint32_t>(tensor.shape[1]);
                out.devicePtr = static_cast<const uint8_t*>(tensor.data) + tensor.byte_offset;
                out.deviceRowStride = tensor.strides
                    ? static_cast<size_t>(tensor.strides[0])
                    : static_cast<size_t>(width) * 4;
                out.gpuResident = true;
                usable = true;
            }
        }
        if (!usable)
        {
            // Release this mapping before the caller retries on the host path;
            // the output itself has not been consumed.
            std::vector<MappedImage> single;
            single.push_back(std::move(out));
            releaseMappings(single);
            out = MappedImage{};
        }
        return usable;
    }

    bool mapImage(ovrtx_render_var_output_handle_t handle, std::vector<uint8_t>& pixels,
                  uint32_t& width, uint32_t& height)
    {
        ovrtx_map_output_description_t description{OVRTX_MAP_DEVICE_TYPE_CPU, 0};
        ovrtx_render_var_output_t output{};
        ovrtx_timeout_t timeout{0};
        ovrtx_result_t result = m_api.map(m_renderer, handle, &description, timeout, &output);
        while (result.status == OVRTX_API_TIMEOUT)
        {
            timeout.time_out_ns = kBoundedWaitNanoseconds;
            result = m_api.map(m_renderer, handle, &description, timeout, &output);
        }
        if (result.status != OVRTX_API_SUCCESS)
        {
            fail(m_api.lastError().empty() ? "LdrColor map failed" : m_api.lastError());
            return false;
        }
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            ++m_stats.liveMappings;
        }

        bool copied = false;
        try
        {
            if (output.status == OVRTX_EVENT_COMPLETED && output.num_tensors > 0 && output.tensors && output.tensors[0].dl)
            {
                const DLTensor& tensor = *output.tensors[0].dl;
                if (tensor.device.device_type == kDLCPU && tensor.ndim == 3 && tensor.shape &&
                    tensor.data && tensor.shape[0] > 0 && tensor.shape[1] > 0 && tensor.shape[2] == 4 &&
                    tensor.shape[0] <= std::numeric_limits<uint32_t>::max() &&
                    tensor.shape[1] <= std::numeric_limits<uint32_t>::max() && tensor.dtype.lanes == 1)
                {
                    height = static_cast<uint32_t>(tensor.shape[0]);
                    width = static_cast<uint32_t>(tensor.shape[1]);
                    const uint64_t count = static_cast<uint64_t>(width) * height * 4;
                    const int64_t rowStrideElements =
                        tensor.strides ? tensor.strides[0] : static_cast<int64_t>(width) * 4;
                    const size_t scalarBytes = tensor.dtype.bits / 8;
                    const bool packedPixels = !tensor.strides ||
                        (tensor.strides[0] >= static_cast<int64_t>(width) * 4 &&
                         tensor.strides[1] == 4 && tensor.strides[2] == 1);
                    const bool uint8Image = tensor.dtype.code == kDLUInt && tensor.dtype.bits == 8;
                    const bool float32Image = tensor.dtype.code == kDLFloat && tensor.dtype.bits == 32 &&
                        scalarBytes == sizeof(float);
                    if (static_cast<uint64_t>(width) * height <= kMaxFramePixels && packedPixels &&
                        (uint8Image || float32Image))
                    {
                        pixels.resize(static_cast<size_t>(count));
                        const uint8_t* base = static_cast<const uint8_t*>(tensor.data) + tensor.byte_offset;
                        if (uint8Image)
                        {
                            for (uint32_t y = 0; y < height; ++y)
                                std::memcpy(pixels.data() + static_cast<size_t>(y) * width * 4,
                                            base + static_cast<size_t>(y * rowStrideElements),
                                            static_cast<size_t>(width) * 4);
                            copied = true;
                        }
                        else
                        {
                            for (uint32_t y = 0; y < height; ++y)
                            {
                                const float* row = reinterpret_cast<const float*>(base +
                                    static_cast<size_t>(y * rowStrideElements) * sizeof(float));
                                for (uint32_t x = 0; x < width * 4; ++x)
                                {
                                    const float value = std::max(0.0f, std::min(1.0f, row[x]));
                                    pixels[(static_cast<size_t>(y) * width * 4) + x] =
                                        static_cast<uint8_t>(value * 255.0f + 0.5f);
                                }
                            }
                            copied = true;
                        }
                    }
                }
            }
        }
        catch (...)
        {
            fail("failed to allocate bounded CPU storage for a mapped LdrColor image");
            copied = false;
        }

        // The CPU copy is complete before unmap, so no producer signal is
        // carried beyond this point. Every successful map is unmapped once.
        const ovrtx_cuda_sync_t noSync{0, 0};
        const ovrtx_result_t unmapResult = m_api.unmap(m_renderer, output.map_handle, noSync);
        if (unmapResult.status != OVRTX_API_SUCCESS)
        {
            fail(m_api.lastError().empty() ? "LdrColor unmap failed" : m_api.lastError());
            m_retainedMapHandles.push_back(output.map_handle);
            copied = false;
        }
        else
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            if (m_stats.liveMappings) --m_stats.liveMappings;
        }
        if (!copied)
            fail("LdrColor did not expose a supported CPU RGBA tensor");
        return copied;
    }

    bool extractGroup(const ovrtx_render_product_set_outputs_t& outputs,
                      std::vector<MappedImage>& images,
                      std::vector<double>& frameEndTimes,
                      uint32_t& width,
                      uint32_t& height)
    {
        const ovrtx_render_product_output_t* product = nullptr;
        for (size_t i = 0; i < outputs.output_count; ++i)
        {
            if (stringEquals(outputs.outputs[i].render_product_path, m_renderProductPath.c_str()))
            {
                product = &outputs.outputs[i];
                break;
            }
        }
        if (!product || product->output_frame_count < 1 ||
            product->output_frame_count > kMaxOrderedFrames)
        {
            fail("ovrtx returned an unsupported ordered frame-group shape (expected 1, 2, 3, or 4)");
            return false;
        }
        std::vector<size_t> extractionOrder;
        try
        {
            images.resize(product->output_frame_count);
            frameEndTimes.resize(product->output_frame_count);
            extractionOrder.reserve(product->output_frame_count);
        }
        catch (...)
        {
            fail("failed to allocate bounded ordered frame-group storage");
            return false;
        }
        auto rejectTimestamps = [this](const char* reason) {
            fail(reason);
            std::lock_guard<std::mutex> lock(m_mutex);
            ++m_stats.rendererTimestampOrderViolations;
            return false;
        };
        for (size_t frameIndex = 0; frameIndex < product->output_frame_count;
             ++frameIndex)
        {
            const ovrtx_render_product_frame_output_t& frame =
                product->output_frames[frameIndex];
            if (!std::isfinite(frame.frame_start_time) ||
                !std::isfinite(frame.frame_end_time) ||
                frame.frame_end_time < frame.frame_start_time)
                return rejectTimestamps(
                    "ordered frame group contains an invalid renderer timestamp");
            if (frameIndex + 1 < product->output_frame_count)
            {
                const double instantTolerance = 1e-6 *
                    std::max(1.0, std::abs(frame.frame_end_time));
                if (std::abs(frame.frame_start_time - frame.frame_end_time) >
                    instantTolerance)
                    return rejectTimestamps(
                        "generated frame does not describe one renderer-time instant");
            }
            frameEndTimes[frameIndex] = frame.frame_end_time;
        }

        bool haveInterval = false;
        double expectedInterval = 0.0;
        double previousEnd = frameEndTimes.front();
        size_t firstComparedIndex = 1;
        if (m_hasLastAcceptedRealEndTime)
        {
            previousEnd = m_lastAcceptedRealEndTime;
            firstComparedIndex = 0;
        }
        for (size_t frameIndex = firstComparedIndex;
             frameIndex < frameEndTimes.size(); ++frameIndex)
        {
            const double interval = frameEndTimes[frameIndex] - previousEnd;
            if (!(interval > 0.0) || !std::isfinite(interval))
            {
                char message[320];
                std::snprintf(
                    message,
                    sizeof(message),
                    "ordered frame group renderer times are not strictly increasing "
                    "(previous=%.17g current=%.17g group_size=%zu index=%zu "
                    "previous_group=%s stop_requested=%s)",
                    previousEnd,
                    frameEndTimes[frameIndex],
                    frameEndTimes.size(),
                    frameIndex,
                    m_hasLastAcceptedRealEndTime ? "true" : "false",
                    stopRequested(m_token) ? "true" : "false");
                return rejectTimestamps(message);
            }
            if (!haveInterval)
            {
                expectedInterval = interval;
                haveInterval = true;
            }
            else
            {
                const double intervalTolerance =
                    std::max(1e-6, std::abs(expectedInterval) * 1e-4);
                if (std::abs(interval - expectedInterval) > intervalTolerance)
                    return rejectTimestamps(
                        "generated frame renderer times are not evenly spaced between real frames");
            }
            previousEnd = frameEndTimes[frameIndex];
        }
        // The final entry is the real rendered frame. Validate/copy it first so
        // generated images never become publishable without their real anchor,
        // while retaining the original array order for presentation.
        extractionOrder.push_back(product->output_frame_count - 1);
        for (size_t i = 0; i + 1 < product->output_frame_count; ++i)
            extractionOrder.push_back(i);
        for (size_t frameIndex : extractionOrder)
        {
            const ovrtx_render_product_frame_output_t& frame = product->output_frames[frameIndex];
            ovrtx_render_var_output_handle_t ldr = OVRTX_INVALID_HANDLE;
            findRenderVarOutput(frame, m_renderVarStride, m_renderVarNameOffset,
                                m_renderVarHandleOffset, "LdrColor", ldr);
            if (ldr == OVRTX_INVALID_HANDLE)
            {
                fail("ordered frame is missing LdrColor");
                return false;
            }
            uint32_t imageWidth = 0;
            uint32_t imageHeight = 0;
            MappedImage image;
            // Prefer the GPU-resident mapping so the displayed image never
            // makes a host round trip. Fall back to the host copy whenever the
            // build, device or tensor shape cannot supply one.
            bool wantGpu = m_gpu && m_gpu->supportsFromGpu();
            if (wantGpu)
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                wantGpu = !m_gpuPublishDisabled;
            }
            if (!wantGpu || !mapImageGpu(ldr, image, imageWidth, imageHeight))
            {
                if (!mapImage(ldr, image.pixels, imageWidth, imageHeight))
                    return false;
            }
            if (width != 0 && (imageWidth != width || imageHeight != height))
            {
                fail("ordered frame group contains inconsistent image extents");
                return false;
            }
            width = imageWidth;
            height = imageHeight;
            images[frameIndex] = std::move(image);
        }
        return true;
    }
#endif

    PublishResult uploadGroup(uint64_t token,
                     std::vector<MappedImage>& images,
                     const std::vector<double>& frameEndTimes,
                     uint32_t width,
                     uint32_t height,
                     uint64_t rendererFrameSerial,
                     const std::array<double, 16>& cameraWorld)
    {
        std::shared_ptr<FrameGroup> group;
        try
        {
            group = std::make_shared<FrameGroup>();
            group->slots.reserve(images.size());
            group->frameEndTimes = frameEndTimes;
        }
        catch (...)
        {
            fail("failed to allocate bounded Vulkan frame-group metadata");
            return PublishResult::eFailed;
        }
        group->cameraWorld = cameraWorld;
        group->rendererFrameSerial = rendererFrameSerial;
        uint64_t targetOwnershipGeneration = 0;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            targetOwnershipGeneration = m_stats.ownershipGeneration +
                ((width != m_ownershipWidth || height != m_ownershipHeight) ? 1 : 0);
            group->ownershipGeneration = targetOwnershipGeneration;
        }
        for (MappedImage& image : images)
        {
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
            if (image.gpuResident)
            {
                const uint8_t* data = static_cast<const uint8_t*>(image.devicePtr);
                size_t stride = image.deviceRowStride;
                VulkanByteImageGpu* nativeGpu = dynamic_cast<VulkanByteImageGpu*>(m_gpu);
                if (nativeGpu)
                    update = nativeGpu->updateImageFromGpuAsync(
                        slot.gpuState, data, stride, {width, height}, PixelFormat::eRGBA8_UNORM);
                if (update.imGuiReference)
                {
                    std::lock_guard<std::mutex> lock(m_mutex);
                    ++m_stats.gpuResidentPublications;
                }
                else
                {
                    // The device pair cannot carry this frame (no visible CUDA
                    // device, a mismatched adapter, an unsupported format).
                    // That is a capability answer, not a session error: latch
                    // GPU publication off so every later frame maps on the
                    // host, drop only this frame, and keep pacing alive.
                    std::lock_guard<std::mutex> lock(m_mutex);
                    m_gpuPublishDisabled = true;
                    ++m_stats.gpuPublicationFailures;
                    releaseGroupLocked(group);
                    return PublishResult::eSkippedRetryable;
                }
            }
            else
            {
                const uint8_t* data = image.pixels.data();
                size_t stride = static_cast<size_t>(width) * 4;
                update = m_gpu->updateImage(slot.gpuState, &data, &stride, 1, {width, height},
                                            PixelFormat::eRGBA8_UNORM, false, 0, 0, 0);
                if (update.imGuiReference)
                {
                    std::lock_guard<std::mutex> lock(m_mutex);
                    ++m_stats.hostFallbackPublications;
                }
            }
            if (!update.imGuiReference)
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                failLocked("failed to upload an ordered image into the Vulkan slot ring");
                releaseGroupLocked(group);
                return PublishResult::eFailed;
            }
            // A GPU-resident image is never read back, so distinct content
            // cannot be hashed without defeating the point. Use its unique
            // serial instead: content-distinctness degrades to
            // image-distinctness rather than reporting a false match.
            const uint64_t fingerprint = image.gpuResident
                ? ++m_nextContentFingerprint
                : rgbaFingerprint(image.pixels);
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
        switch (images.size())
        {
            case 1: ++m_stats.completedFrameGroupsSize1; break;
            case 2: ++m_stats.completedFrameGroupsSize2; break;
            case 3: ++m_stats.completedFrameGroupsSize3; break;
            case 4: ++m_stats.completedFrameGroupsSize4; break;
            default: break;
        }
        m_stats.dlssGeneratedFrameEffectiveCount =
            static_cast<int32_t>(images.size() - 1);
        m_stats.dlssGeneratedFrameEffectiveActive = images.size() > 1;
#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        refreshDlssRuntimeStateLocked();
#endif
        m_cv.notify_all();
        return PublishResult::ePublished;
    }

    void renderLoop(uint64_t token)
    {
#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
        struct PendingStep
        {
            ovrtx_step_result_handle_t handle = OVRTX_INVALID_HANDLE;
            ovrtx_enqueue_result_t enqueue{};
            std::array<double, 16> cameraWorld{};
            bool valid = false;
        };
        PendingStep retainedStep{};
        uint64_t observedPublication = 0;
        auto lastStep = Clock::now();
        while (true)
        {
            CameraPublication publication;
            {
                std::unique_lock<std::mutex> lock(m_mutex);
                m_cv.wait(lock, [this, token]() {
                    return !m_active || token != m_token || m_stopRequested ||
                        m_renderPauseRequested ||
                        (m_camera.serial != 0 && m_presentRate != 0.0 &&
                         !m_pendingGroup);
                });
                if (!m_active || token != m_token || m_stopRequested ||
                    m_renderPauseRequested)
                    break;
                publication = m_camera;
            }
            observedPublication = publication.serial;
            (void)observedPublication;
            std::array<double, 16> predictedWorld{};
            if (!writeCamera(publication, predictedWorld))
                break;

            const auto now = Clock::now();
            double rendererDelta = std::chrono::duration<double>(now - lastStep).count();
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                refreshDlssRuntimeStateLocked();
            }
            // Renderer time follows elapsed execution independently of the
            // configured presentation rate.  The returned frame timestamps
            // then promote a low positive presentation rate when necessary.
            const double delta = std::max(
                1.0 / 1000.0, std::min(1.0 / 15.0, rendererDelta));
            lastStep = now;
            const ovx_string_t productString{m_renderProductPath.c_str(), m_renderProductPath.size()};
            const ovrtx_render_product_set_t productSet{&productString, 1};
            ovrtx_step_result_handle_t handle = OVRTX_INVALID_HANDLE;
            ovrtx_enqueue_result_t stepResult{};
            stepResult = m_api.step(m_renderer, productSet, delta, &handle);
            if (stepResult.status != OVRTX_API_SUCCESS || handle == OVRTX_INVALID_HANDLE)
            {
                fail(m_api.lastError().empty() ? "ovrtx step enqueue failed" : m_api.lastError());
                break;
            }
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                ++m_stats.liveStepResults;
            }

            // Keep one accepted result in flight so the renderer can execute
            // frame N while frame N-1 is fetched, mapped, copied, hashed, and
            // uploaded.  The result handle and its exact predicted camera
            // travel together until publication; at most two accepted results
            // are transiently live while the previous one is retired below.
            PendingStep submitted{};
            submitted.handle = handle;
            submitted.enqueue = stepResult;
            submitted.cameraWorld = predictedWorld;
            submitted.valid = true;
            if (!retainedStep.valid)
            {
                retainedStep = std::move(submitted);
                continue;
            }
            handle = retainedStep.handle;
            stepResult = retainedStep.enqueue;
            predictedWorld = retainedStep.cameraWorld;
            retainedStep = std::move(submitted);

            ovrtx_render_product_set_outputs_t outputs{};
            const bool draining = stopRequested(token);
            const bool fetched = waitFetch(handle, outputs, draining);
            std::vector<MappedImage> images;
            std::vector<double> frameEndTimes;
            // Any mapping still live when this scope unwinds is released
            // exactly once, whichever branch below exits the iteration.
            struct MappingGuard
            {
                NativeFramePacingService* service;
                std::vector<MappedImage>* images;
                ~MappingGuard() { service->releaseMappings(*images); }
            } mappingGuard{this, &images};
            uint32_t width = 0;
            uint32_t height = 0;
            bool extracted = false;
            uint64_t rendererFrameSerial = 0;
            const size_t retainedMapsBefore = m_retainedMapHandles.size();
            if (fetched && !draining)
                extracted = extractGroup(
                    outputs, images, frameEndTimes, width, height);
            if (extracted)
            {
                // Count completed usable ovrtx outputs at fetch/map completion,
                // before slot pressure or a Vulkan upload can drop them.
                std::lock_guard<std::mutex> lock(m_mutex);
                // Renderer-time continuity belongs to the validated output
                // sequence, not to the later GPU/host publication transport.
                // A retryable GPU refusal drops this group before switching
                // subsequent groups to host publication, but ovrtx still
                // advances its next generated timestamps from this real
                // anchor. Retaining the older published anchor would falsely
                // reject that next well-formed group as uneven and terminate
                // pacing instead of allowing the required host fallback.
                m_lastAcceptedRealEndTime = frameEndTimes.back();
                m_hasLastAcceptedRealEndTime = true;
                ++m_stats.realRenderCompletions;
                ++m_stats.rendererCompletions;
                rendererFrameSerial = ++m_nextRendererFrameSerial;
                m_stats.generatedImages += images.size() - 1;
            }
            // Exactly one destroy for every accepted result handle, after all
            // output maps have been copied and unmapped.
            if (m_retainedMapHandles.size() != retainedMapsBefore)
            {
                m_retainedResultHandles.push_back(handle);
                break;
            }
            else
            {
                const ovrtx_result_t destroyResult = m_api.destroy(m_renderer, handle);
                if (destroyResult.status != OVRTX_API_SUCCESS)
                {
                    m_retainedResultHandles.push_back(handle);
                    fail(m_api.lastError().empty() ? "ovrtx result release failed" : m_api.lastError());
                    break;
                }
                {
                    std::lock_guard<std::mutex> lock(m_mutex);
                    if (m_stats.liveStepResults) --m_stats.liveStepResults;
                }
            }
            if (draining)
                break;
            if (fetched && !extracted)
                break;
            if (fetched && extracted &&
                uploadGroup(token, images, frameEndTimes, width, height,
                            rendererFrameSerial, predictedWorld) ==
                    PublishResult::eFailed)
                break;
        }
        // A stop or failure may leave the newest accepted step retained.  It
        // is never publishable after revocation, but its non-cancellable work
        // must still be observed, fetched, and destroyed exactly once before
        // the renderer borrow can return to Python.
        if (retainedStep.valid)
        {
            ovrtx_render_product_set_outputs_t outputs{};
            (void)waitFetch(retainedStep.handle, outputs, true);
            const ovrtx_result_t destroyResult = m_api.destroy(m_renderer, retainedStep.handle);
            if (destroyResult.status != OVRTX_API_SUCCESS)
            {
                m_retainedResultHandles.push_back(retainedStep.handle);
                fail(m_api.lastError().empty() ?
                    "ovrtx retained result release failed" : m_api.lastError());
            }
            else
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                if (m_stats.liveStepResults) --m_stats.liveStepResults;
            }
        }
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
                }
                else
                {
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
#else
        (void)token;
#endif
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
            if (attempted)
            {
                std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
                bool frameDeferred = false;
                if (m_backend->beginFrame(width, height, true, false))
                {
                    ImGui_ImplVulkan_RenderDrawData(
                        drawData->selectViewportImage(const_cast<void*>(descriptor)),
                        m_backend->getCommandBuffer());
                    composed = m_backend->endFrame() && m_backend->restoreNativeFramePacingBase(
                        drawData->copyRegions(), width, height);
                    if (composed)
                    {
                        preparedWindow = m_backend->prepareWindowFrame(
                            width, height, &swapchainImage);
                        if (preparedWindow == VulkanBackend::WindowPresentResult::eFailed)
                            composed = false;
                    }
                }
                else
                {
                    frameDeferred = m_backend->isInitialized();
                }
                if (frameDeferred)
                    attempted = false;
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
                const VulkanBackend::WindowPresentResult presentResult =
                    m_backend->presentWindowFrame(swapchainImage);
                presentSubmitNanoseconds = static_cast<uint64_t>(
                    std::chrono::duration_cast<std::chrono::nanoseconds>(
                        Clock::now() - presentStartedAt).count());
                presentCompletedAt = Clock::now();
                presentSubmitSucceeded =
                    presentResult == VulkanBackend::WindowPresentResult::ePresented;
                if (!presentSubmitSucceeded)
                    composed = false;
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
        }
    }

    mutable std::mutex m_mutex;
    std::condition_variable m_cv;
    bool m_active = false;
    bool m_stopRequested = false;
    bool m_renderPauseRequested = false;
    bool m_renderPaused = false;
    bool m_presenterComposing = false;
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
    uint32_t m_initialWidth = 0;
    uint32_t m_initialHeight = 0;
    uint32_t m_providerWidth = 0;
    uint32_t m_providerHeight = 0;
    uint32_t m_ownershipWidth = 0;
    uint32_t m_ownershipHeight = 0;
    std::string m_renderProductPath;
    std::string m_cameraPath;
    CameraPublication m_camera;
    std::thread m_renderThread;
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
    bool m_renderFatal = false;
    bool m_hasSelectedCameraWorld = false;
    bool m_selectedImageGenerated = false;
    std::array<double, 16> m_selectedCameraWorld{};
#if defined(OMNIUI_HAS_OVRTX_FRAME_PACING)
    OvrtxApi m_api;
    ovrtx_renderer_t* m_renderer = nullptr;
    uint32_t m_renderVarStride = 0;
    uint32_t m_renderVarNameOffset = 0;
    uint32_t m_renderVarHandleOffset = 0;
    std::vector<ovrtx_render_var_output_map_handle_t> m_retainedMapHandles;
    std::vector<ovrtx_step_result_handle_t> m_retainedResultHandles;
#endif
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

bool resumeNativeFramePacingRender(uint64_t token)
{
    return service().resumeRender(token);
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
