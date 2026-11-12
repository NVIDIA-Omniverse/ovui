/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "StandaloneSvgRasterizer.h"

#include "StandaloneImageBackend.h"
#include "StandaloneSvgDocument.h"
#include "platform/Log.h"
#include "platform/IUiFileIO.h"

#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <new>
#include <stdexcept>

namespace omni {
namespace ui {
namespace standalone {

namespace {

/// The bitmap is drawn at this multiple of the widget size, so a scaled-down
/// draw stays sharp on a high-DPI screen.
constexpr double kOversample = 2.0;
/// Longest bitmap side. Bounds the memory that one icon can use.
constexpr double kMaxBitmapSide = 2048.0;
/// Largest SVG file that is read. A larger file is not an icon.
constexpr std::streamoff kMaxFileBytes = 32 * 1024 * 1024;

std::string joinNames(const std::vector<std::string>& names)
{
    std::string out;
    for (const std::string& name : names)
    {
        if (!out.empty())
            out += ", ";
        out += name;
    }
    return out;
}

} // anonymous namespace

#ifdef OVUI_SVG_TEST_SEAM
std::atomic<int> g_svgThrowOnNextDrawForTest{ 0 };
#endif

StandaloneSvgRasterizer::~StandaloneSvgRasterizer()
{
    shutdown();
}

void StandaloneSvgRasterizer::shutdown()
{
    std::lock_guard<std::mutex> lock(m_mutex);
    m_shutdown = true;
    for (auto& kv : m_cache)
        _destroyEntry(kv.second);
    m_cache.clear();
    m_requests.clear();
}

void StandaloneSvgRasterizer::_destroyEntry(Entry& entry)
{
    if (!entry.gpuState)
        return;
    if (auto* gpu = PlatformRegistry::instance().byteImageGpu())
        gpu->destroyState(entry.gpuState);
    entry.gpuState = nullptr;
}

void StandaloneSvgRasterizer::_logFailureOnce(const std::string& url, const std::string& reason)
{
    // Caller holds m_mutex. The same error of a URL is logged once; another
    // error, or the same one after the URL drew, is logged again.
    std::string& last = m_loggedFailures[url];
    if (last == reason)
        return;
    last = reason;
    OMNIUI_LOG_ERROR("SVG: cannot draw '%s': %s", url.c_str(), reason.c_str());
}

void StandaloneSvgRasterizer::_logWarningsOnce(const std::string& url,
                                               const std::vector<std::string>& skipped,
                                               const std::vector<std::string>& changed)
{
    // Caller holds m_mutex. The URL drew: a later error is new.
    m_loggedFailures.erase(url);
    const std::string key = joinNames(skipped) + "\n" + joinNames(changed);
    std::string& last = m_loggedWarnings[url];
    if (last == key)
        return;
    last = key;
    if (!skipped.empty())
        OMNIUI_LOG_WARN("SVG: '%s' is drawn without these parts, which ovui does not draw: %s", url.c_str(),
                        joinNames(skipped).c_str());
    for (const std::string& what : changed)
        OMNIUI_LOG_WARN("SVG: '%s' is drawn differently from the file: %s", url.c_str(), what.c_str());
}

namespace {

/// Read SVG text that has shapes to draw. Returns false and sets `error` when
/// the text is not a usable SVG, is over a work limit or has no shape.
bool parseDrawableSvg(const std::string& svgText,
                      svg::Document& doc,
                      std::string& error,
                      std::vector<std::string>* skipped)
{
    if (!svg::parseSvgDocument(svgText, doc, error))
        return false;
    if (skipped)
        *skipped = doc.skipped;
    if (doc.shapeCount == 0)
    {
        error = "the SVG has no shapes to draw";
        if (!doc.skipped.empty())
            error += " (not drawn: " + joinNames(doc.skipped) + ")";
        return false;
    }
    return true;
}

/// Paint the document with `scale` bitmap pixels for each pixel of the SVG
/// size, the longest side at most kMaxBitmapSide.
bool paintSvgAtScale(const svg::Document& doc,
                     double scale,
                     StandaloneSvgRasterizer::Bitmap& out,
                     std::string& error,
                     std::vector<std::string>* changed)
{
    std::vector<std::string> drawnDifferently = doc.changed;
    const double docWidth = doc.width;
    const double docHeight = doc.height;
    const double longSide = std::max(docWidth, docHeight) * scale;
    if (longSide > kMaxBitmapSide)
        scale *= kMaxBitmapSide / longSide;

    // Within 1 .. kMaxBitmapSide before the conversion, also for NaN.
    auto side = [](double v) {
        v = std::ceil(v - 1e-6);
        return static_cast<uint32_t>(v >= 1.0 ? std::min(v, kMaxBitmapSide) : 1.0);
    };
    const uint32_t width = side(docWidth * scale);
    const uint32_t height = side(docHeight * scale);
    out.width = width;
    out.height = height;
    if (!svg::renderSvgDocument(doc, width, height, out.rgba, error, drawnDifferently))
        return false;
    if (changed)
        *changed = std::move(drawnDifferently);
    return true;
}

} // anonymous namespace

bool StandaloneSvgRasterizer::rasterizeToBitmap(const std::string& svgText,
                                                float widgetWidth,
                                                float widgetHeight,
                                                Bitmap& out,
                                                std::string& error,
                                                std::vector<std::string>* skipped,
                                                std::vector<std::string>* changed)
{
    if (!(widgetWidth > 0.0f) || !(widgetHeight > 0.0f) || !std::isfinite(widgetWidth) ||
        !std::isfinite(widgetHeight))
    {
        error = "the widget size is not positive";
        return false;
    }

    svg::Document doc;
    if (!parseDrawableSvg(svgText, doc, error, skipped))
        return false;

    const double docWidth = doc.width;
    const double docHeight = doc.height;
    const double scale = std::min(widgetWidth / docWidth, widgetHeight / docHeight) * kOversample;
    if (!(scale > 0.0) || !std::isfinite(scale))
    {
        // For example a size of 1e-307: the scale to the widget overflows.
        char size[64];
        std::snprintf(size, sizeof(size), "%g x %g", docWidth, docHeight);
        error = std::string("the SVG size (") + size + " pixels) is too small to scale to the widget";
        return false;
    }
    return paintSvgAtScale(doc, scale, out, error, changed);
}

bool StandaloneSvgRasterizer::rasterizeToBitmapAtOwnSize(const std::string& svgText,
                                                         Bitmap& out,
                                                         std::string& error,
                                                         std::vector<std::string>* skipped,
                                                         std::vector<std::string>* changed)
{
    if (static_cast<std::streamoff>(svgText.size()) > kMaxFileBytes)
    {
        error = "the file is larger than 32 MiB";
        return false;
    }
    // No exception may leave the frame: a failure leaves the image empty and
    // is reported with its cause.
    try
    {
        svg::Document doc;
        if (!parseDrawableSvg(svgText, doc, error, skipped))
            return false;
        return paintSvgAtScale(doc, 1.0, out, error, changed);
    }
    catch (const std::bad_alloc&)
    {
        error = "there was not enough memory to read and paint it (std::bad_alloc)";
    }
    catch (const std::exception& e)
    {
        error = std::string("reading and painting it failed: ") + e.what();
    }
    catch (...)
    {
        error = "reading and painting it failed with an unknown exception";
    }
    out = Bitmap{};
    return false;
}

ISvgRasterizer::RasterResult StandaloneSvgRasterizer::rasterize(const std::string& url,
                                                                float widgetWidth,
                                                                float widgetHeight,
                                                                size_t /*maxMipLevels*/,
                                                                const ImageProviderTextureOptions& /*textureOptions*/)
{
    RasterResult result;

    std::string path = url;
    if (auto* fileIO = PlatformRegistry::instance().fileIO())
        path = fileIO->resolvePath(url.c_str());
    path = StandaloneImageBackend::urlToLocalPath(path);

    std::lock_guard<std::mutex> lock(m_mutex);
    if (m_shutdown)
        return result;

    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (!gpu)
    {
        _logFailureOnce(url, "no GPU texture upload is available for the active render backend");
        return result;
    }

    // The same file at the same widget size: its texture is shared without
    // reading the file again.
    const std::string requestKey = path + "@" + std::to_string(widgetWidth) + "x" + std::to_string(widgetHeight);
    auto request = m_requests.find(requestKey);
    if (request != m_requests.end())
    {
        auto cached = m_cache.find(request->second);
        if (cached != m_cache.end())
            return _share(cached->first, cached->second);
        m_requests.erase(request);
    }

    // No exception may leave the frame: a failure here leaves the image
    // empty and is logged with its cause.
    try
    {
        return _drawAndUpload(url, path, requestKey, widgetWidth, widgetHeight);
    }
    catch (const std::bad_alloc&)
    {
        _logFailureOnce(url, "there was not enough memory to read and paint it (std::bad_alloc)");
    }
    catch (const std::exception& e)
    {
        _logFailureOnce(url, std::string("reading and painting it failed: ") + e.what());
    }
    catch (...)
    {
        _logFailureOnce(url, "reading and painting it failed with an unknown exception");
    }
    return result;
}

ISvgRasterizer::RasterResult StandaloneSvgRasterizer::_drawAndUpload(const std::string& url,
                                                                    const std::string& path,
                                                                    const std::string& requestKey,
                                                                    float widgetWidth,
                                                                    float widgetHeight)
{
    // Caller holds m_mutex.
    RasterResult result;
    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file)
    {
        _logFailureOnce(url, "the file does not exist or cannot be read");
        return result;
    }
    const std::streamoff fileSize = file.tellg();
    if (fileSize <= 0 || fileSize > kMaxFileBytes)
    {
        _logFailureOnce(url, fileSize <= 0 ? "the file is empty" : "the file is larger than 32 MiB");
        return result;
    }
    file.seekg(0);
    std::string text(static_cast<size_t>(fileSize), '\0');
    if (!file.read(text.data(), fileSize))
    {
        _logFailureOnce(url, "the file cannot be read");
        return result;
    }

#ifdef OVUI_SVG_TEST_SEAM
    const int fault = g_svgThrowOnNextDrawForTest.exchange(0);
    if (fault == 1)
        throw std::bad_alloc();
    if (fault == 2)
        throw std::runtime_error("injected failure for the test");
#endif

