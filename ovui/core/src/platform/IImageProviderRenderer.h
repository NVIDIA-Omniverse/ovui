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
};

} // namespace ui
} // namespace omni
