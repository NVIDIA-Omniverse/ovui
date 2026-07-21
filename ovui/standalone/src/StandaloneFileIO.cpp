/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "StandaloneFileIO.h"

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/platform/IUiPlatform.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_NO_STDIO          // we load from memory, not FILE*
#define STBI_NO_HDR            // omni.ui doesn't need HDR float images
#include <stb_image.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <future>
#include <iterator>

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
    // thread via the deferred queue (IUiPlatform::deferToEndOfFrame).
    std::thread([resolved, cb = std::move(callback)]() {
        std::ifstream file(resolved, std::ios::binary | std::ios::ate);
        std::vector<uint8_t> buffer;
        if (file.is_open())
        {
            auto size = file.tellg();
            if (size > 0)
            {
                file.seekg(0, std::ios::beg);
                buffer.resize(static_cast<size_t>(size));
                if (!file.read(reinterpret_cast<char*>(buffer.data()), size))
                    buffer.clear();
            }
        }

        // Deliver callback on the main thread via the deferred queue.
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
    }).detach();
}

ImageData StandaloneFileIO::decodeImage(const uint8_t* data, size_t size)
{
    if (!data || size == 0)
        return {};

    int w = 0, h = 0, channels = 0;
    // Request 4 channels (RGBA) regardless of source format.
    unsigned char* pixels = stbi_load_from_memory(data, static_cast<int>(size), &w, &h, &channels, 4);
    if (!pixels)
        return {};

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
