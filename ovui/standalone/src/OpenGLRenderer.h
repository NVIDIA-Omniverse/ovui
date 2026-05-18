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

#include <omni/ui/platform/IUiRenderer.h>

#include <mutex>
#include <unordered_map>

namespace omni {
namespace ui {
namespace standalone {

/// Standalone IUiRenderer implementation using OpenGL 3.3 core profile.
/// TextureHandle is a GLuint cast to uint64_t.
class OpenGLRenderer final : public IUiRenderer
{
public:
    OpenGLRenderer() = default;
    ~OpenGLRenderer() override;

    // -- Texture lifecycle --
    TextureHandle createTexture(int width, int height, TextureFormat format,
                                const void* data) override;
    void updateTexture(TextureHandle handle, const void* data, size_t size) override;
    void destroyTexture(TextureHandle handle) override;
    void* getImGuiTextureId(TextureHandle handle) override;

    // -- Font atlas --
    TextureHandle uploadFontAtlas(const unsigned char* pixels, int width,
                                  int height) override;

    // -- Frame lifecycle --
    void beginFrame() override;
    void endFrame() override;

private:
    struct TextureInfo
    {
        int width = 0;
        int height = 0;
        TextureFormat format = TextureFormat::eRGBA8;
    };

    std::mutex m_mutex;
    std::unordered_map<uint64_t, TextureInfo> m_textures;
    TextureHandle m_fontAtlasHandle = kInvalidTexture;
};

} // namespace standalone
} // namespace ui
} // namespace omni
