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

#include "TwemojiAtlas.h"

#include <stb_image.h>

#include <glad/glad.h>

#include <cstring>
#include <fstream>
#include <sstream>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

uint64_t parseManifestKey(const std::string& key)
{
    std::vector<uint32_t> cps;
    std::istringstream ss(key);
    std::string part;
    while (std::getline(ss, part, '-'))
    {
        uint32_t cp = static_cast<uint32_t>(std::stoul(part, nullptr, 16));
        cps.push_back(cp);
    }
    return TwemojiAtlas::hashSequence(cps.data(), static_cast<int>(cps.size()));
}

int parseJsonInt(const std::string& json, const std::string& key, int defaultVal)
{
    std::string needle = "\"" + key + "\":";
    auto pos = json.find(needle);
    if (pos == std::string::npos)
        return defaultVal;
    pos += needle.size();
    while (pos < json.size() && json[pos] == ' ')
        ++pos;
    return std::atoi(json.c_str() + pos);
}

// Parse the compact manifest: {"glyphs":{"1f600":{"row":0,"col":0},...}}
bool parseGlyphs(const std::string& json, int cols,
                 std::unordered_map<uint64_t, uint32_t>& out)
{
    auto glyphsPos = json.find("\"glyphs\":{");
    if (glyphsPos == std::string::npos)
        return false;

    size_t i = glyphsPos + 10; // skip past "glyphs":{
    while (i < json.size())
    {
        if (json[i] == '}')
            break;

        // Find key: "codepoint":
        auto kStart = json.find('"', i);
        if (kStart == std::string::npos)
            break;
        auto kEnd = json.find('"', kStart + 1);
        if (kEnd == std::string::npos)
            break;
        std::string key = json.substr(kStart + 1, kEnd - kStart - 1);

        // Find the value object {..}
        auto vStart = json.find('{', kEnd);
        if (vStart == std::string::npos)
            break;
        auto vEnd = json.find('}', vStart);
        if (vEnd == std::string::npos)
            break;
        std::string val = json.substr(vStart, vEnd - vStart + 1);

        int row = parseJsonInt(val, "row", -1);
        int col = parseJsonInt(val, "col", -1);
        if (row >= 0 && col >= 0)
        {
            uint64_t hash = parseManifestKey(key);
            out[hash] = static_cast<uint32_t>(row * cols + col);
        }

        i = vEnd + 1;
        if (i < json.size() && json[i] == ',')
            ++i;
    }
    return true;
}

} // namespace

uint64_t TwemojiAtlas::hashSequence(const uint32_t* codepoints, int count)
{
    if (count == 1)
        return codepoints[0];
    uint64_t h = 0xcbf29ce484222325ULL;
    for (int i = 0; i < count; ++i)
    {
        h ^= codepoints[i];
        h *= 0x100000001b3ULL;
    }
    return h;
}

bool TwemojiAtlas::init(const char* atlasPath, const char* manifestPath)
{
    // The emoji atlas is uploaded via raw OpenGL. When ovui runs on a
    // non-GL backend (Vulkan headless) glad is never loaded, so the GL
    // entry points are still NULL and calling them dereferences address 0.
    // Detect that here and bail cleanly — MarkdownWidget treats a failed
    // init() as "no emoji atlas" and renders without emoji glyphs.
    if (glad_glGenTextures == nullptr)
        return false;

    std::ifstream mf(manifestPath);
    if (!mf.is_open())
        return false;

    std::string json((std::istreambuf_iterator<char>(mf)), std::istreambuf_iterator<char>());

    m_cellSize = parseJsonInt(json, "cellSize", 32);
    m_atlasSize = parseJsonInt(json, "atlasSize", 2048);
    m_cols = m_atlasSize / m_cellSize;

    if (!parseGlyphs(json, m_cols, m_codepointToIndex))
        return false;

    std::ifstream af(atlasPath, std::ios::binary | std::ios::ate);
    if (!af.is_open())
        return false;
    auto size = af.tellg();
    af.seekg(0);
    std::vector<uint8_t> buf(static_cast<size_t>(size));
    af.read(reinterpret_cast<char*>(buf.data()), size);

    int w = 0, h = 0, ch = 0;
    unsigned char* pixels = stbi_load_from_memory(buf.data(), static_cast<int>(buf.size()), &w, &h, &ch, 4);
    if (!pixels)
        return false;

    GLuint tex = 0;
    glGenTextures(1, &tex);
    if (tex == 0)
    {
        stbi_image_free(pixels);
        return false;
    }

    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glBindTexture(GL_TEXTURE_2D, 0);

    stbi_image_free(pixels);

    m_texId = static_cast<ImTextureID>(tex);
    m_loaded = true;
    return true;
}

void TwemojiAtlas::destroy()
{
    if (m_texId != 0)
    {
        GLuint tex = static_cast<GLuint>(m_texId);
        glDeleteTextures(1, &tex);
        m_texId = 0;
    }
    m_codepointToIndex.clear();
    m_loaded = false;
}

bool TwemojiAtlas::lookup(uint64_t key, ImVec2& uv0, ImVec2& uv1) const
{
    auto it = m_codepointToIndex.find(key);
    if (it == m_codepointToIndex.end())
        return false;

    uint32_t idx = it->second;
    int row = static_cast<int>(idx / m_cols);
    int col = static_cast<int>(idx % m_cols);

    float invSize = 1.0f / static_cast<float>(m_atlasSize);
    float x0 = col * m_cellSize * invSize;
    float y0 = row * m_cellSize * invSize;
    float x1 = x0 + m_cellSize * invSize;
    float y1 = y0 + m_cellSize * invSize;

    uv0 = ImVec2(x0, y0);
    uv1 = ImVec2(x1, y1);
    return true;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
