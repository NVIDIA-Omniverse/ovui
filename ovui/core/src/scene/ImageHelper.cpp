/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/scene/ImageHelper.h>
#include <cstring>

#include <omni/ui/platform/Log.h>

#include <omni/ui/ImageProvider/ImageProvider.h>
#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include <omni/ui/ImageProvider/VectorImageProvider.h>
#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/SceneView.h>


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

namespace {

using TextureOptions = ImageProviderTextureOptions;

inline static bool _endsWith(std::string const& value, std::string const& ending)
{
    if (ending.size() > value.size())
    {
        return false;
    }

    return std::equal(ending.rbegin(), ending.rend(), value.rbegin(),
                      [](char i, char j) { return (std::tolower(i) == std::tolower(j)); });
}

template <typename T>
class ImageProviderWithFlags : public T
{
    const ImageProviderTextureOptions m_textureOptions;
public:
    ImageProviderWithFlags(std::string url, TextureOptions textureOption)
        : T(std::move(url))
        , m_textureOptions(std::move(textureOption))
    {
    }

    bool mergeTextureOptions(typename T::TextureOptions& textureOptions) const override
    {
        // Copy stored device mask to textureOptions, but error out on case where
        // both have device masks that do not match.
        const auto deviceMask = m_textureOptions.gpuDeviceMask;
        if (textureOptions.gpuDeviceMask)
        {
            if (deviceMask && deviceMask != textureOptions.gpuDeviceMask)
            {
                OMNIUI_LOG_ERROR("ByteImageProvider has existing texture options that do not match input. (%u, %u)",
                    textureOptions.gpuDeviceMask, deviceMask);
                return false;
            }
        }
        else if (deviceMask)
        {
            textureOptions.gpuDeviceMask = deviceMask;
        }

        // Or the other flags in
        textureOptions.textureUsageFlags |= m_textureOptions.textureUsageFlags;
        textureOptions.resourceUsageFlags |= m_textureOptions.resourceUsageFlags;

        return true;
    }
};

std::unique_ptr<TextureOptions> getTextureOptionsPointer()
{
    constexpr TextureOptions emptyOptions = {};
    TextureOptions imageOptions = ImageHelper::getTextureOptions();
    if (::memcmp(&imageOptions, &emptyOptions, sizeof(TextureOptions)) != 0)
    {
        return std::make_unique<TextureOptions>(std::move(imageOptions));
    }
    return {};
}

}

TextureOptions ImageHelper::getTextureOptions()
{
    auto container = SceneContainerStack::top();
    if (container)
    {
        const SceneView* sceneView = container->getSceneView();
        if (sceneView)
        {
            return sceneView->getTextureOptions();
        }
    }
    return {};
}

ImageHelper::ImageHelper()
    : m_textureOptions(getTextureOptionsPointer())
{
}

ImageHelper::~ImageHelper()
{
}

void ImageHelper::_sourceUrlChanged()
{
    if (m_sourceUrlChangedInternallyFlag)
    {
        return;
    }

    const std::string& texture = this->getSourceUrl();
    if (texture.empty())
    {
        m_sourceUrlChangedInternallyFlag = true;
        this->setImageProvider(nullptr);
        m_sourceUrlChangedInternallyFlag = false;
        return;
    }

    std::shared_ptr<ImageProvider> imageProvider;
    // TODO: Do we have another way to determine if it's vector?
    if (_endsWith(texture, ".svg"))
    {
        if (m_textureOptions)
        {
            imageProvider = std::make_shared<ImageProviderWithFlags<VectorImageProvider>>(texture, *m_textureOptions);
        }
        else
        {
            imageProvider = std::make_shared<VectorImageProvider>(texture);
        }
    }
    else
    {
        if (m_textureOptions)
        {
            imageProvider = std::make_shared<ImageProviderWithFlags<RasterImageProvider>>(texture, *m_textureOptions);
        }
        else
        {
            imageProvider = std::make_shared<RasterImageProvider>(texture);
        }
    }

    m_sourceUrlChangedInternallyFlag = true;
    this->setImageProvider(std::move(imageProvider));
    m_sourceUrlChangedInternallyFlag = false;
}

void ImageHelper::_providerChanged()
{
    if (m_sourceUrlChangedInternallyFlag)
    {
        return;
    }

    m_sourceUrlChangedInternallyFlag = true;
    // When we set provider explicitly we clear the texture path
    this->setSourceUrl({});
    m_sourceUrlChangedInternallyFlag = false;
}

void ImageHelper::_prepareDrawContent(
    const Matrix44& projection, const Matrix44& view, bool& cacheIsDirty, void** texture, void** resource)
{
    // Extract texture from m_imageProvider
    const auto& imageProvider = this->getImageProvider();
    if (imageProvider)
    {
        // printf(">>> %f %f\n", m_textureWidthCache, m_textureHeightCache);
        // Image Provider routine
        imageProvider->prepareDraw(this->_computeImageWidth(static_cast<float>(m_textureWidthCache)),
                                   this->_computeImageHeight(static_cast<float>(m_textureHeightCache)));

        void* textureGpuReference = imageProvider->getImGuiReference();
        auto* managedImageResource = imageProvider->getManagedResource();
        auto textureSize = imageProvider->getSize();
        if (imageProvider->isReferenceValid() && textureSize.x != 0 && textureSize.y != 0)
        {
            if (textureSize.x != m_textureWidthCache || textureSize.y != m_textureHeightCache)
            {
                m_textureWidthCache = (float)textureSize.x;
                m_textureHeightCache = (float)textureSize.y;
                cacheIsDirty = true;
            }
            *texture = textureGpuReference;
            *resource = managedImageResource;
        }
    }
}

float ImageHelper::_computeImageWidth(float width) const
{
    return this->getImageWidth() ? static_cast<float>(this->getImageWidth()) : width;
}

float ImageHelper::_computeImageHeight(float height) const
{
    return this->getImageHeight() ? static_cast<float>(this->getImageHeight()) : height;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
