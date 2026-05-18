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

#include "platform/Assert.h"
#include "platform/Log.h"
#include "platform/PlatformRegistry.h"
#include "platform/IUiFileIO.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/ImageProvider/ImageProvider.h>
#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include <omni/ui/ImageProvider/VectorImageProvider.h>
#include <omni/ui/ImageWithProvider.h>
#include <omni/ui/StyleContainer.h>

#include <algorithm>
#include <string>
#include <unordered_set>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The filling and alignment logic. It takes the canvas and returns the offset, the size and uvs of the new
 * canvas that contains aligned image.
 *
 * @param alignment Input. The alignment policy.
 * @param fillPolicy Input. The filling policy.
 * @param displayWindowSize Input. The size of the display window (aka viewport resolution).
 * @param canvasSize Input/Output. The size of the canvas the image should be filled/aligned. It will have the new size
 *                   of the canvas that contains the aligned image.
 * @param cursorOffset Output. The offset the canvas should be moved to contain aligned image.
 * @param uvs The UV coordinates of the canvas.
 */
static void alignImage(Alignment alignment,
                       ImageWithProvider::FillPolicy fillPolicy,
                       const float displayWindowSize[2],
                       float canvasSize[2],
                       float cursorOffset[2],
                       ImVec2 uvs[2])
{
    if (fillPolicy == ImageWithProvider::FillPolicy::ePreserveAspectFit)
    {
        // Scale image to fit the provided area
        float imageAspect = displayWindowSize[0] / displayWindowSize[1];
        float canvasAspect = canvasSize[0] / canvasSize[1];
        if (imageAspect < canvasAspect)
        {
            // Width of the image is changing, height is unchanged.
            float newWidth = canvasSize[1] * imageAspect;

            // Align the image
            if (alignment & Alignment::eRight)
            {
                cursorOffset[0] = canvasSize[0] - newWidth;
            }
            else if (alignment & Alignment::eHCenter)
            {
                cursorOffset[0] = 0.5f * (canvasSize[0] - newWidth);
            }

            canvasSize[0] = newWidth;
        }
        else
        {
            // Height of the image is changing, width is unchanged.
            float newHeight = canvasSize[0] / imageAspect;

            // Align the image
            if (alignment & Alignment::eBottom)
            {
                cursorOffset[1] = canvasSize[1] - newHeight;
            }
            else if (alignment & Alignment::eVCenter)
            {
                cursorOffset[1] = 0.5f * (canvasSize[1] - newHeight);
            }

            canvasSize[1] = newHeight;
        }
    }
    else if (fillPolicy == ImageWithProvider::FillPolicy::ePreserveAspectCrop)
    {
        // Crop the image image to fill the area and don't change the aspect ratio.
        float imageAspect = displayWindowSize[0] / displayWindowSize[1];
        float canvasAspect = canvasSize[0] / canvasSize[1];
        if (imageAspect < canvasAspect)
        {
            float uvHeight = imageAspect / canvasAspect;

            if (alignment & Alignment::eTop)
            {
                uvs[1].y = uvHeight;
            }
            else if (alignment & Alignment::eBottom)
            {
                uvs[0].y = 1.0f - uvHeight;
            }
            else if (alignment & Alignment::eVCenter)
            {
                uvs[0].y = 0.5f - uvHeight * 0.5f;
                uvs[1].y = 0.5f + uvHeight * 0.5f;
            }
        }
        else
        {
            float uvWidth = canvasAspect / imageAspect;

            if (alignment & Alignment::eLeft)
            {
                uvs[1].x = uvWidth;
            }
            else if (alignment & Alignment::eRight)
            {
                uvs[0].x = 1.0f - uvWidth;
            }
            else if (alignment & Alignment::eHCenter)
            {
                uvs[0].x = 0.5f - uvWidth * 0.5f;
                uvs[1].x = 0.5f + uvWidth * 0.5f;
            }
        }
    }
}

ImageWithProvider::ImageWithProvider(std::shared_ptr<ImageProvider> provider) : Widget{}
{
    m_styleStateToTextureDataIndex.fill(SIZE_MAX);
    m_styleStateToResolvedStyle.fill(nullptr);
    if (provider)
    {
        m_textureDataArray.push_back(std::make_unique<TextureData>());
        m_textureDataArray.back()->imageProvider = provider;
        for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
        {
            m_styleStateToTextureDataIndex[i] = 0;
        }
        m_overrideStyleImages = true;
    }
}

