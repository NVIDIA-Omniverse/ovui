/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "platform/ISvgRasterizer.h"

#ifdef OVUI_SVG_TEST_SEAM
#    include <atomic>
#endif
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

/// Standalone ISvgRasterizer implementation. It reads and paints SVG with the
/// project's own code (StandaloneSvgDocument.h). ui.ImageWithProvider (through
/// VectorImageProvider) and ui.Image (through StandaloneImageBackend) draw
/// .svg files with it, and the Markdown widget decodes SVG images with
/// rasterizeToBitmapAtOwnSize (through StandaloneFileIO::decodeImage). It is
/// built only when the CMake option OMNIUI_ENABLE_SVG is ON. With the option
/// OFF, `init` registers StandaloneSvgOffRasterizer in its place: .svg images
/// draw nothing, and each URL logs one error with the cause.
///
/// rasterize() reads a local SVG file, draws it to an RGBA8 bitmap and uploads
/// the bitmap through the registered IByteImageGpu. The bitmap keeps the aspect
/// ratio of the SVG and fits inside the widget size, drawn at twice that size
/// so that scaled-down drawing stays sharp. Textures are cached per file and
/// bitmap size, and shared by every consumer that asks for the same pair. A
/// request for a file and widget size that has a cached texture gets it
/// without reading the file again, as cached PNG images do.
///
/// <text>, <image>, <foreignObject>, <pattern> paint, masks, filters,
/// markers and a transform on <svg> are not drawn. A file that has such parts
/// and shapes too draws its shapes and logs one warning that names the parts
/// left out. Parts drawn differently from the file (for example a dash pattern
/// too fine to draw dash by dash) log one warning with the cause.
///
/// A failure leaves the image empty and logs one error with the cause:
/// "SVG: cannot draw '<url>': <cause>". This includes a file over a work limit
/// of the reader or painter and an exception (for example std::bad_alloc)
/// while the file is read or painted; no exception leaves rasterize(). The
/// same error or warning of a URL is logged once; after the URL draws without
/// it, it is logged again when it comes back. A failure is not cached, so a
/// file that appears later is found by the next provider that loads it.
class StandaloneSvgRasterizer final : public ISvgRasterizer
{
public:
    StandaloneSvgRasterizer() = default;
    ~StandaloneSvgRasterizer() override;

    RasterResult rasterize(const std::string& url,
                           float widgetWidth,
                           float widgetHeight,
                           size_t maxMipLevels,
                           const ImageProviderTextureOptions& textureOptions) override;
    void releaseGpuResource(const std::string& cacheKey) override;

    /// Destroy every cached texture while IByteImageGpu is still registered,
    /// and refuse new loads after that.
    void shutdown();

    /// A drawn bitmap: straight-alpha RGBA8, rows without padding.
    struct Bitmap
    {
        uint32_t width = 0;
        uint32_t height = 0;
        std::vector<uint8_t> rgba;
    };

    /// Draw SVG text to a bitmap that fits inside widgetWidth x widgetHeight
    /// (times the oversampling factor). Returns false and sets `error` when the
    /// text is not a usable SVG or is over a work limit. `skipped` gets the
    /// parts of the file that are not drawn (for example "<text>"), `changed`
    /// the parts drawn differently from the file, with the cause. Needs no
    /// GPU, window or file.
    static bool rasterizeToBitmap(const std::string& svgText,
                                  float widgetWidth,
                                  float widgetHeight,
                                  Bitmap& out,
                                  std::string& error,
                                  std::vector<std::string>* skipped = nullptr,
                                  std::vector<std::string>* changed = nullptr);

    /// Draw SVG text at its own size: the width and height of its root <svg>
    /// in pixels (the longest side at most 2048), as an image file is shown at
    /// the size of its pixels. Returns false and sets `error` as
    /// rasterizeToBitmap does, also for text larger than 32 MiB and for an
    /// exception (for example std::bad_alloc) while the text is read or
    /// painted; no exception leaves this function. Needs no GPU, window or
    /// file.
    static bool rasterizeToBitmapAtOwnSize(const std::string& svgText,
                                           Bitmap& out,
                                           std::string& error,
                                           std::vector<std::string>* skipped = nullptr,
                                           std::vector<std::string>* changed = nullptr);

private:
    struct Entry
    {
        void* gpuState = nullptr; ///< IByteImageGpu::Handle
        void* imGuiReference = nullptr;
        UInt2 size = {};
        int refCount = 0;
        std::vector<std::string> requests; ///< the keys of m_requests that name this entry
    };

    void _logFailureOnce(const std::string& url, const std::string& reason);
    void _logWarningsOnce(const std::string& url,
                          const std::vector<std::string>& skipped,
                          const std::vector<std::string>& changed);
    /// Reads, paints and uploads the file of a request that has no texture
    /// yet. Caller holds m_mutex.
    RasterResult _drawAndUpload(const std::string& url,
                                const std::string& path,
                                const std::string& requestKey,
                                float widgetWidth,
                                float widgetHeight);
    void _destroyEntry(Entry& entry);
    RasterResult _share(const std::string& cacheKey, Entry& entry);

    std::mutex m_mutex;
    std::unordered_map<std::string, Entry> m_cache;
    /// File and widget size of a request -> the key of its entry in m_cache.
    std::unordered_map<std::string, std::string> m_requests;
    /// URL -> the error last logged for it; removed when the URL draws.
    std::unordered_map<std::string, std::string> m_loggedFailures;
    /// URL -> the warnings last logged for it.
    std::unordered_map<std::string, std::string> m_loggedWarnings;
    bool m_shutdown = false;
};

#ifdef OVUI_SVG_TEST_SEAM
/// Test seam, compiled only into standalone_svg_rasterizer_tests, never into
/// the product library. When it is 1 (std::bad_alloc) or 2
/// (std::runtime_error), the next rasterize() that reads a file throws that
/// exception where the file is read and painted, and sets it back to 0.
extern std::atomic<int> g_svgThrowOnNextDrawForTest;
#endif

} // namespace standalone
} // namespace ui
} // namespace omni
