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

#include "OpenGLRenderer.h"

#include <glad/glad.h>

#include <cstdint>
#include <cstdio>

namespace omni {
namespace ui {
namespace standalone {

OpenGLRenderer::~OpenGLRenderer()
{
    // Destroy all remaining textures
    for (auto& [handle, info] : m_textures)
    {
        GLuint tex = static_cast<GLuint>(handle);
        glDeleteTextures(1, &tex);
    }
    m_textures.clear();
}

TextureHandle OpenGLRenderer::createTexture(int width, int height, TextureFormat format,
                                             const void* data)
{
    GLuint tex = 0;
    glGenTextures(1, &tex);
    if (tex == 0)
    {
        fprintf(stderr, "OpenGLRenderer::createTexture: glGenTextures failed\n");
        return kInvalidTexture;
    }

    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    GLenum glInternalFormat, glFormat;
    if (format == TextureFormat::eR8)
    {
        glInternalFormat = GL_R8;
        glFormat = GL_RED;
        // Swizzle so that R channel shows up in alpha for font rendering
        GLint swizzleMask[] = {GL_ONE, GL_ONE, GL_ONE, GL_RED};
        glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzleMask);
    }
    else // eRGBA8
    {
        glInternalFormat = GL_RGBA8;
        glFormat = GL_RGBA;
    }

    glTexImage2D(GL_TEXTURE_2D, 0, glInternalFormat, width, height, 0,
                 glFormat, GL_UNSIGNED_BYTE, data);

    glBindTexture(GL_TEXTURE_2D, 0);

    TextureHandle handle = static_cast<TextureHandle>(tex);

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_textures[handle] = {width, height, format};
    }

    return handle;
}

void OpenGLRenderer::updateTexture(TextureHandle handle, const void* data, size_t size)
{
    if (handle == kInvalidTexture || !data)
        return;

    TextureInfo info;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto it = m_textures.find(handle);
        if (it == m_textures.end())
        {
            fprintf(stderr, "OpenGLRenderer::updateTexture: unknown handle %llu\n",
                    (unsigned long long)handle);
            return;
        }
        info = it->second;
    }

    GLuint tex = static_cast<GLuint>(handle);
    GLenum glFormat = (info.format == TextureFormat::eR8) ? GL_RED : GL_RGBA;

    glBindTexture(GL_TEXTURE_2D, tex);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, info.width, info.height,
                    glFormat, GL_UNSIGNED_BYTE, data);
    glBindTexture(GL_TEXTURE_2D, 0);

    (void)size; // size is for validation; we trust width*height*channels
}

void OpenGLRenderer::destroyTexture(TextureHandle handle)
{
    if (handle == kInvalidTexture)
        return;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_textures.erase(handle);
    }

    GLuint tex = static_cast<GLuint>(handle);
    glDeleteTextures(1, &tex);
}

void* OpenGLRenderer::getImGuiTextureId(TextureHandle handle)
{
    return reinterpret_cast<void*>(static_cast<intptr_t>(handle));
}

TextureHandle OpenGLRenderer::uploadFontAtlas(const unsigned char* pixels, int width, int height)
{
    // Destroy previous font atlas if any
    if (m_fontAtlasHandle != kInvalidTexture)
    {
        destroyTexture(m_fontAtlasHandle);
        m_fontAtlasHandle = kInvalidTexture;
    }

    // Upload as RGBA8 (ImGui provides RGBA data via GetTexDataAsRGBA32)
    m_fontAtlasHandle = createTexture(width, height, TextureFormat::eRGBA8, pixels);
    return m_fontAtlasHandle;
}

void OpenGLRenderer::beginFrame()
{
    // No-op for OpenGL. The imgui_impl_opengl3 backend handles frame setup.
}

void OpenGLRenderer::endFrame()
{
    // No-op for OpenGL. Rendering is done via ImGui_ImplOpenGL3_RenderDrawData.
}

} // namespace standalone
} // namespace ui
} // namespace omni
