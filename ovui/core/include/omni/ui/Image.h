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
class OMNIUI_CLASS_API Image : public Widget
{
    OMNIUI_OBJECT(Image)

public:
    enum class FillPolicy : uint8_t
    {
        eStretch = 0,
        ePreserveAspectFit,
        ePreserveAspectCrop
    };

    OMNIUI_API
    ~Image() override;

    OMNIUI_API
    void destroy() override;

    /**
     * @brief Reimplemented. Called when the style or the parent style is changed.
     */
    OMNIUI_API
    void onStyleUpdated() override;

    /**
     * @brief Returns true if the image has non empty sourceUrl obtained through the property or the style.
     */
    OMNIUI_API
    bool hasSourceUrl() const;

    /**
     * @brief This property holds the image URL. It can be an `omni:` path, a `file:` path, a direct path or the path
     * relative to the application root directory.
     */
    OMNIUI_PROPERTY(std::string, sourceUrl, READ, getSourceUrl, WRITE, setSourceUrl, NOTIFY, setSourceUrlChangedFn);

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

    /**
     * @brief The progress of the image loading.
     *
     * TODO: For now we only have two states, 0.0 and 1.0
     */
    OMNIUI_PROPERTY(
        float, progress, DEFAULT, 0.0f, READ, getProgress, NOTIFY, setProgressChangedFn, PROTECTED, WRITE, _setProgress);

protected:
    /**
     * @brief Construct image with given url. If the url is empty, it gets the image URL from styling.
     */
    OMNIUI_API
    Image(const std::string& sourceUrl = {});


    /**
     * @brief the default constructor will need to get the image URL from styling
     */
    // OMNIUI_API
    // Image();

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct TextureData;
    struct SourceUrlLoader;
    struct ImageData;

    /**
     * @brief Check if it's necessary to load new textures and load them for all the style states.
     */
    void _loadSourceUrl();

    /**
     * @brief Load the given texture for the given style state. If the texture was loaded before, it just modifies the
     * indexes without reloading.
     */
    void _loadSourceUrl(const std::string sourceUrl, StyleContainer::State state);

    // Returns true if the url from the style is changed since the image is loaded.
    bool _hasStyleUrlChanged() const;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
