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

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include "../platform/Log.h"

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/Profile.h>

#include <cmath>
#include <algorithm>
#include <vector>

namespace omni
{
namespace ui
{

ByteImageProvider::ByteImageProvider()
{
    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (gpu)
    {
        m_gpuState = gpu->createState();
    }
}

ByteImageProvider::~ByteImageProvider()
{
    // ImageProvider::~ImageProvider() calls _releaseImage via setImageData,
    // but since it's called from the base destructor, the derived
    // _releaseImage is never called. So we must do it here.
    this->setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);

    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (gpu && m_gpuState)
    {
        gpu->destroyState(m_gpuState);
        m_gpuState = nullptr;
    }
}

bool ByteImageProvider::mergeTextureOptions(TextureOptions& textureOptions) const
{
    if (m_textureOptions)
    {
        const auto deviceMask = m_textureOptions->gpuDeviceMask;
        if (textureOptions.gpuDeviceMask)
        {
            if (deviceMask && deviceMask != textureOptions.gpuDeviceMask)
            {
                OMNIUI_LOG_ERROR("ByteImageProvider has exiting texture options that do not match input. (%u, %u)",
                    textureOptions.gpuDeviceMask, deviceMask);
                return false;
            }
        }
        else if (deviceMask)
        {
            textureOptions.gpuDeviceMask = deviceMask;
        }

        textureOptions.textureUsageFlags |= m_textureOptions->textureUsageFlags;
        textureOptions.resourceUsageFlags |= m_textureOptions->resourceUsageFlags;
    }
    return true;
}

bool ByteImageProvider::setTextureOptions(TextureOptions textureOptions)
{
    if (!m_textureOptions)
    {
        m_textureOptions = std::make_unique<TextureOptions>(textureOptions);
    }
    else
    {
        *m_textureOptions = textureOptions;
    }
    return true;
}

void ByteImageProvider::_updateImage(const uint8_t* const* mipMapBuffers,
                                     size_t* mipMapStrides,
                                     size_t mipMapCount,
                                     UInt2 size,
                                     PixelFormat format,
                                     bool fromGpu)
{
    OMNIUI_PROFILE_VERBOSE_ZONE("ByteImageProvider::_updateImage");

    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (!gpu || !m_gpuState)
    {
        return;
    }

    uint32_t optDeviceMask = m_textureOptions ? m_textureOptions->gpuDeviceMask : 0;
    uint32_t optTexFlags = m_textureOptions ? m_textureOptions->textureUsageFlags : 0;
    uint32_t optRsrcFlags = m_textureOptions ? m_textureOptions->resourceUsageFlags : 0;

    auto result = gpu->updateImage(m_gpuState, mipMapBuffers, mipMapStrides, mipMapCount,
                                   size, format, fromGpu,
                                   optDeviceMask, optTexFlags, optRsrcFlags);

    if (!result.imGuiReference)
    {
        OMNIUI_LOG_ERROR("Failed to create texture GPU data! [%u x %u, %zu mips]", size.x, size.y, mipMapCount);
        return;
    }

    if (result.managedResource)
    {
        _setManagedResource(reinterpret_cast<GpuResource*>(result.managedResource));
    }

    m_imageSize = size;
    m_imageFormat = format;
    m_imageMipCount = mipMapCount;
    m_imGuiReference = result.imGuiReference;
}

void ByteImageProvider::_releaseImage()
{
    auto* gpu = PlatformRegistry::instance().byteImageGpu();
    if (gpu && m_gpuState)
    {
        gpu->releaseImage(m_gpuState);
    }
}

void ByteImageProvider::prepareDraw(float widgetWidth, float widgetHeight)
{
}

void ByteImageProvider::setBytesData(const uint8_t* bytes, UInt2 size, size_t stride, PixelFormat format)
{
    if (bytes == nullptr)
    {
        OMNIUI_LOG_WARN("setBytesData called with nullptr\n");
        return;
    }

    if (stride == kAutoCalculateStride)
    {
        stride = size.x * getPixelFormatSize(format);
    }
    _updateImage(&bytes, &stride, 1, size, format);
}

void ByteImageProvider::setMipMappedBytesData(const uint8_t* const* mipMapBytes,
                                              size_t* mipMapStrides,
                                              size_t mipMapCount,
                                              UInt2 size,
                                              PixelFormat format)
{
    if (mipMapBytes == nullptr)
    {
        OMNIUI_LOG_WARN("setMipMappedBytesData called with nullptr\n");
        return;
    }

    const size_t formatSize = getPixelFormatSize(format);
    uint32_t mipDivisor = 1;
    for (size_t mip = 0; mip < mipMapCount; ++mip)
    {
        if (mipMapStrides[mip] == kAutoCalculateStride)
        {
            uint32_t mipMapSizeX = size.x / mipDivisor;
            mipMapStrides[mip] = mipMapSizeX * formatSize;
            mipDivisor *= 2;
        }
    }

    _updateImage(mipMapBytes, mipMapStrides, mipMapCount, size, format);
}

void ByteImageProvider::setMipMappedBytesData(
    const uint8_t* bytes, UInt2 size, size_t stride, PixelFormat format, size_t maxMipLevels)
{
    // Initialize the variables
    const uint8_t* rgbaDataMip0 = bytes;
    uint32_t width = size.x;
    uint32_t height = size.y;

    std::vector<const uint8_t*> mipMapRgbaData;
    std::vector<size_t> mipMapStrides;

    // Calculate the maximum size of the image (either width or height)
    int maxSize = std::max(width, height);
    // Calculate the number of mipmap levels based on the maximum size
    const size_t calculatedMipMapCount = (size_t)std::floor(std::log2((double)maxSize)) + 1;
    size_t mipMapCount = std::min(maxMipLevels, calculatedMipMapCount);

    bool isMipFormatSupported = isMipGenFormatSupported(format);

    mipMapCount = isMipFormatSupported ? mipMapCount : 0;

    // If there is more than one mipmap level, generate the mipmaps
    if (mipMapCount > 1)
    {
        {
            OMNIUI_PROFILE_VERBOSE_ZONE("Mip map generation");

            // Resize the vectors to hold the mipmap data and strides
            mipMapRgbaData.resize(mipMapCount);
            mipMapStrides.resize(mipMapCount);

            // Initialize a variable to keep track of the divisor for each
            // mipmap level
            uint32_t mipDivisor = 1;
            // Loop through each mipmap level
            for (size_t mip = 0; mip < mipMapCount; ++mip)
            {
                mipMapStrides[mip] = kAutoCalculateStride;
                if (mip == 0)
                {
                    mipMapRgbaData[0] = rgbaDataMip0;
                }
                else
                {
                    // For subsequent mipmap levels, calculate the new width and
                    // height
                    uint32_t mipWidth = width / mipDivisor;
                    uint32_t mipHeight = height / mipDivisor;

                    // Calculate the width and height of the previous mipmap level
                    uint32_t prevMipWidth = width / (mipDivisor / 2);
                    uint32_t prevMipHeight = height / (mipDivisor / 2);

                    // Allocate memory for the new mipmap level and calculate
                    // the new data
                    uint8_t* mipData = (uint8_t*)::malloc(mipWidth * mipHeight * 4);
                    const uint8_t* prevMipData = mipMapRgbaData[mip - 1];

                    // Get a pointer to the previous mipmap level data
                    for (uint32_t y = 0; y < mipHeight; ++y)
                    {
                        uint32_t yp1 = 2 * y + 1;
                        if (yp1 >= prevMipHeight)
                            yp1 = prevMipHeight - 1;

                        for (uint32_t x = 0; x < mipWidth; ++x)
                        {
                            uint32_t xp1 = 2 * x + 1;
                            if (xp1 >= prevMipWidth)
                            {
                                xp1 = prevMipWidth - 1;
                            }

                            for (uint32_t ch = 0; ch < 4; ++ch)
                            {
                                int avgChannel = prevMipData[((2 * x) + (2 * y) * prevMipWidth) * 4 + ch] +
                                                 prevMipData[(xp1 + (2 * y) * prevMipWidth) * 4 + ch] +
                                                 prevMipData[(xp1 + yp1 * prevMipWidth) * 4 + ch] +
                                                 prevMipData[((2 * x) + yp1 * prevMipWidth) * 4 + ch];
                                avgChannel /= 4;
                                if (avgChannel < 0)
                                {
                                    avgChannel = 0;
                                }
                                if (avgChannel > 255)
                                {
                                    avgChannel = 255;
                                }
                                mipData[(x + y * mipWidth) * 4 + ch] = static_cast<uint8_t>(avgChannel);
                            }
                        }
                    }

                    mipMapRgbaData[mip] = mipData;
                }
                mipDivisor *= 2;
            }
        }

        this->setMipMappedBytesData((const uint8_t**)mipMapRgbaData.data(), mipMapStrides.data(), mipMapCount,
                                    { static_cast<uint32_t>(width), static_cast<uint32_t>(height) },
                                    format);

        // Delete all but the 0-th mip level
        for (size_t mip = 1; mip < mipMapCount; ++mip)
        {
            ::free((void*)mipMapRgbaData[mip]);
        }
    }
    else
    {
        this->setBytesData(bytes, size, stride, format);
    }
}

void ByteImageProvider::setBytesDataFromGPU(const uint8_t* bytes,
                                            UInt2 size,
                                            size_t stride,
                                            PixelFormat format)
{
    if (bytes == nullptr)
    {
        OMNIUI_LOG_WARN("setBytesDataFromGPU called with nullptr\n");
        return;
    }

    if (stride == kAutoCalculateStride)
    {
        stride = size.x * getPixelFormatSize(format);
    }

    _updateImage(&bytes, &stride, 1, size, format, /*fromGpu*/ true);
}

}
}
