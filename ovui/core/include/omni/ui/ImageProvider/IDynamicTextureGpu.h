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
#include <string>

namespace omni
{
namespace ui
{

/// Abstract interface for DynamicTextureProvider GPU operations.
///
/// In Kit mode, KitDynamicTextureGpu implements this using Kit's IRenderer and
/// rtx ResourceManager. In standalone mode, no implementation is registered
/// and DynamicTextureProvider methods use safe defaults.
///
/// Registered via PlatformRegistry::setDynamicTextureGpu().
class IDynamicTextureGpu
{
public:
    virtual ~IDynamicTextureGpu() = default;

    /// Resolve the texture URI from a user-provided texture name.
    /// Kit prepends the dynamic-texture prefix if not already present.
    /// Default (no adapter): returns textureName unchanged.
    virtual std::string resolveTextureUri(const std::string& textureName) const = 0;

    /// Whether the DynamicTextureProvider destructor should clean up image data
    /// by calling setImageData(nullptr, ...) before the base destructor runs.
    virtual bool shouldCleanupOnDestruction() const = 0;

    /// Register a managed GPU resource for the given texture URI.
    ///
    /// @param renderer  Opaque renderer pointer (m_kitRenderer from ImageProvider).
    /// @param resource  Opaque GpuResource pointer (may be nullptr for unset).
    /// @param hasPriorResource  Whether the provider currently has a managed resource.
    /// @param uri       The resolved texture URI.
    /// @return true on success.
    virtual bool setManagedResourceForUri(void* renderer,
                                          void* resource,
                                          bool hasPriorResource,
                                          const std::string& uri) = 0;

    /// Get the default GPU device mask for dynamic textures.
    /// Kit returns 0xFFFFFFFF (all devices). Return 0 for no override.
    virtual uint32_t getDefaultDeviceMask() const = 0;
};

} // namespace ui
} // namespace omni
