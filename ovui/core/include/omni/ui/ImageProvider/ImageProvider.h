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

#include "../Object.h"
#include "../Property.h"

#include <omni/ui/platform/Types.h>

#include <memory>
#include <utility>

// Forward declaration for opaque GPU resource type used only by pointer/reference.
namespace rtx { namespace resourcemanager { class RpResource; } }

namespace omni
{
namespace ui
{

constexpr const size_t kAutoCalculateStride = (size_t)-1;

/// Texture creation options for ImageProvider.
/// Layout matches omni::kit::renderer::IRendererTextureOptions.
struct ImageProviderTextureOptions
{
    uint32_t gpuDeviceMask = 0;
    uint32_t textureUsageFlags = 0;
    uint32_t resourceUsageFlags = 0;
    union
    {
        bool pooled;
        uint32_t unusedExtPadding = 0;
    };
};

class OMNIUI_CLASS_API ImageProvider
{
protected:
    using GpuResource = rtx::resourcemanager::RpResource;
    using TextureOptions = ImageProviderTextureOptions;

public:
    OMNIUI_API
    ImageProvider();

    OMNIUI_API
    virtual ~ImageProvider();

    /**
     * @brief Returns reference which could be used to draw ImGui images with.
     */
    OMNIUI_API
    virtual void* getImGuiReference();

    /**
     * @brief Returns true if ImGui reference is valid, false otherwise.
     */
    OMNIUI_API
    virtual bool isReferenceValid()
    {
        return m_imGuiReference != nullptr;
    }

    /**
     * @brief Gets image width.
     */
    OMNIUI_API
    size_t getWidth()
    {
        return m_imageSize.x;
    }

    /**
     * @brief Gets image height.
     */
    OMNIUI_API
    size_t getHeight()
    {
        return m_imageSize.y;
    }

    /**
     * @brief Gets tuple (width, height).
     */
    OMNIUI_API
    UInt2 getSize()
    {
        return m_imageSize;
    }

    /**
     * @brief Gets display window w.r.t to the image (data window). The display size is same as the viewport size.
     */
    OMNIUI_API
    DisplayWindowRect getDisplayWindow()
    {
        return m_imageDisplayWindow;
    }

    /**
     * @brief Gets image format.
     */
    OMNIUI_API
    PixelFormat getFormat()
    {
        return m_imageFormat;
    }

    /**
     * @brief Function that should be called when the widget is being prepared to be drawn. Lazy load of image
     * contents may happen there, depending on the image provider logic.
     * @param widgetWidth Computed width of the widget.
     * @param widgetHeight Computed height of the widget.
     */
    OMNIUI_API
    virtual void prepareDraw(float widgetWidth, float widgetHeight);

    /**
     * @brief Sets non-managed image data directly.
     * @param imGuiReference Opaque pointer to the data used in the ImGuiRenderer.
     * @param size Size tuple (width, height) of the image data.
     * @param format Pixel format of the image data.
     * @param gpuRsrc The GpuResource to be associated with the image data. Can be nullptr.
     */
    OMNIUI_API
    void setImageData(void* imGuiReference, UInt2 size, PixelFormat format, GpuResource* gpuRsrc = nullptr);

    /**
     * @brief Sets image data directly from a GpuResource.
     * @param rpRsrc The GpuResource to be used for data.
     * @return A boolean value whether the image-data was set.
     *         On success the GpuResource will have been retained, otherwise not.
     */
    OMNIUI_API
    bool setImageData(GpuResource& gpuRsrc);

    /**
     * Sets image data directly from a GpuResource.
     *
     * @param gpuRsrc The GpuResource to be used for data.
     * @param presentationKey The presentation key associated with the GpuResource. Used by the present thread to get the ImGui reference.
     *
     * @return A boolean value indicating whether the image-data was set.
     *         On success, the GpuResource will have been retained, otherwise not.
     */
    OMNIUI_API
    bool setImageData(GpuResource& gpuRsrc, uint64_t presentationKey);

    /**
     * @brief Shuts down the image provider system
     */
    OMNIUI_API
    static void shutdown();

    /**
     * @brief Returns the managed GPU resource.
     */
    OMNIUI_API
    GpuResource* getManagedResource();

protected:
    /**
     * @brief Release the managed image data, called from setImageData
     */
    OMNIUI_API
    virtual void _releaseImage()
    {
    }

    void _shutdown();

    OMNIUI_API
    virtual bool _setManagedResource(GpuResource* rpRsrc);

    OMNIUI_API
    virtual bool mergeTextureOptions(TextureOptions& textureOptions) const;

    OMNIUI_API
    virtual bool setTextureOptions(TextureOptions textureOptions);

    void* m_imGuiReference = nullptr;
    UInt2 m_imageSize = {};
    DisplayWindowRect m_imageDisplayWindow = { 0.0f, 0.0f, 1.0f, 1.0f };
    PixelFormat m_imageFormat = PixelFormat::eRGBA8_UNORM;
    size_t m_imageMipCount = 1;
    bool m_isShutdown = false;

    void* m_kitRenderer = nullptr;
    GpuResource* m_managedRsrc = nullptr;
    uint64_t m_presentationKey = 0;
    bool m_hasFuture = false;
    uint32_t m_id = 0;

public:
    template <typename T, typename... Args>
    static std::shared_ptr<T> create(Args&&... args)
    {
        std::shared_ptr<T> ptr{ new T{ std::forward<Args>(args)... } };
        return ptr;
    }

    template <typename T, typename Deleter, typename... Args>
    static std::shared_ptr<T> createWithDeleter(Deleter&& deleter, Args&&... args)
    {
        return std::shared_ptr<T>{ new T{ std::forward<Args>(args)... }, std::forward<Deleter>(deleter) };
    }
};

}
}
