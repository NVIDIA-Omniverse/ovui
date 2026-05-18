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
#include "platform/IImageBackend.h"
#include "platform/IUiSettings.h"
#include "platform/Log.h"
#include "platform/PlatformRegistry.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Image.h>
#include <omni/ui/Profile.h>
#include <omni/ui/StyleContainer.h>

#include "WidgetData.h"

#include <memory>
#include <unordered_set>

OMNIUI_NAMESPACE_OPEN_SCOPE

constexpr char kSyncTextureLoadSettingPath[] = "/exts/omni.ui/Image/syncTextureLoad";
constexpr char kGenerateMipsSettingsPath[] = "/persistent/exts/omni.ui/Image/generateMips";

/**
 * @brief The filling and alignment logic. It takes the canvas and returns the offset, the size and uvs of the new
 * canvas that contains aligned image.
 *
 * @param alignment Input. The alignment policy.
 * @param fillPolicy Input. The filling policy.
 * @param imageSize Input. The full size of the image to fill.
 * @param canvasSize Input/Output. The size of the canvas the image should be filled/aligned. It will have the new size
 *                   of the canvas that contains the aligned image.
 * @param cursorOffset Output. The offset the canvas should be moved to contain aligned image.
 * @param uvs The UV coordinates of the canvas.
 */
