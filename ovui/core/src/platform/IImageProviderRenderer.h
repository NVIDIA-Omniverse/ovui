/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/platform/Types.h>
#include <cstdint>

namespace omni
{
namespace ui
{

/// Abstract interface for renderer operations used by ImageProvider.
///
/// In Kit mode, KitImageProviderRenderer wraps omni::kit::renderer::IRenderer
/// to handle GPU resource management and present-thread queries.
/// In standalone mode, the default (null) implementation causes all
/// GPU-resource methods to be no-ops, which is correct since standalone
/// does not use GpuResource-based image data paths.
class IImageProviderRenderer
{
public:
    virtual ~IImageProviderRenderer() = default;

    /// Acquire the renderer context. Called during ImageProvider construction.
    /// Returns an opaque pointer stored as m_kitRenderer.
    virtual void* acquireRenderer() = 0;

    /// Check if the renderer's present thread is enabled.
    virtual bool isPresentThreadEnabled(void* renderer) = 0;

    /// What the renderer knows about one presentation key.
    enum class PresentationKeyState
    {
        /// The renderer keeps no per-key state (a renderer that is not updated).
        eUnknown,
        /// The renderer replaces the key with a drawable before its back end reads the draw data.
        eMapped,
        /// The key has no drawable: never notified, retired, or sent with an invalid frame.
        eUnmapped,
    };

    /// Report the state of one key. ImageProvider does not return an unmapped key and uses the
    /// texture reference instead, so a live feed of another provider cannot keep a dead key in use.
    /// For an unknown key the provider keeps key mode, so a renderer that is not updated keeps its
    /// valid presentation. The draw guard of the standalone back ends removes every key command
    /// whose state is not eMapped, because those back ends read a texture id as a texture name or
    /// as a Vulkan descriptor and have no key table.
    virtual PresentationKeyState presentationKeyState(void* renderer, uint64_t key)
    {
        (void)renderer;
        (void)key;
        return PresentationKeyState::eUnknown;
    }

    /// Result of ensuring a GPU resource on the target device with texture info.
    struct EnsureResourceResult
    {
        void* resource = nullptr;
        void* textureHandlePtr = nullptr;
        uint32_t width = 0;
        uint32_t height = 0;
        PixelFormat format = PixelFormat::eUnknown;
    };

    /// Ensure a GPU resource on the target device and extract texture info.
    /// Used by setImageData(GpuResource&, uint64_t).
    virtual EnsureResourceResult ensureResourceWithTextureInfo(
        void* renderer, void* rpRsrc, uint32_t id) = 0;

    /// Ensure a GPU resource on the target device (simple, no texture info extraction).
    /// Used by _setManagedResource for retaining resources.
    virtual void* ensureResourceSimple(
        void* renderer, void* rpRsrc, uint32_t id) = 0;

    /// Release a managed GPU resource.
    virtual void releaseResource(void* renderer, void* managedRsrc) = 0;
    virtual bool getMetadataDisplayWindow(void*, DisplayWindowRect&) { return false; }
};

} // namespace ui
} // namespace omni
