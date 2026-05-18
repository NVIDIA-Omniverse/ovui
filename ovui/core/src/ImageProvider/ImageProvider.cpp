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

#include <omni/ui/ImageProvider/ImageProvider.h>
#include "../platform/Log.h"
#include "../platform/PlatformRegistry.h"
#include "../platform/IImageProviderRenderer.h"

#include <mutex>
#include <list>

namespace omni
{
namespace ui
{

std::mutex s_mutex;
std::list<ImageProvider*> s_list;

ImageProvider::ImageProvider()
{
    {
        std::lock_guard<std::mutex> g(s_mutex);
        s_list.push_back(this);

        static uint32_t idCounter = 0;
        m_id = idCounter++;
    }

    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();
    if (ipr)
    {
        m_kitRenderer = ipr->acquireRenderer();
        if (!m_kitRenderer)
        {
            OMNIUI_LOG_ERROR("Renderer must be present!");
        }
    }
}

ImageProvider::~ImageProvider()
{
    setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
    {
        std::lock_guard<std::mutex> g(s_mutex);
        s_list.remove(this);
    }
}

void ImageProvider::setImageData(void* imGuiReference, UInt2 size, PixelFormat format, GpuResource* rpRsrc)
{
    if (m_isShutdown)
        return;

    _releaseImage();
    m_imGuiReference = imGuiReference;
    m_imageSize = size;
    m_imageFormat = format;
    _setManagedResource(rpRsrc);
}

void* ImageProvider::getImGuiReference()
{
    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();
    if (ipr && ipr->isPresentThreadEnabled(m_kitRenderer) && m_presentationKey)
    {
        uintptr_t intPtr = static_cast<uintptr_t>(m_presentationKey);
        return reinterpret_cast<void*>(intPtr);
    }
    return m_imGuiReference;
}


bool ImageProvider::setImageData(GpuResource& rpRsrc, uint64_t presentationKey)
{
    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();
    if (!ipr)
        return false;

    m_presentationKey = presentationKey;

    if (reinterpret_cast<void*>(&rpRsrc) != reinterpret_cast<void*>(m_managedRsrc))
    {
        auto result = ipr->ensureResourceWithTextureInfo(
            m_kitRenderer, reinterpret_cast<void*>(&rpRsrc), m_id);
        if (!result.resource)
        {
            return false;
        }

        setImageData(result.textureHandlePtr, { result.width, result.height }, result.format, nullptr);
        m_managedRsrc = reinterpret_cast<GpuResource*>(result.resource);
    }

    return true;
}

void ImageProvider::prepareDraw(float widgetWidth, float widgetHeight)
{
}

bool ImageProvider::setImageData(GpuResource& rpRsrc)
{
    return setImageData(rpRsrc, 0);
}

void ImageProvider::shutdown()
{
    std::lock_guard<std::mutex> g(s_mutex);
    for (auto* entry : s_list)
    {
        entry->_shutdown();
    }
}

void ImageProvider::_shutdown()
{
    m_isShutdown = true;
}

ImageProvider::GpuResource* ImageProvider::getManagedResource()
{
    return m_managedRsrc;
}

bool ImageProvider::_setManagedResource(GpuResource* rpRsrc)
{
    auto* ipr = PlatformRegistry::instance().imageProviderRenderer();

    auto* rsrc = reinterpret_cast<void*>(rpRsrc);
    auto* managed = reinterpret_cast<void*>(m_managedRsrc);

    if (rsrc == managed)
    {
        return true;
    }

    if (ipr)
    {
        if (rsrc)
        {
            rsrc = ipr->ensureResourceSimple(m_kitRenderer, rsrc, m_id);
        }
        if (managed)
        {
            ipr->releaseResource(m_kitRenderer, managed);
        }
    }

    m_managedRsrc = reinterpret_cast<GpuResource*>(rsrc);
    return true;
}

bool ImageProvider::mergeTextureOptions(ImageProvider::TextureOptions& textureOptions) const
{
    return true;
}

bool ImageProvider::setTextureOptions(TextureOptions textureOptions)
{
    OMNIUI_LOG_ERROR("ImageProvider::setTextureOptions is not implemented");
    return false;
}

}
}
