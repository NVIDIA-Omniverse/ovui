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

#include "StandaloneRasterImageLoader.h"

#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>

// stb_image is compiled with STBI_NO_STDIO in StandaloneFileIO.cpp, so
// stbi_load (file-path variant) is not available. Read the file into a buffer
// ourselves and use stbi_load_from_memory instead.
#include <stb_image.h>

#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

namespace {

/// Generate box-filtered mip chain from an RGBA8 base image.
/// Returns a vector of pointers (index 0 is the original base) and fills strides.
/// The base pointer is copied into slot 0; subsequent slots are newly allocated
/// and must be freed by the caller via ::free().
void generateMipChain(const uint8_t* basePixels,
                      uint32_t width, uint32_t height,
                      size_t mipCount,
                      std::vector<const uint8_t*>& outBuffers,
                      std::vector<size_t>& outStrides)
{
    outBuffers.resize(mipCount);
    outStrides.resize(mipCount);
    outBuffers[0] = basePixels;
    outStrides[0] = static_cast<size_t>(width) * 4;

    uint32_t prevW = width;
    uint32_t prevH = height;
    const uint8_t* prev = basePixels;

    for (size_t mip = 1; mip < mipCount; ++mip)
    {
        uint32_t w = std::max<uint32_t>(prevW / 2, 1);
        uint32_t h = std::max<uint32_t>(prevH / 2, 1);
        uint8_t* mipData = static_cast<uint8_t*>(::malloc(static_cast<size_t>(w) * h * 4));
        if (!mipData)
        {
            outBuffers.resize(mip);
            outStrides.resize(mip);
            break;
        }

        for (uint32_t y = 0; y < h; ++y)
        {
            uint32_t y0 = y * 2;
            uint32_t y1 = std::min(y0 + 1, prevH - 1);
            for (uint32_t x = 0; x < w; ++x)
            {
                uint32_t x0 = x * 2;
                uint32_t x1 = std::min(x0 + 1, prevW - 1);
                for (uint32_t c = 0; c < 4; ++c)
                {
                    int sum = prev[(y0 * prevW + x0) * 4 + c]
                            + prev[(y0 * prevW + x1) * 4 + c]
                            + prev[(y1 * prevW + x0) * 4 + c]
                            + prev[(y1 * prevW + x1) * 4 + c];
                    mipData[(y * w + x) * 4 + c] = static_cast<uint8_t>(sum / 4);
                }
            }
        }

        outBuffers[mip] = mipData;
        outStrides[mip] = static_cast<size_t>(w) * 4;
        prev = mipData;
        prevW = w;
        prevH = h;
    }
}

} // anonymous namespace

StandaloneRasterImageLoader::~StandaloneRasterImageLoader()
{
    // Release every cached GPU state before IByteImageGpu goes away.
    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    std::lock_guard<std::mutex> lock(m_mutex);
    if (gpu)
    {
        for (auto& kv : m_cache)
        {
            if (kv.second && kv.second->gpuState)
            {
                gpu->destroyState(kv.second->gpuState);
                kv.second->gpuState = nullptr;
            }
        }
    }
    m_cache.clear();
    m_instances.clear();
}

