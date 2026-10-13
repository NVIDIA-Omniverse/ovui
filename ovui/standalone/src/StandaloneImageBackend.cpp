/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "StandaloneImageBackend.h"

#include "StandaloneRasterImageLoader.h"
#include "platform/Log.h"

#include <algorithm>
#include <cctype>
#include <fstream>

namespace omni {
namespace ui {
namespace standalone {

namespace {

/// GPU state of one loaded texture. Each handle is one loader instance, so the
/// loader keeps the shared texture alive until the last handle is destroyed.
struct RasterTextureHandle final : IImageBackend::TextureHandle
{
    std::weak_ptr<StandaloneRasterImageLoader> loader;
    void* imGuiReference = nullptr;

    ~RasterTextureHandle() override
    {
        if (auto l = loader.lock())
        {
            l->releaseLoad(this);
        }
    }
};

int hexValue(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

bool startsWithNoCase(const std::string& s, const char* prefix)
{
    size_t n = std::char_traits<char>::length(prefix);
    if (s.size() < n)
        return false;
    for (size_t i = 0; i < n; ++i)
    {
        if (std::tolower(static_cast<unsigned char>(s[i])) != prefix[i])
            return false;
    }
    return true;
}

/// True for "scheme://..." where the scheme is two or more characters, so a
/// Windows drive path such as "C://dir" is not taken as a URL.
bool hasUrlScheme(const std::string& s)
{
    size_t pos = s.find("://");
    if (pos == std::string::npos || pos < 2)
        return false;
    return std::all_of(s.begin(), s.begin() + pos, [](char c) {
        return std::isalnum(static_cast<unsigned char>(c)) || c == '+' || c == '-' || c == '.';
    });
}

bool hasSvgExtension(const std::string& path)
{
    if (path.size() < 4)
        return false;
    std::string ext = path.substr(path.size() - 4);
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return std::tolower(c); });
    return ext == ".svg";
}

} // anonymous namespace

StandaloneImageBackend::StandaloneImageBackend(std::shared_ptr<StandaloneRasterImageLoader> loader)
    : m_loader(loader)
{
}

std::string StandaloneImageBackend::urlToLocalPath(const std::string& sourceUrl)
{
    if (!startsWithNoCase(sourceUrl, "file://"))
    {
        return sourceUrl;
    }

    std::string path = sourceUrl.substr(7);
    if (startsWithNoCase(path, "localhost/"))
    {
        path = path.substr(9);
    }

    std::string decoded;
    decoded.reserve(path.size());
    for (size_t i = 0; i < path.size(); ++i)
    {
        int hi = 0, lo = 0;
        if (path[i] == '%' && i + 2 < path.size() && (hi = hexValue(path[i + 1])) >= 0 &&
            (lo = hexValue(path[i + 2])) >= 0)
        {
            decoded.push_back(static_cast<char>(hi * 16 + lo));
            i += 2;
        }
        else
        {
            decoded.push_back(path[i]);
        }
    }

    // file:///C:/dir/a.png -> C:/dir/a.png
    if (decoded.size() >= 3 && decoded[0] == '/' && std::isalpha(static_cast<unsigned char>(decoded[1])) &&
        decoded[2] == ':')
    {
        decoded.erase(0, 1);
    }

    return decoded;
}

void StandaloneImageBackend::_logFailure(const std::string& sourceUrl, const char* reason)
{
    {
        std::lock_guard<std::mutex> lock(m_loggedMutex);
        if (!m_loggedUrls.insert(sourceUrl).second)
        {
            return;
        }
    }
    OMNIUI_LOG_ERROR("ui.Image: cannot load '%s': %s", sourceUrl.c_str(), reason);
}

IImageBackend::LoadResult StandaloneImageBackend::loadTexture(const std::string& sourceUrl,
                                                              float /*contentWidth*/,
                                                              float /*contentHeight*/,
                                                              SetTextureDataFn setTextureData,
                                                              NotifyProgressFn /*notifyProgress*/)
{
    auto loader = m_loader.lock();
    if (!loader)
    {
        _logFailure(sourceUrl, "no raster image loader is available for the active render backend");
        return LoadResult::eFailed;
    }

    if (!startsWithNoCase(sourceUrl, "file://") && hasUrlScheme(sourceUrl))
    {
        _logFailure(sourceUrl, "only local file paths and file:// URLs are supported");
        return LoadResult::eFailed;
    }

    const std::string path = urlToLocalPath(sourceUrl);
    if (hasSvgExtension(path))
    {
        _logFailure(sourceUrl, "SVG files are not supported");
        return LoadResult::eFailed;
    }

    auto handle = std::make_unique<RasterTextureHandle>();
    handle->loader = loader;

    auto result = loader->beginLoad(handle.get(), path);
    if (result.status == IRasterImageLoader::LoadResult::eFailed || !result.imGuiReference)
    {
        _logFailure(sourceUrl,
                    std::ifstream(path, std::ios::binary) ? "the file is not a supported raster image"
                                                          : "the file does not exist or cannot be read");
        return LoadResult::eFailed;
    }

    handle->imGuiReference = result.imGuiReference;

    TextureInfo info;
    info.width = result.imageSize.x;
    info.height = result.imageSize.y;
    info.handle = std::move(handle);
    setTextureData(std::move(info));
    return LoadResult::eSyncComplete;
}

void* StandaloneImageBackend::getImGuiTextureId(const TextureHandle& handle) const
{
    return static_cast<const RasterTextureHandle&>(handle).imGuiReference;
}

} // namespace standalone
} // namespace ui
} // namespace omni
