/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/platform/IUiFileIO.h>
#include <omni/ui/platform/IUiRenderer.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include "ImageResolver.h"

#include <cstring>
#include <fstream>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

static const uint8_t kBase64Decode[256] = {
    // clang-format off
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255, 62,255,255,255, 63,
     52, 53, 54, 55, 56, 57, 58, 59, 60, 61,255,255,255,  0,255,255,
    255,  0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14,
     15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,255,255,255,255,255,
    255, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
     41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,
    // clang-format on
};

std::vector<uint8_t> base64Decode(const char* begin, size_t len)
{
    std::vector<uint8_t> out;
    out.reserve(len * 3 / 4);
    uint32_t accum = 0;
    int bits = 0;
    for (size_t i = 0; i < len; ++i)
    {
        uint8_t v = kBase64Decode[static_cast<uint8_t>(begin[i])];
        if (v == 255)
            continue;
        accum = (accum << 6) | v;
        bits += 6;
        if (bits >= 8)
        {
            bits -= 8;
            out.push_back(static_cast<uint8_t>((accum >> bits) & 0xFF));
        }
    }
    return out;
}

ImTextureID uploadRGBA(const uint8_t* pixels, int w, int h)
{
    auto* renderer = PlatformRegistry::instance().renderer();
    return renderer ? renderer->createTexture(w, h, TextureFormat::eRGBA8, pixels) : 0;
}

void deleteTexture(ImTextureID id)
{
    if (id == 0)
        return;
    if (auto* renderer = PlatformRegistry::instance().renderer())
        renderer->destroyTexture(id);
}

ImTextureID drawTextureId(ImTextureID handle)
{
    auto* renderer = PlatformRegistry::instance().renderer();
    return renderer ? reinterpret_cast<ImTextureID>(renderer->getImGuiTextureId(handle)) : 0;
}

} // namespace

StbImageResolver::~StbImageResolver()
{
    for (auto& [key, entry] : m_cache)
        deleteTexture(entry.texId);
}

ResolvedImage StbImageResolver::_loadFromMemory(const std::string& key, const unsigned char* data, size_t len)
{
    auto* fileIO = PlatformRegistry::instance().fileIO();
    auto image = fileIO ? fileIO->decodeImage(data, len) : ImageData{};
    int w = image.width, h = image.height;
    const auto* pixels = image.pixels.empty() ? nullptr : image.pixels.data();
    if (!pixels)
    {
        m_cache[key] = {0, {0, 0}, false};
        return {};
    }

    ImTextureID texId = uploadRGBA(pixels, w, h);

    CacheEntry entry;
    entry.texId = texId;
    entry.size = {static_cast<float>(w), static_cast<float>(h)};
    entry.valid = (texId != 0);
    m_cache[key] = entry;

    auto drawId = drawTextureId(entry.texId);
    return {drawId, entry.size, {0, 0}, {1, 1}, entry.valid && drawId != 0};
}

ResolvedImage StbImageResolver::_loadFromFile(const std::string& path)
{
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file.is_open())
    {
        m_cache[path] = {0, {0, 0}, false};
        return {};
    }
    auto size = file.tellg();
    file.seekg(0);
    std::vector<uint8_t> buf(static_cast<size_t>(size));
    file.read(reinterpret_cast<char*>(buf.data()), size);
    return _loadFromMemory(path, buf.data(), buf.size());
}

ResolvedImage StbImageResolver::resolve(const std::string& src)
{
    std::string resolved = src;
    if (m_urlProvider)
    {
        std::string candidate = m_urlProvider(src);
        if (!candidate.empty())
            resolved = std::move(candidate);
    }

    if (resolved.compare(0, 7, "file://") == 0)
        resolved = resolved.substr(7);
    else if (resolved.compare(0, 5, "file:") == 0)
        resolved = resolved.substr(5);

    auto it = m_cache.find(resolved);
    if (it != m_cache.end())
    {
        auto drawId = drawTextureId(it->second.texId);
        return {drawId, it->second.size, {0, 0}, {1, 1}, it->second.valid && drawId != 0};
    }

    if (resolved.compare(0, 11, "data:image/") == 0)
    {
        auto pos = resolved.find("base64,");
        if (pos != std::string::npos)
        {
            const char* b64Start = resolved.data() + pos + 7;
            size_t b64Len = resolved.size() - (pos + 7);
            auto decoded = base64Decode(b64Start, b64Len);
            return _loadFromMemory(resolved, decoded.data(), decoded.size());
        }
    }

    return _loadFromFile(resolved);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