std::shared_ptr<StandaloneRasterImageLoader::CacheEntry>
StandaloneRasterImageLoader::_loadOrGetCached(const std::string& url, size_t maxMipLevels)
{
    // Caller holds m_mutex.
    auto it = m_cache.find(url);
    if (it != m_cache.end())
    {
        return it->second;
    }

    auto entry = std::make_shared<CacheEntry>();
    entry->failed = true; // optimistic: flip on success

    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (!gpu)
    {
        fprintf(stderr, "StandaloneRasterImageLoader: no IByteImageGpu registered; cannot load '%s'\n",
                url.c_str());
        m_cache[url] = entry;
        return entry;
    }

    // Read the file into memory. stb_image is compiled with STBI_NO_STDIO
    // elsewhere in this library so the file-path variant isn't linked in.
    std::ifstream file(url, std::ios::binary);
    if (!file)
    {
        fprintf(stderr, "StandaloneRasterImageLoader: cannot open '%s'\n", url.c_str());
        m_cache[url] = entry;
        return entry;
    }
    std::vector<uint8_t> fileBytes((std::istreambuf_iterator<char>(file)),
                                   std::istreambuf_iterator<char>());
    if (fileBytes.empty())
    {
        fprintf(stderr, "StandaloneRasterImageLoader: empty file '%s'\n", url.c_str());
        m_cache[url] = entry;
        return entry;
    }

    int w = 0, h = 0, comp = 0;
    // Always decode to RGBA8.
    uint8_t* pixels = stbi_load_from_memory(fileBytes.data(),
                                            static_cast<int>(fileBytes.size()),
                                            &w, &h, &comp, 4);
    if (!pixels || w <= 0 || h <= 0)
    {
        fprintf(stderr, "StandaloneRasterImageLoader: stbi_load_from_memory failed for '%s': %s\n",
                url.c_str(), stbi_failure_reason() ? stbi_failure_reason() : "unknown");
        if (pixels) stbi_image_free(pixels);
        m_cache[url] = entry;
        return entry;
    }

    const uint32_t width  = static_cast<uint32_t>(w);
    const uint32_t height = static_cast<uint32_t>(h);

    // Build mip chain up to maxMipLevels (bounded by image size).
    size_t maxPossible = 1;
    {
        uint32_t dim = std::max(width, height);
        while (dim > 1) { dim /= 2; ++maxPossible; }
    }
    size_t mipCount = std::min(maxMipLevels == 0 ? size_t(1) : maxMipLevels, maxPossible);
    if (mipCount == 0) mipCount = 1;

    std::vector<const uint8_t*> mipBuffers;
    std::vector<size_t> mipStrides;
    generateMipChain(pixels, width, height, mipCount, mipBuffers, mipStrides);

    auto* state = gpu->createState();
    if (!state)
    {
        fprintf(stderr, "StandaloneRasterImageLoader: createState failed for '%s'\n", url.c_str());
        // Free generated mips (slot 0 is the stbi pointer).
        for (size_t mip = 1; mip < mipBuffers.size(); ++mip)
            ::free(const_cast<uint8_t*>(mipBuffers[mip]));
        stbi_image_free(pixels);
        m_cache[url] = entry;
        return entry;
    }

    auto result = gpu->updateImage(state,
                                   mipBuffers.data(),
                                   mipStrides.data(),
                                   mipBuffers.size(),
                                   UInt2{ width, height },
                                   PixelFormat::eRGBA8_UNORM,
                                   /*fromGpu*/ false,
                                   /*gpuDeviceMask*/ 0,
                                   /*textureUsageFlags*/ 0,
                                   /*resourceUsageFlags*/ 0);

    // Free mip pixel data (GPU now owns a copy).
    for (size_t mip = 1; mip < mipBuffers.size(); ++mip)
        ::free(const_cast<uint8_t*>(mipBuffers[mip]));
    stbi_image_free(pixels);

    if (!result.imGuiReference)
    {
        gpu->destroyState(state);
        fprintf(stderr, "StandaloneRasterImageLoader: GPU upload failed for '%s'\n", url.c_str());
        m_cache[url] = entry;
        return entry;
    }

    entry->gpuState = state;
    entry->imGuiReference = result.imGuiReference;
    entry->size = UInt2{ width, height };
    entry->format = PixelFormat::eRGBA8_UNORM;
    entry->failed = false;

    m_cache[url] = entry;
    return entry;
}

