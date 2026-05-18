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

#include <cstddef>
#include <cstdint>

namespace omni {
namespace ui {

/// Opaque handle to a GPU texture managed by the renderer backend.
/// In standalone (OpenGL): this is a GLuint cast to uint64_t.
/// In Kit: an index into the adapter's internal texture map.
using TextureHandle = uint64_t;

/// Sentinel value representing an invalid / uninitialized texture.
constexpr TextureHandle kInvalidTexture = 0;

/// Pixel format hint for createTexture().
enum class TextureFormat : uint32_t
{
    eRGBA8 = 0, ///< 4 channels, 8 bits each, unsigned normalized.
    eR8,        ///< Single channel, 8 bits, unsigned normalized (font atlas).
};

/// Abstract renderer interface replacing IRenderer / IImGuiRenderer.
///
/// In Kit mode, KitRendererAdapter wraps IRenderer + IImGuiRenderer and
/// maintains an internal TextureHandle -> KitTextureState map.
/// In standalone mode, OpenGL 3.3 core is used directly.
class IUiRenderer
{
public:
    virtual ~IUiRenderer() = default;

    // -- Texture lifecycle --------------------------------------------------

    /// Create a GPU texture and optionally upload initial data.
    /// @param width   Texture width in pixels.
    /// @param height  Texture height in pixels.
    /// @param format  Pixel format.
    /// @param data    Initial pixel data (may be nullptr for an empty texture).
    /// @return A valid TextureHandle, or kInvalidTexture on failure.
    virtual TextureHandle createTexture(int width, int height, TextureFormat format,
                                        const void* data) = 0;

    /// Upload new pixel data to an existing texture (full replace).
    /// The data must match the texture's dimensions and format.
    virtual void updateTexture(TextureHandle handle, const void* data, size_t size) = 0;

    /// Destroy a texture and release GPU resources.
    /// Passing kInvalidTexture is a safe no-op.
    virtual void destroyTexture(TextureHandle handle) = 0;

    /// Convert a TextureHandle to the ImTextureID expected by ImGui draw commands.
    /// In OpenGL: (void*)(intptr_t)handle. In Kit: the ImGui-renderer-specific ID.
    virtual void* getImGuiTextureId(TextureHandle handle) = 0;

    // -- Font atlas ---------------------------------------------------------

    /// Upload a font atlas bitmap produced by ImGui.
    /// @param pixels  Alpha-only (1 byte per pixel) or RGBA pixel data.
    /// @param width   Atlas width.
    /// @param height  Atlas height.
    /// @return The texture handle for the atlas (set on ImGui IO.Fonts->TexID).
    virtual TextureHandle uploadFontAtlas(const unsigned char* pixels, int width,
                                          int height) = 0;

    // -- Initialization ------------------------------------------------------

    /// Block until the renderer backend is fully initialized.
    /// In Kit mode this waits for IRenderer::waitForInit(); standalone is a no-op.
    virtual void waitForInit() {}

    // -- Frame lifecycle ----------------------------------------------------

    /// Called once per frame before any ImGui drawing.
    virtual void beginFrame() = 0;

    /// Called once per frame after ImGui::Render() to submit draw data to the GPU.
    virtual void endFrame() = 0;
};

} // namespace ui
} // namespace omni