    Bitmap bitmap;
    std::string error;
    std::vector<std::string> skipped;
    std::vector<std::string> changed;
    if (!rasterizeToBitmap(text, widgetWidth, widgetHeight, bitmap, error, &skipped, &changed))
    {
        _logFailureOnce(url, error);
        return result;
    }
    _logWarningsOnce(url, skipped, changed);

    const std::string cacheKey = path + "@" + std::to_string(bitmap.width) + "x" + std::to_string(bitmap.height);
    auto it = m_cache.find(cacheKey);
    if (it == m_cache.end())
    {
        void* state = gpu->createState();
        if (!state)
        {
            _logFailureOnce(url, "the GPU texture cannot be created");
            return result;
        }

        const uint8_t* mip = bitmap.rgba.data();
        size_t stride = static_cast<size_t>(bitmap.width) * 4;
        auto upload = gpu->updateImage(state, &mip, &stride, 1, UInt2{ bitmap.width, bitmap.height },
                                       PixelFormat::eRGBA8_UNORM,
                                       /*fromGpu*/ false,
                                       /*gpuDeviceMask*/ 0,
                                       /*textureUsageFlags*/ 0,
                                       /*resourceUsageFlags*/ 0);
        // The texture is freed if anything below fails, also by an exception.
        struct StateGuard
        {
            IByteImageGpu* gpu;
            void* state;
            ~StateGuard()
            {
                if (state)
                    gpu->destroyState(state);
            }
        } guard{ gpu, state };
        if (!upload.imGuiReference)
        {
            _logFailureOnce(url, "the GPU texture upload failed");
            return result;
        }

        Entry entry;
        entry.gpuState = state;
        entry.imGuiReference = upload.imGuiReference;
        entry.size = UInt2{ bitmap.width, bitmap.height };
        it = m_cache.emplace(cacheKey, entry).first;
        guard.state = nullptr; // the cache owns it now
    }

    m_requests[requestKey] = cacheKey;
    std::vector<std::string>& requests = it->second.requests;
    if (std::find(requests.begin(), requests.end(), requestKey) == requests.end())
        requests.push_back(requestKey);
    return _share(cacheKey, it->second);
}

ISvgRasterizer::RasterResult StandaloneSvgRasterizer::_share(const std::string& cacheKey, Entry& entry)
{
    // Caller holds m_mutex.
    ++entry.refCount;
    RasterResult result;
    result.success = true;
    result.imGuiReference = entry.imGuiReference;
    result.imageSize = entry.size;
    result.imageFormat = PixelFormat::eRGBA8_UNORM;
    result.cacheKey = cacheKey;
    return result;
}

void StandaloneSvgRasterizer::releaseGpuResource(const std::string& cacheKey)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto it = m_cache.find(cacheKey);
    if (it == m_cache.end())
        return;
    if (--it->second.refCount <= 0)
    {
        _destroyEntry(it->second);
        for (const std::string& request : it->second.requests)
            m_requests.erase(request);
        m_cache.erase(it);
    }
}

} // namespace standalone
} // namespace ui
} // namespace omni
