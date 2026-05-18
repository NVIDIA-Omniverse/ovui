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

#define STB_IMAGE_IMPLEMENTATION
#define STBI_NO_STDIO
#define STBI_NO_HDR
#include <stb_image.h>

#include "ImageResolver.h"

#include <glad/glad.h>

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
    // Same guard as TwemojiAtlas::init: the markdown image upload path uses
    // raw OpenGL, but glad is only loaded by GL-backed platforms. Under the
    // Vulkan headless backend glad_glGenTextures is NULL and the call below
    // would jump to address 0. Bail with a 0 texture id; StbImageResolver
    // marks the cache entry invalid and the markdown widget renders without
    // the image.
    if (glad_glGenTextures == nullptr)
        return 0;
    GLuint tex = 0;
    glGenTextures(1, &tex);
    if (tex == 0)
        return 0;
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glBindTexture(GL_TEXTURE_2D, 0);
    return static_cast<ImTextureID>(tex);
}

void deleteTexture(ImTextureID id)
{
    if (id == 0)
        return;
    GLuint tex = static_cast<GLuint>(id);
    glDeleteTextures(1, &tex);
}

} // namespace

StbImageResolver::~StbImageResolver()
{
    for (auto& [key, entry] : m_cache)
        deleteTexture(entry.texId);
}

ResolvedImage StbImageResolver::_loadFromMemory(const std::string& key, const unsigned char* data, size_t len)
{
    int w = 0, h = 0, channels = 0;
    unsigned char* pixels = stbi_load_from_memory(data, static_cast<int>(len), &w, &h, &channels, 4);
    if (!pixels)
    {
        m_cache[key] = {0, {0, 0}, false};
        return {};
    }

    ImTextureID texId = uploadRGBA(pixels, w, h);
    stbi_image_free(pixels);

    CacheEntry entry;
    entry.texId = texId;
    entry.size = {static_cast<float>(w), static_cast<float>(h)};
    entry.valid = (texId != 0);
    m_cache[key] = entry;

    return {entry.texId, entry.size, {0, 0}, {1, 1}, entry.valid};
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
        return {it->second.texId, it->second.size, {0, 0}, {1, 1}, it->second.valid};

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
