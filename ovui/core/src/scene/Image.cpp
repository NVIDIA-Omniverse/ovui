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

#include <omni/ui/platform/Assert.h>

#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include <omni/ui/ImageProvider/VectorImageProvider.h>
#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Image.h>
#include <omni/ui/scene/Math.h>

#include "RectangleData.h"

#include <numeric>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct Image::ImageData : public Rectangle::RectangleData
{
    ~ImageData() override = default;

    std::vector<Vector2> m_cachedUvs;
};

template <typename T>
static void _scale(T& first, T& second, Float scale)
{
    T half = (first + second) * (Float).5;
    first = half + (first - half) * scale;
    second = half + (second - half) * scale;
}

void Image::_initialize(Float width, Float height)
{
    _setSourceUrlChangedFn(std::bind(&This::_sourceUrlChanged, this));
    _setImageProviderChangedFn(std::bind(&This::_providerChanged, this));
    _setFillPolicyChangedFn(std::bind(&This::_providerChanged, this));

    // Fallback image width/height when it's not specified
    m_textureWidthCache = std::max(static_cast<float>(width), 32.0f);
    m_textureHeightCache = std::max(static_cast<float>(height), 32.0f);
}

Image::Image(const std::string& sourceUrl, Float width, Float height)
    : Rectangle(width, height, new ImageData)
{
    _initialize(width, height);
    setSourceUrl(sourceUrl);
}

Image::Image(const std::shared_ptr<ImageProvider>& imageProvider, Float width, Float height)
    : Rectangle(width, height, new ImageData)
{
    _initialize(width, height);
    setImageProvider(imageProvider);
}

Image::Image(Float width, Float height)
    : Image("", width, height)
{
}

Image::~Image()
{
}

void Image::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    Rectangle::_preDrawContent(input, projection, view, width, height);
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void Image::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    // Extract texture from m_imageProvider
    void* texture[] = { nullptr };
    void* resource[] = { nullptr };

    bool cacheIsDirty = false;
    this->_prepareDrawContent(projection, view, cacheIsDirty, texture, resource);

    if (cacheIsDirty)
    {
        this->_dirtyCache();
    }
    this->_rebuildCache();

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        auto& data = _getData<ImageData>();
        drawList->addPolygonMesh(data.m_cachedPoints.data(), data.m_cachedColors.data(), data.m_cachedVertexIndices.data(),
                                 data.m_cachedVertexCounts.data(), data.m_cachedVertexCounts.size(),
                                 data.m_cachedUvs.data(), texture, resource);
    }
}

void Image::_rebuildCache()
{
    auto& data = _getData<ImageData>();
    if (!data.m_cacheIsDirty)
    {
        return;
    }

    // Build Rectangle
    Rectangle::_rebuildCache();

    // Override vertex count
    data.m_cachedVertexCounts[0] = 4;

    // Build UVs
    data.m_cachedUvs.clear();
    _ensureCapacity(data.m_cachedUvs, 4);

    Float rectangleAspect = this->getHeight() / this->getWidth();
    Float imageAspect = m_textureWidthCache > 0 && m_textureHeightCache > 0 ?
                            static_cast<Float>(m_textureHeightCache) / static_cast<Float>(m_textureWidthCache) :
                            (Float)1.0;

    Float widthMin = 0.0;
    Float widthMax = 1.0;
    Float heightMin = 0.0;
    Float heightMax = 1.0;

    if (m_textureWidthCache > 0 && m_textureHeightCache > 0)
    {
        if (this->getFillPolicy() == FillPolicy::ePreserveAspectCrop)
        {
            if (rectangleAspect < imageAspect)
            {
                // Scale UV height
                Float aspect = rectangleAspect / imageAspect;
                _scale(heightMin, heightMax, aspect);
            }
            else
            {
                // Scale UV width
                Float aspect = imageAspect / rectangleAspect;
                _scale(widthMin, widthMax, aspect);
            }
        }
        else if (this->getFillPolicy() == FillPolicy::ePreserveAspectFit)
        {
            if (rectangleAspect < imageAspect)
            {
                // Scale width
                Float aspect = rectangleAspect / imageAspect;
                switch (this->getAxis())
                {
                case 0:
                    _scale(data.m_cachedPoints[0].y, data.m_cachedPoints[2].y, aspect);
                    _scale(data.m_cachedPoints[1].y, data.m_cachedPoints[3].y, aspect);

                    break;
                default:
                    _scale(data.m_cachedPoints[0].x, data.m_cachedPoints[2].x, aspect);
                    _scale(data.m_cachedPoints[1].x, data.m_cachedPoints[3].x, aspect);

                    break;
                }
            }
            else
            {
                // Scale height
                Float aspect = imageAspect / rectangleAspect;
                switch (this->getAxis())
                {
                case 0:
                case 1:
                    _scale(data.m_cachedPoints[0].z, data.m_cachedPoints[2].z, aspect);
                    _scale(data.m_cachedPoints[1].z, data.m_cachedPoints[3].z, aspect);

                    break;
                default:
                    _scale(data.m_cachedPoints[0].y, data.m_cachedPoints[2].y, aspect);
                    _scale(data.m_cachedPoints[1].y, data.m_cachedPoints[3].y, aspect);

                    break;
                };
            }
        }
    }

    data.m_cachedUvs.emplace_back(widthMax, heightMin);
    data.m_cachedUvs.emplace_back(widthMax, heightMax);
    data.m_cachedUvs.emplace_back(widthMin, heightMax);
    data.m_cachedUvs.emplace_back(widthMin, heightMin);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
