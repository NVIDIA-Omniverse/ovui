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

#pragma once

#include "ImageHelper.h"
#include "Rectangle.h"

#include <memory>
#include <string>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class OMNIUI_SCENE_CLASS_API Image : public Rectangle, public ImageHelper
{
    OMNIUI_SCENE_OBJECT(Image);

public:
    enum class FillPolicy : uint8_t
    {
        eStretch = 0,
        ePreserveAspectFit,
        ePreserveAspectCrop
    };

    OMNIUI_SCENE_API
    virtual ~Image();

    /**
     * @brief This property holds the image URL. It can be an `omni:` path, a `file:` path, a direct path or the path
     * relative to the application root directory.
     */
    OMNIUI_PROPERTY(
        std::string, sourceUrl, READ, getSourceUrl, WRITE, setSourceUrl, PROTECTED, NOTIFY, _setSourceUrlChangedFn);

    /**
     * @brief This property holds the image provider. It can be an `omni:` path, a `file:` path, a direct path or the
     * path relative to the application root directory.
     */
    OMNIUI_PROPERTY(std::shared_ptr<ImageProvider>,
                    imageProvider,
                    READ,
                    getImageProvider,
                    WRITE,
                    setImageProvider,
                    PROTECTED,
                    NOTIFY,
                    _setImageProviderChangedFn);

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
                    PROTECTED,
                    NOTIFY,
                    _setFillPolicyChangedFn);

protected:
    /**
     * @brief Created an image with the given URL
     */
    OMNIUI_SCENE_API
    Image(const std::string& sourceUrl, Float width = 1.0, Float height = 1.0);

    /**
     * @brief Created an image with the given provider
     */
    OMNIUI_SCENE_API
    Image(const std::shared_ptr<ImageProvider>& imageProvider, Float width = 1.0, Float height = 1.0);

    /**
     * @brief Created an empty image
     */
    OMNIUI_SCENE_API
    Image(Float width = 1.0, Float height = 1.0);

    OMNIUI_SCENE_API
    void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height) override;

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    void _rebuildCache() override;

private:
    struct ImageData;

    void _initialize(Float width, Float height);
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
