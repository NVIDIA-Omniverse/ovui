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

#include <functional>
#include <string>
#include <unordered_map>
#include <utility>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct ResolvedImage
{
    ImTextureID textureId = 0;
    ImVec2 size = {0, 0};
    ImVec2 uv0 = {0, 0};
    ImVec2 uv1 = {1, 1};
    bool ready = false;
};

class ImageResolver
{
public:
    virtual ~ImageResolver() = default;
    virtual ResolvedImage resolve(const std::string& src) = 0;
    virtual void tick() {}
};

class StbImageResolver : public ImageResolver
{
public:
    using UrlProvider = std::function<std::string(const std::string&)>;

private:
    struct CacheEntry
    {
        ImTextureID texId = 0;
        ImVec2 size = {0, 0};
        bool valid = false;
    };
    std::unordered_map<std::string, CacheEntry> m_cache;
    UrlProvider m_urlProvider;

    ResolvedImage _loadFromMemory(const std::string& key, const unsigned char* data, size_t len);
    ResolvedImage _loadFromFile(const std::string& path);

public:
    ~StbImageResolver() override;
    void setUrlProvider(UrlProvider provider) { m_urlProvider = std::move(provider); }
    ResolvedImage resolve(const std::string& src) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
