/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "../platform/Log.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>

#include <unordered_map>

namespace omni
{
namespace ui
{

class GpuResourcesCache
{
public:
    struct RefCountedGpuResource
    {
        uint32_t counter = 0;
        ByteImageProvider* imageProvider = nullptr;
    };

    std::unordered_map<std::string, RefCountedGpuResource> gpuResources;

    ByteImageProvider* initGpuResource(const std::string& key,
                                       const uint8_t* bytes,
                                       size_t stride,
                                       UInt2 size,
                                       PixelFormat format,
                                       const ImageProviderTextureOptions& options,
                                       bool forceOverwrite = false,
                                       size_t generateMipMapLevelCount = 1)
    {
        ByteImageProvider* cachedImageProvider = nullptr;

        auto it = gpuResources.find(key);
        if (it != gpuResources.end())
        {
            if (!forceOverwrite)
            {
                OMNIUI_LOG_INFO("omni::ui::GpuResourcesCache: trying to cache an existing resource");
                return nullptr;
            }
            cachedImageProvider = it->second.imageProvider;
        }
        else
        {
            cachedImageProvider = new ByteImageProvider();
            cachedImageProvider->setTextureOptions(options);
        }

        if (generateMipMapLevelCount > 1)
        {
            cachedImageProvider->setMipMappedBytesData(bytes, size, stride, format, generateMipMapLevelCount);
        }
        else
        {
            cachedImageProvider->setBytesData(bytes, size, stride, format);
        }

        RefCountedGpuResource refCountedGpuResource = {};
        refCountedGpuResource.counter = 1;
        refCountedGpuResource.imageProvider = cachedImageProvider;
        gpuResources.insert(std::make_pair(key, refCountedGpuResource));

        return cachedImageProvider;
    }

    ByteImageProvider* initMipMappedGpuResource(const std::string& key,
                                                const uint8_t* const* mipMapBytes,
                                                size_t* mipMapStrides,
                                                size_t mipMapCount,
                                                UInt2 size,
                                                PixelFormat format,
                                                const ImageProviderTextureOptions& options,
                                                bool forceOverwrite = false)
    {
        ByteImageProvider* cachedImageProvider = nullptr;

        auto it = gpuResources.find(key);
        if (it != gpuResources.end())
        {
            if (!forceOverwrite)
            {
                OMNIUI_LOG_INFO("omni::ui::GpuResourcesCache: trying to cache an existing resource");
                return nullptr;
            }
            cachedImageProvider = it->second.imageProvider;
        }
        else
        {
            cachedImageProvider = new ByteImageProvider();
            cachedImageProvider->setTextureOptions(options);
        }

        cachedImageProvider->setMipMappedBytesData(mipMapBytes, mipMapStrides, mipMapCount, size, format);

        RefCountedGpuResource refCountedGpuResource = {};
        refCountedGpuResource.counter = 1;
        refCountedGpuResource.imageProvider = cachedImageProvider;
        gpuResources.insert(std::make_pair(key, refCountedGpuResource));

        return cachedImageProvider;
    }

    ByteImageProvider* acquireGpuResource(const std::string& key)
    {
        auto it = gpuResources.find(key);
        if (it != gpuResources.end())
        {
            it->second.counter++;
            if (!it->second.imageProvider)
            {
                OMNIUI_LOG_INFO("omni::ui::GpuResourcesCache: uninitialized cached GPU resource");
                return nullptr;
            }
            return it->second.imageProvider;
        }
        else
        {
            return nullptr;
        }
    }

    void releaseGpuResource(const std::string& key)
    {
        auto it = gpuResources.find(key);
        if (it != gpuResources.end())
        {
            if (it->second.counter == 0)
            {
                OMNIUI_LOG_INFO("omni::ui::GpuResourcesCache: trying to release uninitialized cached GPU resource");
                return;
            }

            it->second.counter--;
            if (it->second.counter == 0)
            {
                delete it->second.imageProvider;
                it->second.imageProvider = nullptr;
                gpuResources.erase(it);
            }
        }
        else
        {
            OMNIUI_LOG_INFO("omni::ui::GpuResourcesCache: trying to release non-existent cached GPU resource '%s'", key.c_str());
        }
    }
};

GpuResourcesCache& getGpuResourcesCache();

}
}