ImageWithProvider::ImageWithProvider(const std::string& url) : Widget{}
{
    m_styleStateToTextureDataIndex.fill(SIZE_MAX);
    m_styleStateToResolvedStyle.fill(nullptr);
    if (!url.empty())
    {
        m_textureDataArray.push_back(std::make_unique<TextureData>());
        m_textureDataArray.back()->imageProvider = _createImageProviderFromUrl(url.c_str());
        for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
        {
            m_styleStateToTextureDataIndex[i] = 0;
        }
        m_overrideStyleImages = true;
    }
}

ImageWithProvider::~ImageWithProvider()
{
    m_createdImageProviders.clear();
}

void ImageWithProvider::destroy()
{
    m_createdImageProviders.clear();
    Widget::destroy();
}

void ImageWithProvider::onStyleUpdated()
{
    if (!m_overrideStyleImages)
    {
        m_updateStyleImages = true;
    }
}

void ImageWithProvider::prepareDraw(float width, float height)
{
    if (!m_overrideStyleImages && (m_updateStyleImages || this->_hasStyleUrlChanged()))
    {
        this->_populateImageProvidersFromStyles();
    }

    for (size_t stateId = 0; stateId < static_cast<size_t>(StyleContainer::State::eCount); ++stateId)
    {
        std::lock_guard<std::mutex> lock(m_textureMutex);

        size_t textureIndex = m_styleStateToTextureDataIndex[stateId];
        if (textureIndex == SIZE_MAX)
        {
            continue;
        }

        if (textureIndex >= m_textureDataArray.size())
        {
            OMNIUI_LOG_ERROR("Invalid textureIndex in ImageWithProvider!");
            continue;
        }

        std::shared_ptr<ImageProvider>& imageProvider = m_textureDataArray[textureIndex]->imageProvider;
        imageProvider->prepareDraw(width, height);
    }
}

std::shared_ptr<ImageProvider>& ImageWithProvider::_createImageProviderFromUrl(const char* url)
{
    std::string resolvedUrl = PlatformRegistry::instance().fileIO()->resolvePath(url);
    std::string extension;
    auto dotPos = resolvedUrl.rfind('.');
    if (dotPos != std::string::npos)
    {
        extension = resolvedUrl.substr(dotPos);
    }

    if (extension == ".svg")
    {
        m_createdImageProviders.emplace_back(std::make_shared<VectorImageProvider>());
        static_cast<VectorImageProvider*>(m_createdImageProviders.back().get())->setSourceUrl(url);
    }
    else
    {
        m_createdImageProviders.emplace_back(std::make_shared<RasterImageProvider>());
        static_cast<RasterImageProvider*>(m_createdImageProviders.back().get())->setSourceUrl(url);
    }

    return m_createdImageProviders.back();
}

