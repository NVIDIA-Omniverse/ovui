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

    ImTextureID textureId() const { return m_texId; }
    bool isLoaded() const { return m_loaded; }

    static uint64_t hashSequence(const uint32_t* codepoints, int count);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
