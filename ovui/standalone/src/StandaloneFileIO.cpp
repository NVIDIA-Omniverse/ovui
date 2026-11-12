/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "StandaloneFileIO.h"
#ifdef OMNIUI_HAS_SVG
#include "StandaloneSvgRasterizer.h"
#endif

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/platform/IUiPlatform.h>
#include <omni/ui/platform/Log.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_NO_STDIO          // we load from memory, not FILE*
#define STBI_NO_HDR            // omni.ui doesn't need HDR float images
#include <stb_image.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <cstdlib>
#include <future>
#include <iterator>
#include <string_view>
#include <system_error>
#include <stdexcept>
#ifdef OVUI_FILE_IO_TEST_SEAM
#include <atomic>
#endif

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#elif defined(__linux__)
#include <dlfcn.h>
#endif

namespace fs = std::filesystem;

namespace omni {
namespace ui {
namespace standalone {

/// Find the resources base directory.  Try the library location first (wheel
/// installs place resources/ next to the .so), then fall back to CWD.
static std::string findResourcesBase()
{
#ifdef _WIN32
    {
        HMODULE hModule = nullptr;
        if (GetModuleHandleExW(
                GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<LPCWSTR>(&findResourcesBase), &hModule))
        {
            wchar_t modulePath[MAX_PATH];
            if (GetModuleFileNameW(hModule, modulePath, MAX_PATH))
            {
                fs::path libDir = fs::path(modulePath).parent_path();
                fs::path candidate = libDir / "resources";
                if (fs::is_directory(candidate))
                    return (candidate / "").string();
            }
        }
    }
#elif defined(__linux__)
    {
        Dl_info info;
        if (dladdr(reinterpret_cast<void*>(&findResourcesBase), &info) && info.dli_fname)
        {
            fs::path libDir = fs::path(info.dli_fname).parent_path();
            fs::path candidate = libDir / "resources";
            if (fs::is_directory(candidate))
                return (candidate / "").string(); // ensure trailing slash
        }
    }
#endif
    // Fallback: CWD-relative
    if (fs::is_directory("resources"))
        return "resources/";

    // Check parent dirs (common in build subdirectories)
    std::error_code ec;
    fs::path cwd = fs::current_path(ec);
    for (int i = 0; i < 3 && !cwd.empty(); ++i)
    {
        if (fs::is_directory(cwd / "resources"))
            return (cwd / "resources" / "").string();
        cwd = cwd.parent_path();
    }

    return "resources/";
}

StandaloneFileIO::StandaloneFileIO()
{
    // Locate the resources directory relative to the library or CWD.
    std::string base = findResourcesBase();
    m_tokens["${fonts}"]  = base + "fonts/";
    m_tokens["${glyphs}"] = base + "glyphs/";
    m_tokens["${icons}"]  = base + "icons/";
    m_tokens["${styles}"] = base + "styles/";
}

StandaloneFileIO::~StandaloneFileIO()
{
    // Background reads must not outlive the file IO (rule 13.3). Take the list
    // under the lock, then wait without the lock so a wait never blocks other
    // reads. Each read is waited for up to a time limit; one that passes it is
    // abandoned (rule 13.4) so shutdown cannot hang (rule 13.5).
    std::vector<BackgroundRead> reads;
    {
        std::lock_guard<std::mutex> lock(m_readsMutex);
        reads.swap(m_reads);
    }

    for (auto& read : reads)
    {
        if (read.thread.get_id() == std::this_thread::get_id())
        {
            // A read callback is destroying its file IO on the read's own
            // thread. The thread cannot wait for itself, so let it finish.
            read.thread.detach();
            continue;
        }
        // Each wait's time limit starts when the wait starts (rule 31.3).
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        std::unique_lock<std::mutex> signalLock(read.signal->mutex);
        const bool finished = read.signal->done_changed.wait_until(
            signalLock, deadline, [&read]() { return read.signal->done; });
        signalLock.unlock();
        if (finished)
        {
            read.thread.join();
            continue;
        }
        // The read passed its shutdown time limit. Report it on a channel that
        // survives teardown (the logger may already be gone), do not release
        // its resources, and exit at once with a non-zero status
        // (rules 31.6, 31.7, 31.8, 31.9).
        // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "StandaloneFileIO: the read of '%s' did not finish within its shutdown "
                        "time limit of 5 s; exiting\n", read.path.c_str());
        fflush(stderr);
        read.thread.detach();
        std::_Exit(70);
    }
}

std::vector<uint8_t> StandaloneFileIO::readFile(const char* path)
{
    if (!path)
        return {};

    std::string resolved = resolvePath(path);

    std::ifstream file(resolved, std::ios::binary | std::ios::ate);
    if (!file.is_open())
        return {};

    auto size = file.tellg();
    if (size <= 0)
        return {};

    file.seekg(0, std::ios::beg);
    std::vector<uint8_t> buffer(static_cast<size_t>(size));
    if (!file.read(reinterpret_cast<char*>(buffer.data()), size))
        return {};

    return buffer;
}

bool StandaloneFileIO::fileExists(const char* path)
{
    if (!path)
        return false;
    std::string resolved = resolvePath(path);
    std::error_code ec;
    return fs::exists(resolved, ec);
}

uint64_t StandaloneFileIO::getModTime(const char* path)
{
    if (!path)
        return 0;

    std::string resolved = resolvePath(path);
    std::error_code ec;
    auto ftime = fs::last_write_time(resolved, ec);
    if (ec)
        return 0;

    // Convert file_time to seconds since epoch.
    // In C++17, file_clock epoch is implementation-defined, so we approximate.
    auto duration = ftime.time_since_epoch();
    auto seconds = std::chrono::duration_cast<std::chrono::seconds>(duration);
    return static_cast<uint64_t>(seconds.count());
}

std::string StandaloneFileIO::resolvePath(const char* tokenPath)
{
    if (!tokenPath)
        return {};

    std::string path(tokenPath);

    // Replace all known tokens
    std::lock_guard<std::mutex> lock(m_mutex);
    for (const auto& [token, replacement] : m_tokens)
    {
        size_t pos = path.find(token);
        while (pos != std::string::npos)
        {
            path.replace(pos, token.length(), replacement);
            pos = path.find(token, pos + replacement.length());
        }
    }
    return path;
}

namespace {
#ifdef OVUI_FILE_IO_TEST_SEAM
// Test seam (compiled only into the file-IO test). When armed, the next read
// throws before touching the file, so the read-failure path runs without a
// huge allocation. Never built into the product library.
std::atomic<bool> g_failNextReadForTest{ false };
#endif


// Read one already-resolved path and report the cause of any failure (14.2).
// A non-regular path (such as a directory) is reported, not read, so its
// reported size cannot drive a huge allocation.
std::vector<uint8_t> readFileFromDisk(const std::string& resolved)
{
#ifdef OVUI_FILE_IO_TEST_SEAM
    if (g_failNextReadForTest.exchange(false))
        throw std::runtime_error("StandaloneFileIO: injected read failure for test");
#endif
    std::error_code ec;
    if (!std::filesystem::is_regular_file(resolved, ec))
    {
        OMNIUI_LOG_WARN("StandaloneFileIO::readFileAsync: cannot read '%s': %s", resolved.c_str(),
                        ec ? ec.message().c_str() : "not a regular file");
        return {};
    }
    std::ifstream file(resolved, std::ios::binary | std::ios::ate);
    if (!file.is_open())
    {
        const int error = errno;
        OMNIUI_LOG_WARN("StandaloneFileIO::readFileAsync: cannot open '%s': %s", resolved.c_str(),
                        std::generic_category().message(error).c_str());
        return {};
    }
    const std::streampos size = file.tellg();
    if (size <= 0)
        return {};
    file.seekg(0, std::ios::beg);
    std::vector<uint8_t> buffer(static_cast<size_t>(size));
    if (!file.read(reinterpret_cast<char*>(buffer.data()), size))
    {
        const int error = errno;
        OMNIUI_LOG_WARN("StandaloneFileIO::readFileAsync: cannot read '%s': %s", resolved.c_str(),
                        error ? std::generic_category().message(error).c_str() : "the file ended early");
        return {};
    }
    return buffer;
}

}  // namespace

#ifdef OVUI_FILE_IO_TEST_SEAM
void failNextReadForTest()
{
    g_failNextReadForTest.store(true);
}
#endif

void StandaloneFileIO::readFileAsync(const char* path, ReadFileCallback callback)
{
    if (!path || !callback)
    {
        if (callback)
            callback({});
        return;
    }

    // Resolve path now (on calling thread), then read asynchronously.
    std::string resolved = resolvePath(path);

    // Read on a background thread, then deliver the callback on the main
    // thread via the deferred queue (IUiPlatform::deferToEndOfFrame). The
    // thread waits until this read is recorded below before it runs, so a
    // callback that destroys the file IO cannot do so before the record for
    // its thread exists. The thread captures no reference to this object.
    auto signal = std::make_shared<ReadSignal>();
    std::thread thread([resolved, cb = std::move(callback), signal]() {
        {
            std::unique_lock<std::mutex> signalLock(signal->mutex);
            signal->registered_changed.wait(signalLock, [&signal]() { return signal->registered; });
        }
        std::vector<uint8_t> buffer;
        try
        {
            buffer = readFileFromDisk(resolved);
        }
        catch (const std::exception& exc)
        {
            // A failed read still delivers its empty result below.
            buffer.clear();
            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
            fprintf(stderr, "StandaloneFileIO::readFileAsync: read of '%s' failed: %s\n", resolved.c_str(),
                    exc.what());
        }

        // Deliver the callback, even when the read failed. When no platform is
        // registered it runs here, on this thread, and may destroy the file IO;
        // the signal is kept alive by this thread, so the object is never
        // touched afterwards. A throwing callback is reported, not re-run.
        try
        {
            auto* platform = PlatformRegistry::instance().platform();
            if (platform)
            {
                platform->deferToEndOfFrame([cb, data = std::move(buffer)]() mutable {
                    cb(std::move(data));
                });
            }
            else
            {
                // Fallback: no platform registered yet, call directly.
                cb(std::move(buffer));
            }
        }
        catch (const std::exception& exc)
        {
            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
            fprintf(stderr, "StandaloneFileIO::readFileAsync: result handler for '%s' failed: %s\n",
                    resolved.c_str(), exc.what());
        }

        {
            std::lock_guard<std::mutex> signalLock(signal->mutex);
            signal->done = true;
        }
        signal->done_changed.notify_all();
    });

    {
        std::lock_guard<std::mutex> lock(m_readsMutex);
        // Join and forget reads that have finished so the list does not grow.
        for (auto it = m_reads.begin(); it != m_reads.end();)
        {
            bool finished = false;
            {
                std::lock_guard<std::mutex> signalLock(it->signal->mutex);
                finished = it->signal->done;
            }
            if (finished)
            {
                it->thread.join();
                it = m_reads.erase(it);
            }
            else
            {
                ++it;
            }
        }
        m_reads.push_back(BackgroundRead{ std::move(thread), signal, resolved });
    }

    // The read is recorded and the list lock released: let the thread run.
    // After this point no member of this object is touched, so the callback
    // may safely destroy it.
    {
        std::lock_guard<std::mutex> signalLock(signal->mutex);
        signal->registered = true;
    }
    signal->registered_changed.notify_all();
}

namespace {

bool isXmlSpace(uint8_t c)
{
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

/// True when the bytes start as SVG text: after an optional UTF-8 byte order
/// mark and white space comes '<', and the text has an <svg> element, with or
/// without a namespace prefix ("<svg" or "<s:svg"). The root element of each
/// file that the SVG reader accepts is one of these; the reader checks the
/// namespace.
bool looksLikeSvg(const uint8_t* data, size_t size)
{
    size_t i = (size >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF) ? 3 : 0;
    while (i < size && isXmlSpace(data[i]))
        ++i;
    if (i >= size || data[i] != '<')
        return false;
    for (; i < size; ++i)
    {
        if (data[i] != '<')
            continue;
        // The element name ends at white space, '/', '>' or '<'.
        size_t end = i + 1;
        while (end < size && !isXmlSpace(data[end]) && data[end] != '/' && data[end] != '>' && data[end] != '<')
            ++end;
        const std::string_view name(reinterpret_cast<const char*>(data + i + 1), end - i - 1);
        if (name == "svg" || (name.size() > 4 && name.compare(name.size() - 4, 4, ":svg") == 0))
            return true;
        i = end - 1;
    }
    return false;
}

/// Decode SVG text at its own size, as an image file is decoded, so that the
/// Markdown widget shows an .svg image as ui.Image and ui.ImageWithProvider
/// show it. The caller has no file name, so a report names none.
ImageData decodeSvgImage(const uint8_t* data, size_t size)
{
#ifdef OMNIUI_HAS_SVG
    StandaloneSvgRasterizer::Bitmap bitmap;
    std::string error;
    std::vector<std::string> skipped;
    std::vector<std::string> changed;
    // The base64 decoder of a Markdown data URI gives a zero byte for each '='
    // of padding at the end (at most two). They are not part of the SVG text,
    // and the XML reader refuses text after the root element.
    size_t textSize = size;
    for (int padding = 0; padding < 2 && textSize > 0 && data[textSize - 1] == 0; ++padding)
        --textSize;
    const std::string text(reinterpret_cast<const char*>(data), textSize);
    if (!StandaloneSvgRasterizer::rasterizeToBitmapAtOwnSize(text, bitmap, error, &skipped, &changed))
    {
        OMNIUI_LOG_ERROR("SVG: cannot draw an image: %s", error.c_str());
        return {};
    }
    if (!skipped.empty())
    {
        std::string names;
        for (const std::string& name : skipped)
            names += (names.empty() ? "" : ", ") + name;
        OMNIUI_LOG_WARN("SVG: an image is drawn without these parts, which ovui does not draw: %s", names.c_str());
    }
    for (const std::string& what : changed)
        OMNIUI_LOG_WARN("SVG: an image is drawn differently from the file: %s", what.c_str());

    ImageData result;
    result.width = static_cast<int>(bitmap.width);
    result.height = static_cast<int>(bitmap.height);
    result.channels = 4;
    result.pixels = std::move(bitmap.rgba);
    return result;
#else
    (void)data;
    (void)size;
    OMNIUI_LOG_ERROR("SVG: cannot draw an image: this build has no SVG support (it was built with OMNIUI_ENABLE_SVG=OFF)");
    return {};
#endif
}

}  // namespace

ImageData StandaloneFileIO::decodeImage(const uint8_t* data, size_t size)
{
    if (!data || size == 0)
        return {};

    int w = 0, h = 0, channels = 0;
    // Request 4 channels (RGBA) regardless of source format.
    unsigned char* pixels = stbi_load_from_memory(data, static_cast<int>(size), &w, &h, &channels, 4);
    if (!pixels)
    {
        // stb_image reads no SVG. Raster bytes never get here.
        return looksLikeSvg(data, size) ? decodeSvgImage(data, size) : ImageData{};
    }

    ImageData result;
    result.width = w;
    result.height = h;
    result.channels = 4; // always RGBA after decode
    result.pixels.assign(pixels, pixels + static_cast<size_t>(w) * h * 4);
    stbi_image_free(pixels);
    return result;
}

void StandaloneFileIO::registerToken(const std::string& token, const std::string& resolvedPath)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    m_tokens[token] = resolvedPath;
}

} // namespace standalone
} // namespace ui
} // namespace omni
