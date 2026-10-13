/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Api.h>

#include <imgui/imgui.h>

#include <cstdint>
#include <string>
#include <unordered_map>

OMNIUI_NAMESPACE_OPEN_SCOPE

class TwemojiAtlas
{
    ImTextureID m_texId = 0;
    int m_atlasSize = 2048;
    int m_cellSize = 32;
    int m_cols = 64;
    std::unordered_map<uint64_t, uint32_t> m_codepointToIndex;
    bool m_loaded = false;

public:
    ~TwemojiAtlas() { destroy(); }

    bool init(const char* atlasPath, const char* manifestPath);
    void destroy();

    bool hasGlyph(uint64_t key) const
    {
        return m_codepointToIndex.find(key) != m_codepointToIndex.end();
    }

    bool lookup(uint64_t key, ImVec2& uv0, ImVec2& uv1) const;

    ImTextureID textureId() const;
    bool isLoaded() const { return m_loaded; }

    static uint64_t hashSequence(const uint32_t* codepoints, int count);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
