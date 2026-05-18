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

#include "Alignment.h"
#include "ImageProvider/ImageProvider.h"
#include "Widget.h"

#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The Image widget displays an image.
 *
 * The source of the image is specified as a URL using the source property. By default, specifying the width and height
 * of the item causes the image to be scaled to that size. This behavior can be changed by setting the fill_mode
 * property, allowing the image to be stretched or scaled instead. The property alignment controls where to align the
 * scaled image.
 */
class OMNIUI_CLASS_API ImageWithProvider : public Widget
{
    OMNIUI_OBJECT(ImageWithProvider)

public:
    enum class FillPolicy : uint8_t
    {
        eStretch = 0,
        ePreserveAspectFit,
        ePreserveAspectCrop
    };

    OMNIUI_API
    ~ImageWithProvider() override;

    OMNIUI_API
    void destroy() override;

    /**
     * @brief Reimplemented. Called when the style or the parent style is changed.
     */
    OMNIUI_API
    void onStyleUpdated() override;

    /**
     * @brief Force call `ImageProvider::prepareDraw` to ensure the next draw
     * call the image is loaded. It can be used to load the image for a hidden
     * widget or to set the rasterization resolution.
     */
    OMNIUI_API
    void prepareDraw(float width, float height);

    /**
     * @brief This property holds the alignment of the image when the fill policy is ePreserveAspectFit or
     * ePreserveAspectCrop.
     * By default, the image is centered.
     */
    OMNIUI_PROPERTY(Alignment, alignment, DEFAULT, Alignment::eCenter, READ, getAlignment, WRITE, setAlignment);

    /**
     * @brief Define what happens when the source image has a different size than the item.
     */
    OMNIUI_PROPERTY(FillPolicy,
                    fillPolicy,
                    DEFAULT,
                    FillPolicy::ePreserveAspectFit,
                    READ,
                    getFillPolicy,
                    WRITE,
                    setFillPolicy,
                    NOTIFY,
                    setFillPolicyChangedFn);

    /**
     * @brief Prevents image blurring when it's placed to fractional position (like x=0.5, y=0.5)
     */
    OMNIUI_PROPERTY(bool, pixelAligned, DEFAULT, false, READ, getPixelAligned, WRITE, setPixelAligned);

    // TODO: Image rotation
    // TODO: Right now, it's useless because we load the image in the background, and when the object is created, the
    // texture is not loaded. There is no way to wait for the texture. We need to add a method to force load. And we
    // will be able to use texture dimensions as a read-only property. It will help us to achieve

protected:
    /**
     * @brief Construct image with given ImageProvider. If the ImageProvider is nullptr, it gets the image URL from
     * styling.
     */
    OMNIUI_API
    ImageWithProvider(std::shared_ptr<ImageProvider> imageProvider);

    /**
     * @brief Construct image with given url. If the url is empty, it gets the image URL from styling.
     */
    OMNIUI_API
    ImageWithProvider(const std::string& url = {});


    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    // The mutex for the texture operations, because we load the texture in the background.
    std::mutex m_textureMutex;

    void _populateImageProvidersFromStyles();
    std::shared_ptr<ImageProvider>& _createImageProviderFromUrl(const char* url);
    void _calcTextureIndex();

    // Returns true if the url from the style is changed since the image is loaded.
    bool _hasStyleUrlChanged() const;

    // Flag to check all the textures if it's necessary to reload them.
    bool m_texturesLoaded = false;

    // It is the cache of preloaded textures. We need it because we can switch the texture depending on the widget style
    // state. It can be a separate texture for hovered, disabled, selected, etc. widget. To switch the texture fast, we
    // preload them for all the states. To be sure that the same texture is not loaded twice, we keep them in a separate
    // vector, and we keep the index of the texture per style state. To know which texture is already loaded, we keep
    // the map name to the texture index.
    // Index of the texture per style state
    std::array<size_t, static_cast<size_t>(StyleContainer::State::eCount)> m_styleStateToTextureDataIndex;
    // Resolved style. We need it to know if style shade is changed. It's void*
    // to indicate that it can't be used as a string andit can only be used to
    // check if the style became dirty.
    std::array<const void*, static_cast<size_t>(StyleContainer::State::eCount)> m_styleStateToResolvedStyle;
    // Index of the texture per filename
    std::unordered_map<std::string, size_t> m_imageUrlToTextureDataIndex;

    bool m_updateStyleImages = true;
    bool m_overrideStyleImages = false;

    // Texture data for all the loaded textures
    struct TextureData
    {
        // Removes it from the GPU.
        ~TextureData();

        // Flag to reload the texture.
        bool loadingStarted = false;

        // We delete TextureData when the use count reaches zero.
        size_t counter = 0;

        std::shared_ptr<ImageProvider> imageProvider = nullptr;
    };
    std::vector<std::unique_ptr<TextureData>> m_textureDataArray;
    std::vector<std::shared_ptr<ImageProvider>> m_createdImageProviders;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
