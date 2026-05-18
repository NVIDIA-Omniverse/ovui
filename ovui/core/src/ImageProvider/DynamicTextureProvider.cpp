/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/ImageProvider/DynamicTextureProvider.h>
#include <omni/ui/ImageProvider/IDynamicTextureGpu.h>
#include "../platform/PlatformRegistry.h"
#include "../platform/Log.h"

namespace omni
{
namespace ui
{

DynamicTextureProvider::DynamicTextureProvider(const std::string& textureName)
{
    auto* dtGpu = PlatformRegistry::instance().dynamicTextureGpu();
    m_textureUri = dtGpu ? dtGpu->resolveTextureUri(textureName) : textureName;
}

DynamicTextureProvider::~DynamicTextureProvider()
{
    auto* dtGpu = PlatformRegistry::instance().dynamicTextureGpu();
    if (dtGpu && dtGpu->shouldCleanupOnDestruction())
    {
        this->setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
    }
}

bool DynamicTextureProvider::_setManagedResource(GpuResource* rpRsrc)
{
    auto* dtGpu = PlatformRegistry::instance().dynamicTextureGpu();
    if (dtGpu)
    {
        dtGpu->setManagedResourceForUri(
            m_kitRenderer, reinterpret_cast<void*>(rpRsrc), m_managedRsrc != nullptr, m_textureUri);
    }

    return ByteImageProvider::_setManagedResource(rpRsrc);
}

bool DynamicTextureProvider::mergeTextureOptions(ImageProvider::TextureOptions& textureOptions) const
{
    auto* dtGpu = PlatformRegistry::instance().dynamicTextureGpu();
    if (dtGpu)
    {
        uint32_t mask = dtGpu->getDefaultDeviceMask();
        if (mask != 0 && textureOptions.gpuDeviceMask == 0)
        {
            textureOptions.gpuDeviceMask = mask;
        }
    }
    return true;
}

}
}
