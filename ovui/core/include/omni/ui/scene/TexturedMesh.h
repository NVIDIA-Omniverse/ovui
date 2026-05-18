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
#include "PolygonMesh.h"
#include "Object.h"

#include <array>
#include <memory>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE
class ImageProvider;
OMNIUI_NAMESPACE_CLOSE_SCOPE

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The shape for free-form textures. It supports both ImageProvider and
 * URL. Basically it's PolygonMesh with the ability to use images.
 *
 * TODO: Tiling:
 * We use the tiling provided by ImGui. In the future we can implement it
 * when we need it.
 *
 * TODO: Alpha behavior:
 * It should behave exactly like sc.Image. We can add a property for it later if
 * we need it.
 */
class OMNIUI_SCENE_CLASS_API TexturedMesh : public PolygonMesh, public ImageHelper
{
    OMNIUI_SCENE_OBJECT(TexturedMesh);

public:
    class TexturedMeshGesturePayload : public PolygonMesh::PolygonMeshGesturePayload
    {
    public:
        // The coords of the intersection in the space of the texture.
        Float u = 0.0;
        Float v = 0.0;
    };

    OMNIUI_SCENE_API
    virtual ~TexturedMesh();

    OMNIUI_SCENE_API
    void intersect(const Vector3 origin,
                   const Vector3 direction,
                   const Vector2 mouse,
                   const Matrix44& projection,
                   const Matrix44& view,
                   GestureState state) override;

    /**
     * @brief Contains all the information about the intersection
     */
    OMNIUI_SCENE_API
    const TexturedMeshGesturePayload* getGesturePayload() const override;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    const TexturedMeshGesturePayload* getGesturePayload(GestureState state) const override;

    /**
     * @brief The texture coordinates.
     *
     * The number of elements corresponds to the face-varying interpolation: One
     * element for each of the face-vertices that define the mesh topology.
     */
    OMNIUI_PROPERTY(std::vector<Vector2>, uvs, GET_VALUE, getUvs, WRITE, setUvs, PROTECTED, NOTIFY, _setUvsChangedFn);

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

protected:
    /**
     * @brief Create with the given URL
     */
    OMNIUI_SCENE_API
    TexturedMesh(const std::string& sourceUrl,
                 const std::vector<Vector2>& uvs,
                 const std::vector<Vector3>& positions,
                 const std::vector<Color4>& colors,
                 const std::vector<uint32_t>& vertexCounts,
                 const std::vector<uint32_t>& vertexIndices,
                 bool legacyFlippedV = true);
 
    /**
     * @brief Create with the given provider
     */
    OMNIUI_SCENE_API
    TexturedMesh(const std::shared_ptr<ImageProvider>& imageProvider,
                 const std::vector<Vector2>& uvs,
                 const std::vector<Vector3>& positions,
                 const std::vector<Color4>& colors,
                 const std::vector<uint32_t>& vertexCounts,
                 const std::vector<uint32_t>& vertexIndices,
                 bool legacyFlippedV = true);

    OMNIUI_SCENE_API
    void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height) override;

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    void _initialize(const std::vector<Vector2>& uvs);
    void _uvsChanged();

    struct TexturedMeshData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