static void alignImage(Alignment alignment,
                       Image::FillPolicy fillPolicy,
                       const ImVec2 imageSize,
                       ImVec2& canvasSize,
                       ImVec2& cursorOffset,
                       ImVec2 uvs[2])
{
    if (fillPolicy == Image::FillPolicy::ePreserveAspectFit)
    {
        // Scale image to fit the provided area
        float imageAspect = imageSize.x / imageSize.y;
        float canvasAspect = canvasSize.x / canvasSize.y;
        if (imageAspect < canvasAspect)
        {
            // Width of the image is changing, height is unchanged.
            float newWidth = canvasSize.y * imageAspect;

            // Align the image
            if (alignment & Alignment::eRight)
            {
                cursorOffset.x = canvasSize.x - newWidth;
            }
            else if (alignment & Alignment::eHCenter)
            {
                cursorOffset.x = 0.5f * (canvasSize.x - newWidth);
            }

            canvasSize.x = newWidth;
        }
        else
        {
            // Height of the image is changing, width is unchanged.
            float newHeight = canvasSize.x / imageAspect;

            // Align the image
            if (alignment & Alignment::eBottom)
            {
                cursorOffset.y = canvasSize.y - newHeight;
            }
            else if (alignment & Alignment::eVCenter)
            {
                cursorOffset.y = 0.5f * (canvasSize.y - newHeight);
            }

            canvasSize.y = newHeight;
        }
    }
    else if (fillPolicy == Image::FillPolicy::ePreserveAspectCrop)
    {
        // Crop the image image to fill the area and don't change the aspect ratio.
        float imageAspect = imageSize.x / imageSize.y;
        float canvasAspect = canvasSize.x / canvasSize.y;
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


struct Image::ImageData : public Widget::WidgetData
{
    ~ImageData() override = default;

    // struct to hold all data memebers accessed across threads.
    // textureMutex must be held for r/w operations on any of the fields in this object.
    // getTextureDataAndLock and getTextureDataFromState are utility functions for the most
    // common access patterns in this file.
    //
    struct TextureDataWithMutex
    {
        // The mutex for the texture operations, because we load the texture in the background.
        std::mutex textureMutex;
        // Texture data for all the loaded textures
        std::vector<std::unique_ptr<TextureData>> stateTextureData;
        // It is the cache of preloaded textures. We need it because we can switch the texture depending on the widget style
        // state. It can be a separate texture for hovered, disabled, selected, etc. widget. To switch the texture fast, we
        // preload them for all the states. To be sure that the same texture is not loaded twice, we keep them in a separate
        // vector, and we keep the index of the texture per style state. To know which texture is already loaded, we keep
        // the map name to the texture index.
        // Index of the texture per style state
        std::array<size_t, static_cast<size_t>(StyleContainer::State::eCount)> styleStateToIndex;
    } m_textureDataAndMutex;

    std::pair<std::unique_lock<std::mutex>, std::vector<std::unique_ptr<Image::TextureData>>&>
    getTextureDataAndLock();

    std::pair<std::unique_lock<std::mutex>, Image::TextureData*>
    getTextureDataFromState(StyleContainer::State state, bool errorMsgs);

    // Resolved style. We need it to know if style shade is changed. It's void*
    // to indicate that it can't be used as a string andit can only be used to
    // check if the style became dirty.
    std::array<const void*, static_cast<size_t>(StyleContainer::State::eCount)> m_styleStateToResolvedStyle;

    // Index of the texture per filename
    std::unordered_map<std::string, size_t> m_imageUrlToTextureDataIndex;

    // Flag to check all the textures if it's necessary to reload them.
    bool m_texturesLoaded = false;
};

std::pair<std::unique_lock<std::mutex>, std::vector<std::unique_ptr<Image::TextureData>>&>
Image::ImageData::getTextureDataAndLock()
{
    return { std::unique_lock<std::mutex>(m_textureDataAndMutex.textureMutex),
        m_textureDataAndMutex.stateTextureData };
}

std::pair<std::unique_lock<std::mutex>, Image::TextureData*>
Image::ImageData::getTextureDataFromState(StyleContainer::State state, bool errorMsgs)
{
    const size_t stateId = static_cast<size_t>(state);
    // _loadSourceUrl (which is called on main thread), can posibly assign into styleStateToIndex,
    // so lock should be held for bounds and read below.
    // it is released early in cases it leads to invalid data.
    //
    auto lockedData = getTextureDataAndLock();
    auto& styleToIndex = m_textureDataAndMutex.styleStateToIndex;
    if (stateId >= styleToIndex.size())
    {
        if (errorMsgs)
        {
            OMNIUI_LOG_ERROR("Out of bounds stateId: %zu", stateId);
        }
        return {};
    }

    const size_t textureIndex = styleToIndex[stateId];
    auto& lockedTextureData = lockedData.second;

    if (textureIndex >= lockedTextureData.size())
    {
        if (textureIndex != SIZE_MAX && errorMsgs)
        {
            OMNIUI_LOG_ERROR("Out of bounds textureIndex: %zu", textureIndex);
        }
        return {};
    }

    TextureData* texData = lockedTextureData[textureIndex].get();
    if (!texData)
    {
        if (errorMsgs)
        {
            OMNIUI_LOG_ERROR("Invalid TextureData for textureIndex: %zu", textureIndex);
        }
        return {};
    }

    return { std::move(lockedData.first), texData };
}

Image::Image(const std::string& sourceUrl)
    : Widget(new ImageData)
{
    auto* settings = PlatformRegistry::instance().settings();
    if (settings)
    {
        settings->setDefaultBool(kSyncTextureLoadSettingPath, false);
        settings->setDefaultBool(kGenerateMipsSettingsPath, false);
    }

    auto& data = _getData<ImageData>();
    data.m_textureDataAndMutex.styleStateToIndex.fill(SIZE_MAX);
    data.m_styleStateToResolvedStyle.fill(nullptr);

    this->setSourceUrlChangedFn([this](const auto&) {
        _getData<ImageData>().m_texturesLoaded = false;
    });
    this->setSourceUrl(sourceUrl);

    this->setProgressChangedFn([this](const auto& progress) {
        if (progress >= 1.0f)
        {
            this->forceRasterDirty(BakeDirtyReason::eContentChanged);
        }
    });
}

struct Image::TextureData
{
    TextureData() = default;
    ~TextureData() = default;

    // We delete TextureData when the use count reaches zero.
    size_t counter = 0;

    // Texture properties set by the backend after loading.
    uint32_t width = 0;
    uint32_t height = 0;

    // Flag to reload the texture.
    bool loadingStarted = false;

    // Backend-specific opaque texture state. Destructor releases GPU resources.
    std::unique_ptr<IImageBackend::TextureHandle> handle;
};

Image::~Image() = default;

void Image::destroy()
{
    auto& data = _getData<ImageData>();
    {
        auto lockedData = data.getTextureDataAndLock();
        lockedData.second.clear();
    }
    Widget::destroy();
}

void Image::onStyleUpdated()
{
    _getData<ImageData>().m_texturesLoaded = false;
}

bool Image::hasSourceUrl() const
{
    // We don't check styleStateToIndex because it's possible that the image has never called
    // _loadSourceUrl and the indexes are not initialized.

    if (!m_sourceUrl.empty())
    {
        return true;
    }
    else
    {
        for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
        {
            const char* imagePath = nullptr;
            if (this->_resolveStyleProperty(StyleStringProperty::eImageUrl,
                                            static_cast<StyleContainer::State>(i), &imagePath)
                && imagePath && imagePath[0] != '\0')
            {
                return true;
            }
        }
    }

    return false;
}

void Image::_drawContent(float elapsedTime)
{
    // It's not the best way to load the image in draw cycle because the first frame the widget will be empty. But
    // it's good because it will be lazy loaded when the widget appears on the visible area.
    // TODO: We need an option or a method to force the loading.
    this->_loadSourceUrl();

    uint32_t texWidth = 0;
    uint32_t texHeight = 0;
    ImTextureID imguiTexId = 0;
    {
        auto& data = _getData<ImageData>();
        auto lockedData = data.getTextureDataFromState(this->_getStyleState(), true);
        TextureData* textureData = lockedData.second;
        if (!textureData || !textureData->handle)
        {
            return;
        }

        texWidth = textureData->width;
        texHeight = textureData->height;
        if (texWidth == 0 || texHeight == 0)
        {
            return;
        }

        auto* backend = PlatformRegistry::instance().imageBackend();
        if (!backend)
        {
            return;
        }
        imguiTexId = (ImTextureID)(uintptr_t)backend->getImGuiTextureId(*textureData->handle);
        if (imguiTexId == 0)
        {
            return;
        }
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

    uint32_t roundCorner = ImDrawFlags_RoundCornersAll;
    this->_resolveStyleProperty(StyleEnumProperty::eCornerFlag, &roundCorner);

    uint32_t align = static_cast<uint32_t>(this->getAlignment());
    this->_resolveStyleProperty(StyleEnumProperty::eAlignment, &align);
    Alignment alignment = static_cast<Alignment>(align);

    uint32_t fillPolicyStyle = static_cast<uint32_t>(this->getFillPolicy());
    this->_resolveStyleProperty(StyleEnumProperty::eFillPolicy, &fillPolicyStyle);
    FillPolicy fillPolicy = static_cast<FillPolicy>(fillPolicyStyle);

    const ImVec2 imageSize = { static_cast<float>(texWidth), static_cast<float>(texHeight) };
    ImVec2 canvasSize = { this->getComputedContentWidth(), this->getComputedContentHeight() };
    ImVec2 cursorOffset = { 0.0f, 0.0f };
    ImVec2 uvs[2] = { { 0.0f, 0.0f }, { 1.0f, 1.0f } };

    alignImage(alignment, fillPolicy, imageSize, canvasSize, cursorOffset, uvs);

    auto cursor = ImGui::GetCursorScreenPos();
    cursor.x += cursorOffset.x;
    cursor.y += cursorOffset.y;

    ImVec2 rectMax{ cursor.x + canvasSize.x, cursor.y + canvasSize.y };

    if (this->getPixelAligned())
    {
        // Floor it to avoid artifacts
        cursor = ImFloor(cursor);
        rectMax = ImFloor(rectMax);
    }

    // Draw the image
    if (borderRadius == 0.0f)
    {
        ImGui::GetWindowDrawList()->AddImage(imguiTexId, cursor, rectMax, uvs[0], uvs[1], tintColor);
    }
    else
    {
        ImGui::GetWindowDrawList()->AddImageRounded(
            imguiTexId, cursor, rectMax, uvs[0], uvs[1], tintColor, borderRadius, roundCorner);
    }

    // Draw rectangle
    if (borderWidth > 0.0f && borderColor != 0x0)
    {
        // Draw a border on top of rectangle.
        ImGui::GetWindowDrawList()->AddRect(cursor, rectMax, borderColor, borderRadius, roundCorner, borderWidth);
    }
}

void Image::_loadSourceUrl()
{
    auto& data = _getData<ImageData>();
    if (this->getComputedContentWidth() == 0.0f || this->getComputedContentHeight() == 0.0f)
    {
        return;
    }
    else if (data.m_texturesLoaded && (!m_sourceUrl.empty() || !this->_hasStyleUrlChanged()))
    {
        return;
    }

    if (!m_sourceUrl.empty())
    {
        // Get the texture from the property
        for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
        {
            auto state = static_cast<StyleContainer::State>(i);
            _loadSourceUrl(m_sourceUrl, state);
        }

        // Indicate we don't have and don't need anything resolved
        for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
        {
            data.m_styleStateToResolvedStyle[i] = nullptr;
        }
    }
    else
    {
        // Get the texture from the style
        const char* defaultImagePath = nullptr;
        for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
        {
            auto state = static_cast<StyleContainer::State>(i);

            const char* imagePath = nullptr;
            if (this->_resolveStyleProperty(StyleStringProperty::eImageUrl, state, &imagePath))
            {
                // Save resolved style to check if the style is changed later
                data.m_styleStateToResolvedStyle[i] = reinterpret_cast<const void*>(imagePath);
            }
            else
            {
                imagePath = defaultImagePath;
                data.m_styleStateToResolvedStyle[i] = nullptr;
            }

            if (state == StyleContainer::State::eNormal && imagePath)
            {
                defaultImagePath = imagePath;
            }

            _loadSourceUrl(imagePath ? imagePath : std::string{}, state);
        }
    }

    data.m_texturesLoaded = true;
}

void Image::_loadSourceUrl(const std::string sourceUrl, StyleContainer::State state)
{
    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;

    auto* backend = PlatformRegistry::instance().imageBackend();
    if (!backend)
    {
        return;
    }

    size_t textureIndex;
    // Check if we already have it
    {
        auto& data = _getData<ImageData>();
        auto lockedData = data.getTextureDataAndLock();
        auto& lockedTextureData = lockedData.second;

        if (sourceUrl.empty())
        {
            textureIndex = SIZE_MAX;
        }
        else
        {
            auto emplaced = data.m_imageUrlToTextureDataIndex.emplace(
                std::piecewise_construct, std::forward_as_tuple(sourceUrl), std::forward_as_tuple(lockedTextureData.size()));
            // The second arg is a bool denoting whether the insertion took place (true if insertion happened, false if
            // it did not). If the source URL is inserted, we need to create the texture data as well. Otherwise we had
            // the texture data before.
            if (emplaced.second)
            {
                lockedTextureData.push_back(std::make_unique<TextureData>());
            }

            // The index of found texture
            textureIndex = emplaced.first->second;
            OMNIUI_ASSERT(textureIndex != SIZE_MAX);

            if (!lockedTextureData[textureIndex])
            {
                // It happens if the texture was destroyed in past and we need to load it again.
                lockedTextureData[textureIndex] = std::make_unique<TextureData>();
            }
        }

        // The texture that Image had before. (note: lock is held in lockedData above)
        size_t& previousTextureIndex = data.m_textureDataAndMutex.styleStateToIndex[static_cast<size_t>(state)];

        if (previousTextureIndex == textureIndex)
        {
            // Do nothing because the texture is not changed for the current style state.
            return;
        }
        else
        {
            if (textureIndex != SIZE_MAX)
            {
                lockedTextureData[textureIndex]->counter++;
            }

            if (previousTextureIndex != SIZE_MAX)
            {
                // We are here because the texture is changed for the current state. We need to decrease the number of
                // states that need this texture.
                auto& imageDataOfPreviousImage = lockedTextureData[previousTextureIndex];

                OMNIUI_ASSERT(imageDataOfPreviousImage);
                OMNIUI_ASSERT(imageDataOfPreviousImage->counter > 0);

                imageDataOfPreviousImage->counter--;
                if (imageDataOfPreviousImage->counter == 0)
                {
                    // The use count reaches zero and it means there is to style state that is using this texture. We
                    // don't need it anymore and we can delete it.
                    imageDataOfPreviousImage.reset();
                }
            }
        }

        previousTextureIndex = textureIndex;

        if (textureIndex == SIZE_MAX || lockedTextureData[textureIndex]->loadingStarted)
        {
            // Either the image url is empty the loading of the texture is already started. Nothing to do.
            return;
        }

        lockedTextureData[textureIndex]->loadingStarted = true;
    }

    // Delegate the actual loading to the backend.
    auto weakImage = this->weak_from_this();
    int stateInt = static_cast<int>(state);

    auto setTextureData = [weakImage, stateInt](IImageBackend::TextureInfo info) -> bool
    {
        auto image = std::static_pointer_cast<Image>(weakImage.lock());
        if (!image)
        {
            OMNIUI_LOG_INFO("Host widget has been destroyed. Skip texture assignment.");
            return false;
        }

        auto& data = image->_getData<ImageData>();
        auto lockedData =
            data.getTextureDataFromState(static_cast<StyleContainer::State>(stateInt), false);
        if (TextureData* texData = lockedData.second)
        {
            texData->width = info.width;
            texData->height = info.height;
            texData->handle = std::move(info.handle);
            return true;
        }

        return false;
    };

    auto notifyProgress = [weakImage]()
    {
        if (auto image = std::static_pointer_cast<Image>(weakImage.lock()))
        {
            image->_setProgress(1.0f);
        }
    };

    auto result = backend->loadTexture(
        sourceUrl,
        this->getComputedContentWidth(),
        this->getComputedContentHeight(),
        std::move(setTextureData),
        std::move(notifyProgress));

    if (result == IImageBackend::LoadResult::eSyncComplete)
    {
        this->_setProgress(1);
    }
}

bool Image::_hasStyleUrlChanged() const
{
    auto& data = _getData<ImageData>();
    for (size_t i = 0, n = static_cast<size_t>(StyleContainer::State::eCount); i < n; i++)
    {
        if (!data.m_styleStateToResolvedStyle[i])
        {
            continue;
        }

        auto state = static_cast<StyleContainer::State>(i);

        const char* imagePath;
        if (!this->_resolveStyleProperty(StyleStringProperty::eImageUrl, state, &imagePath))
        {
            continue;
        }

        if (data.m_styleStateToResolvedStyle[i] != imagePath)
        {
            return true;
        }
    }

    return false;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