void ImageWithProvider::_populateImageProvidersFromStyles()
{
    std::lock_guard<std::mutex> lock(m_textureMutex);
    if (!m_overrideStyleImages)
    {
        // Get the texture from the style
        const char* defaultImagePath = nullptr;
        for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
        {
            auto state = static_cast<StyleContainer::State>(i);

            const char* imagePath;
            if (this->_resolveStyleProperty(StyleStringProperty::eImageUrl, state, &imagePath))
            {
                m_styleStateToResolvedStyle[i] = imagePath;
            }
            else
            {
                imagePath = defaultImagePath;
                m_styleStateToResolvedStyle[i] = nullptr;
            }

            if (state == StyleContainer::State::eNormal && imagePath)
            {
                defaultImagePath = imagePath;
            }

            // In some edge cases imagePath could end up being nullptr, which will lead to crash, so we need this
            // wrapper/check
            std::string imagePathStr;
            if (imagePath)
                imagePathStr = imagePath;
            else
                continue;

            auto emplaced =
                m_imageUrlToTextureDataIndex.emplace(std::piecewise_construct, std::forward_as_tuple(imagePathStr),
                                                     std::forward_as_tuple(m_textureDataArray.size()));
            // The second arg is a bool denoting whether the insertion took place (true if insertion happened, false if
            // it did not). If the source URL is inserted, we need to create the texture data as well. Otherwise we had
            // the texture data before.
            if (emplaced.second)
            {
                m_textureDataArray.push_back(std::make_unique<TextureData>());
            }

            // The index of found texture
            size_t textureIndex = emplaced.first->second;
            OMNIUI_ASSERT(textureIndex != SIZE_MAX);

            if (!m_textureDataArray[textureIndex])
            {
                // It happens if the texture was destroyed in past and we need to load it again.
                m_textureDataArray[textureIndex] = std::make_unique<TextureData>();
            }

            // The texture that Image had before.
            size_t& previousTextureIndex = m_styleStateToTextureDataIndex[static_cast<size_t>(state)];

            if (previousTextureIndex == textureIndex)
            {
                // Do nothing because the texture is not changed for the current style state.
                continue;
            }
            else
            {
                if (textureIndex != SIZE_MAX)
                {
                    m_textureDataArray[textureIndex]->counter++;
                }

                if (previousTextureIndex != SIZE_MAX)
                {
                    // We are here because the texture is changed for the current state. We need to decrease the number
                    // of states that need this texture.
                    auto& imageDataOfPreviousImage = m_textureDataArray[previousTextureIndex];

                    OMNIUI_ASSERT(imageDataOfPreviousImage);
                    OMNIUI_ASSERT(imageDataOfPreviousImage->counter > 0);

                    imageDataOfPreviousImage->counter--;
                    if (imageDataOfPreviousImage->counter == 0)
                    {
                        // The use count reaches zero and it means there is to style state that is using this texture.
                        // We don't need it anymore and we can delete it.
                        imageDataOfPreviousImage.reset();
                    }
                }
            }

            previousTextureIndex = textureIndex;

            if (textureIndex == SIZE_MAX || m_textureDataArray[textureIndex]->loadingStarted)
            {
                // Either the image url is empty the loading of the texture is already started. Nothing to do.
                continue;
            }

            m_textureDataArray[textureIndex]->loadingStarted = true;
            m_textureDataArray[textureIndex]->imageProvider = _createImageProviderFromUrl(imagePath);
        }
        m_updateStyleImages = false;
    }
}

