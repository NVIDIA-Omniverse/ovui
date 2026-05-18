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

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

namespace omni
{
namespace ui
{

class Image;

/// Abstract backend for the Image widget's texture loading and GPU resource management.
///
/// In Kit mode, KitImageBackend wraps the Kit renderer, resource manager, SVG rasterizer,
/// path resolution, and async texture upload pipeline.
/// In standalone mode, a backend can implement loading via stb_image + the IUiRenderer texture API.
class IImageBackend
{
public:
    virtual ~IImageBackend() = default;

    // -- Opaque types --------------------------------------------------------

    /// Per-texture GPU state owned by the backend. Destructor releases GPU resources.
    struct TextureHandle
    {
        virtual ~TextureHandle() = default;
    };

    // -- Texture loading -----------------------------------------------------

    /// Information passed to the completion callback when a texture is ready.
    struct TextureInfo
    {
        uint32_t width = 0;
        uint32_t height = 0;
        std::unique_ptr<TextureHandle> handle;
    };

    /// Callback that stores texture data on the Image widget.
    /// Called when texture data is available (may be on any thread).
    /// Returns true if the Image is alive and the data was stored successfully.
    using SetTextureDataFn = std::function<bool(TextureInfo)>;

    /// Callback to notify that texture loading completed (calls _setProgress).
    /// Must be called on the main / UI thread.
    using NotifyProgressFn = std::function<void()>;

    /// Result of loadTexture().
    enum class LoadResult
    {
        eSyncComplete, ///< Loading finished synchronously. Caller calls _setProgress.
        eAsyncPending, ///< Loading started asynchronously. Backend handles progress.
        eFailed        ///< Loading failed or backend not available.
    };

    /// Start loading a texture from a URL.
    ///
    /// @param sourceUrl       The image URL (may need path resolution by the backend).
    /// @param contentWidth    Widget content width in pixels (used for SVG sizing).
    /// @param contentHeight   Widget content height in pixels (used for SVG sizing).
    /// @param setTextureData  Callback to store the loaded texture data on the Image.
    /// @param notifyProgress  Callback to notify completion (_setProgress(1.0f)).
    ///                        For async loads, the backend must schedule this on the main thread.
    /// @return LoadResult indicating sync completion, async pending, or failure.
    virtual LoadResult loadTexture(const std::string& sourceUrl,
                                   float contentWidth,
                                   float contentHeight,
                                   SetTextureDataFn setTextureData,
                                   NotifyProgressFn notifyProgress) = 0;

    // -- Rendering -----------------------------------------------------------

    /// Get the ImGui-compatible texture ID for a loaded texture.
    /// @return void* suitable for ImGui::AddImage(), or nullptr if not ready.
    virtual void* getImGuiTextureId(const TextureHandle& handle) const = 0;
};

} // namespace ui
} // namespace omni