IRasterImageLoader::LoadResult
StandaloneRasterImageLoader::beginLoad(void* instanceKey, const std::string& url)
{
    LoadResult out;
    out.cacheKey = url;

    if (url.empty())
    {
        out.status = LoadResult::eFailed;
        return out;
    }

    std::lock_guard<std::mutex> lock(m_mutex);

    // If this instance already has state for a different URL, drop it first.
    auto instIt = m_instances.find(instanceKey);
    if (instIt != m_instances.end() && instIt->second.cacheKey != url)
    {
        auto oldIt = m_cache.find(instIt->second.cacheKey);
        if (oldIt != m_cache.end() && oldIt->second)
        {
            if (--oldIt->second->refCount <= 0)
            {
                auto* gpu = PlatformRegistry::instance().byteImageGpu();
                if (gpu && oldIt->second->gpuState)
                    gpu->destroyState(oldIt->second->gpuState);
                m_cache.erase(oldIt);
            }
        }
        m_instances.erase(instIt);
    }

    auto entry = _loadOrGetCached(url, /*maxMipLevels*/ 3);
    if (entry->failed)
    {
        out.status = LoadResult::eFailed;
        InstanceState s;
        s.cacheKey = url;
        s.status = LoadResult::eFailed;
        m_instances[instanceKey] = s;
        return out;
    }

    ++entry->refCount;

    InstanceState s;
    s.cacheKey = url;
    s.status = LoadResult::eCached;
    m_instances[instanceKey] = s;

    out.status = LoadResult::eCached;
    out.imGuiReference = entry->imGuiReference;
    out.imageSize = entry->size;
    out.imageFormat = entry->format;
    out.managedResource = nullptr;
    return out;
}

IRasterImageLoader::LoadResult
StandaloneRasterImageLoader::poll(void* instanceKey,
                                  const ImageProviderTextureOptions& /*textureOptions*/,
                                  size_t /*maxMipLevels*/)
{
    LoadResult out;
    std::lock_guard<std::mutex> lock(m_mutex);

    auto it = m_instances.find(instanceKey);
    if (it == m_instances.end())
    {
        out.status = LoadResult::eFailed;
        return out;
    }

    out.cacheKey = it->second.cacheKey;

    auto cacheIt = m_cache.find(it->second.cacheKey);
    if (cacheIt == m_cache.end() || !cacheIt->second || cacheIt->second->failed)
    {
        out.status = LoadResult::eFailed;
        return out;
    }

    out.status = LoadResult::eReady;
    out.imGuiReference = cacheIt->second->imGuiReference;
    out.imageSize = cacheIt->second->size;
    out.imageFormat = cacheIt->second->format;
    out.managedResource = nullptr;
    return out;
}

void StandaloneRasterImageLoader::waitForCompletion(void* /*instanceKey*/, int32_t /*maxIterations*/)
{
    // Synchronous loader: nothing to wait for.
}

void StandaloneRasterImageLoader::releaseLoad(void* instanceKey)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto it = m_instances.find(instanceKey);
    if (it == m_instances.end())
        return;

    auto cacheIt = m_cache.find(it->second.cacheKey);
    if (cacheIt != m_cache.end() && cacheIt->second)
    {
        if (--cacheIt->second->refCount <= 0)
        {
            auto* gpu = PlatformRegistry::instance().byteImageGpu();
            if (gpu && cacheIt->second->gpuState)
                gpu->destroyState(cacheIt->second->gpuState);
            m_cache.erase(cacheIt);
        }
    }
    m_instances.erase(it);
}

void StandaloneRasterImageLoader::releaseGpuResource(const std::string& cacheKey)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto it = m_cache.find(cacheKey);
    if (it == m_cache.end() || !it->second)
        return;
    if (it->second->refCount <= 0)
    {
        auto* gpu = PlatformRegistry::instance().byteImageGpu();
        if (gpu && it->second->gpuState)
            gpu->destroyState(it->second->gpuState);
        m_cache.erase(it);
    }
}

} // namespace standalone
} // namespace ui
} // namespace omni