void ImageWithProvider::_drawContent(float elapsedTime)
{
    // It's not the best way to load the image in draw cycle because the first frame the widget will be empty. But
    // it's good because it will be lazy loaded when the widget appears on the visible area.
    if (!m_overrideStyleImages && (m_updateStyleImages || this->_hasStyleUrlChanged()))
    {
        _populateImageProvidersFromStyles();
    }

    ImTextureID textureGpuReference = 0;
    UInt2 textureSize = { 0, 0 };
    DisplayWindowRect displayWindow = {0, 0, 1, 1};
    {
        size_t stateId = static_cast<size_t>(this->_getStyleState());

        std::lock_guard<std::mutex> lock(m_textureMutex);

        size_t textureIndex = m_styleStateToTextureDataIndex[stateId];
        if (textureIndex == SIZE_MAX)
        {
            return;
        }

        if (textureIndex >= m_textureDataArray.size())
        {
            OMNIUI_LOG_ERROR("Invalid textureIndex in ImageWithProvider!");
            return;
        }

        std::shared_ptr<ImageProvider>& imageProvider = m_textureDataArray[textureIndex]->imageProvider;
        imageProvider->prepareDraw(this->getComputedContentWidth(), this->getComputedContentHeight());

        textureGpuReference = (ImTextureID)(uintptr_t)imageProvider->getImGuiReference();
        textureSize = imageProvider->getSize();
        if (!imageProvider->isReferenceValid() || textureSize.x == 0 || textureSize.y == 0)
        {
            return;
        }

        displayWindow = imageProvider->getDisplayWindow();
    }

    // TODO: We don't have to use dpiScale here. The style should return the scaled value.
    float dpiScale = this->getDpiScale();

    // Determine which border we need.
    uint32_t borderColor = 0x0;
    this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &borderColor);

    // Determine which border we need.
    uint32_t tintColor = 0xFFFFFFFF;
    this->_resolveStyleProperty(StyleColorProperty::eColor, &tintColor);

    float borderWidth = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &borderWidth))
    {
        borderWidth *= dpiScale;
    }

    float borderRadius = 0.0f;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &borderRadius))
    {
        borderRadius *= dpiScale;
    }

    uint32_t round_corner = ImDrawFlags_RoundCornersAll;
    this->_resolveStyleProperty(StyleEnumProperty::eCornerFlag, &round_corner);

    float imageSize[2] = { static_cast<float>(textureSize.x), static_cast<float>(textureSize.y) };
    float canvasSize[2] = { this->getComputedContentWidth(), this->getComputedContentHeight() };
    float cursorOffset[2] = { 0.0f, 0.0f };
    ImVec2 uvs[2] = { { 0.0f, 0.0f }, { 0.0f, 0.0f } };

    float displayWidthNormalized = fabsf(displayWindow.z - displayWindow.x);
    float displayHeightNormalized = fabsf(displayWindow.w - displayWindow.y);
    float displayWindowSize[2] = { displayWidthNormalized * imageSize[0], displayHeightNormalized * imageSize[1] };

    uint32_t align = static_cast<uint32_t>(this->getAlignment());
    this->_resolveStyleProperty(StyleEnumProperty::eAlignment, &align);
    Alignment alignment = static_cast<Alignment>(align);

    uint32_t fillPolicyStyle = static_cast<uint32_t>(this->getFillPolicy());
    this->_resolveStyleProperty(StyleEnumProperty::eFillPolicy, &fillPolicyStyle);
    FillPolicy fillPolicy = static_cast<FillPolicy>(fillPolicyStyle);

    alignImage(alignment, fillPolicy, displayWindowSize, canvasSize, cursorOffset, uvs);

    auto cursor = ImGui::GetCursorScreenPos();
    float dataWindowOffsetX = std::max(-displayWindow.x/displayWidthNormalized, 0.0f) * canvasSize[0];
    float dataWindowOffsetY = std::max(-displayWindow.y/displayHeightNormalized, 0.0f) * canvasSize[1];
    float rectWidth = std::min((-displayWindow.x + 1)/displayWidthNormalized, 1.0f) * canvasSize[0] - dataWindowOffsetX;
    float rectHeight = std::min((-displayWindow.y + 1)/displayHeightNormalized, 1.0f) * canvasSize[1] - dataWindowOffsetY;

    cursor.x += cursorOffset[0] + dataWindowOffsetX;
    cursor.y += cursorOffset[1] + dataWindowOffsetY;

    uvs[0].x += displayWindow.x;
    uvs[0].y += displayWindow.y;
    uvs[1].x += displayWindow.z + 1.f/imageSize[0];
    uvs[1].y += displayWindow.w + 1.f/imageSize[1];
    uvs[0].x = std::clamp(uvs[0].x, 0.0f, 1.0f);
    uvs[0].y = std::clamp(uvs[0].y, 0.0f, 1.0f);
    uvs[1].x = std::clamp(uvs[1].x, 0.0f, 1.0f);
    uvs[1].y = std::clamp(uvs[1].y, 0.0f, 1.0f);

    ImVec2 rectMax{ cursor.x + rectWidth, cursor.y + rectHeight };

    if (this->getPixelAligned())
    {
        // Floor it to avoid artifacts
        cursor = ImFloor(cursor);
        rectMax = ImFloor(rectMax);
    }

    // Draw the image
    if (borderRadius == 0.0f)
    {
        ImGui::GetWindowDrawList()->AddImage(textureGpuReference, cursor, rectMax, uvs[0], uvs[1], tintColor);
    }
    else
    {
        ImGui::GetWindowDrawList()->AddImageRounded(
            textureGpuReference, cursor, rectMax, uvs[0], uvs[1], tintColor, borderRadius, round_corner);
    }

    // Draw rectangle
    if (borderWidth > 0.0f && borderColor != 0x0)
    {
        // Draw a border on top of rectangle.
        ImGui::GetWindowDrawList()->AddRect(cursor, rectMax, borderColor, borderRadius, round_corner, borderWidth);
    }
}

bool ImageWithProvider::_hasStyleUrlChanged() const
{
    for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
    {
        if (!m_styleStateToResolvedStyle[i])
        {
            continue;
        }

        auto state = static_cast<StyleContainer::State>(i);

        const char* imagePath;
        if (!this->_resolveStyleProperty(StyleStringProperty::eImageUrl, state, &imagePath))
        {
            continue;
        }

        if (m_styleStateToResolvedStyle[i] != imagePath)
        {
            return true;
        }
    }

    return false;
}

ImageWithProvider::TextureData::~TextureData()
{
}


OMNIUI_NAMESPACE_CLOSE_SCOPE
