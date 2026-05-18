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

#include "ImageProvider.h"
#include "IByteImageGpu.h"

#include <memory>

namespace omni
{
namespace ui
{

class OMNIUI_CLASS_API ByteImageProvider : public ImageProvider
{
public:
    OMNIUI_API
    ByteImageProvider();

    OMNIUI_API
    virtual ~ByteImageProvider();

    /**
     * @brief Sets byte data that the image provider will turn into an image.
     * @param bytes Data bytes.
     * @param size Tuple of image size, (width, height).
     * @param stride Number of bytes between rows of data bytes. Value kAutoCalculateStride could be used to
     * auto-calculate stride based on format, given data bytes have no gaps.
     * @param format Image format.
     */
    OMNIUI_API
    virtual void setBytesData(const uint8_t* bytes,
                              UInt2 size,
                              size_t stride = kAutoCalculateStride,
                              PixelFormat format = PixelFormat::eRGBA8_UNORM);

    OMNIUI_API
    virtual void setMipMappedBytesData(const uint8_t* const* mipMapBytes,
                                       size_t* mipMapStrides,
                                       size_t mipMapCount,
                                       UInt2 size,
                                       PixelFormat format = PixelFormat::eRGBA8_UNORM);

    OMNIUI_API
    virtual void setMipMappedBytesData(const uint8_t* bytes,
                                       UInt2 size,
                                       size_t stride,
                                       PixelFormat format = PixelFormat::eRGBA8_UNORM,
                                       size_t maxMipLevels = SIZE_MAX);

    OMNIUI_API
    virtual void setBytesDataFromGPU(const uint8_t* bytes,
                                     UInt2 size,
                                     size_t stride = kAutoCalculateStride,
                                     PixelFormat format = PixelFormat::eRGBA8_UNORM);

    OMNIUI_API
    void prepareDraw(float widgetWidth, float widgetHeight) override;

protected:
    friend class GpuResourcesCache;

    void _updateImage(const uint8_t* const* mipMapBuffers,
                      size_t* mipMapStrides,
                      size_t mipMapCount,
                      UInt2 size,
                      PixelFormat format,
                      bool fromGpu = false);
    OMNIUI_API
    void _releaseImage() override;

    OMNIUI_API
    bool mergeTextureOptions(TextureOptions& textureOptions) const override;

    OMNIUI_API
    bool setTextureOptions(TextureOptions textureOptions) override;

    IByteImageGpu::Handle m_gpuState = nullptr;
    std::unique_ptr<TextureOptions> m_textureOptions;
};

}
}
