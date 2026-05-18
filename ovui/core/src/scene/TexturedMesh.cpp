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
#include <omni/ui/platform/Assert.h>

#include <omni/ui/Profile.h>

#include <omni/ui/platform/Log.h>

#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include <omni/ui/ImageProvider/VectorImageProvider.h>
#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Math.h>
#include <omni/ui/scene/TexturedMesh.h>

#include "PolygonMeshData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

struct TexturedMesh::TexturedMeshData : public PolygonMeshData
{
    TexturedMeshData(bool legacyFlippedV)
        : m_lastGesturePayload(std::make_unique<TexturedMeshGesturePayload>())
        , m_legacyFlippedV(legacyFlippedV)
    {}
    ~TexturedMeshData() override
    {
    }

    std::unique_ptr<TexturedMeshGesturePayload> m_lastGesturePayload;
    std::array<std::unique_ptr<TexturedMeshGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;
    const bool m_legacyFlippedV;
};

void TexturedMesh::_initialize(const std::vector<Vector2>& uvs)
{
    // Fallback image width/height when it's not specified
    m_textureWidthCache = 32.0f;
    m_textureHeightCache = 32.0f;

    _setSourceUrlChangedFn(std::bind(&This::_sourceUrlChanged, this));
    _setImageProviderChangedFn(std::bind(&This::_providerChanged, this));

    // Assign change-notification before setUvs call to log warning/error at least once
    if (_getData<TexturedMeshData>().m_legacyFlippedV)
    {
        _setUvsChangedFn(std::bind(&This::_uvsChanged, this));
    }
    setUvs(uvs);

}

TexturedMesh::TexturedMesh(const std::string& sourceUrl,
                           const std::vector<Vector2>& uvs,
                           const std::vector<Vector3>& positions,
                           const std::vector<Color4>& colors,
                           const std::vector<uint32_t>& vertexCounts,
                           const std::vector<uint32_t>& vertexIndices,
                           bool legacyFlippedV)
    : PolygonMesh(positions, colors, vertexCounts, vertexIndices, new TexturedMeshData(legacyFlippedV))
{
    _initialize(uvs);
    setSourceUrl(sourceUrl);
}

TexturedMesh::TexturedMesh(const std::shared_ptr<ImageProvider>& imageProvider,
                           const std::vector<Vector2>& uvs,
                           const std::vector<Vector3>& positions,
                           const std::vector<Color4>& colors,
                           const std::vector<uint32_t>& vertexCounts,
                           const std::vector<uint32_t>& vertexIndices,
                           bool legacyFlippedV)
    : PolygonMesh(positions, colors, vertexCounts, vertexIndices, new TexturedMeshData(legacyFlippedV))
{
    _initialize(uvs);
    setImageProvider(imageProvider);
}

TexturedMesh::~TexturedMesh() = default;


void TexturedMesh::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    PolygonMesh::_preDrawContent(input, projection, view, width, height);
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

void TexturedMesh::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const auto faceCount = this->getVertexCounts().size();

    std::unique_ptr<void* []> imGuiTextures { new void*[faceCount] };
    std::fill(imGuiTextures.get(), imGuiTextures.get() + faceCount, nullptr);
    std::unique_ptr<void* []> resources { new void*[faceCount] };
    std::fill(resources.get(), resources.get() + faceCount, nullptr);

    bool cacheIsDirty = false;
    void* textureGpuReference = nullptr;
    void* managedResources = nullptr;
    this->_prepareDrawContent(projection, view, cacheIsDirty, &textureGpuReference, &managedResources);

    if (textureGpuReference)
    {
        std::fill(imGuiTextures.get(), imGuiTextures.get() + faceCount, textureGpuReference);
    }
    if (managedResources)
    {
        std::fill(resources.get(), resources.get() + faceCount, managedResources);
    }

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        // NOTE: pass m_uvs directly to avoid performance of copy and possible re-flip from getUvs()
        drawList->addPolygonMesh(this->getPositions().data(), this->getColors().data(),
                                 this->getVertexIndices().data(), this->getVertexCounts().data(),
                                 this->getVertexCounts().size(),
                                 m_uvs.data(), imGuiTextures.get(), resources.get());
    }
}

void TexturedMesh::intersect(const Vector3 origin,
                            const Vector3 direction,
                            const Vector2 mouse,
                            const Matrix44& projection,
                            const Matrix44& view,
                            GestureState state)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& data = _getData<TexturedMeshData>();

    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<TexturedMeshGesturePayload>();
    }

    auto& lastGesturePayload = data.m_lastGesturePayload;
    _calculateST(origin, direction, lastGesturePayload->s, lastGesturePayload->t, lastGesturePayload->faceId,
        lastGesturePayload->itemClosestPoint, lastGesturePayload->rayClosestPoint, lastGesturePayload->rayDistance);

    // no intersection
    if (lastGesturePayload->faceId == -1)
    {
        lastGesturePayload->u = -1.0;
        lastGesturePayload->v = -1.0;
    }
    else
    {
        Vector2 st = Vector2{(float)lastGesturePayload->s, (float)lastGesturePayload->t};

        // NOTE: need to use m_uvs directly to avoid performance of copy and possible re-flip from getUvs()
        const auto& uvs = m_uvs;
        Vector2 uv_origin = uvs[0];
        Vector2 uv_x = glm::normalize(uvs[1] - uv_origin);
        Vector2 uv_y;

        const auto& vertexCounts = this->getVertexCounts();
        uint32_t count = vertexCounts[lastGesturePayload->faceId];
        if (count == 3)
            uv_y = glm::normalize(uvs[2] - uv_origin);
        else if (count == 4)
            uv_y = glm::normalize(uvs[3] - uv_origin);

        st -= uv_origin;
        lastGesturePayload->u = glm::dot(st, uv_x);
        lastGesturePayload->v = glm::dot(st, uv_y);

        // Flip v co-ordinate back to legacy space if required
        if (data.m_legacyFlippedV)
        {
            lastGesturePayload->v = Float(1) - lastGesturePayload->v;
        }
    }
    *stateGesturePayload.get() = *lastGesturePayload.get();
}

const TexturedMesh::TexturedMeshGesturePayload* TexturedMesh::getGesturePayload() const
{
    return _getData<TexturedMeshData>().m_lastGesturePayload.get();
}

const TexturedMesh::TexturedMeshGesturePayload* TexturedMesh::getGesturePayload(GestureState state) const
{
    return _getData<TexturedMeshData>().m_itersections[static_cast<uint32_t>(state)].get();
}

void TexturedMesh::_uvsChanged()
{
    OMNIUI_ASSERT(_getData<TexturedMeshData>().m_legacyFlippedV, "_uvsChanged while not requiring a V flip");
    OMNIUI_LOG_WARN("TexturedMesh uvs should be specified in usd coordinate space for better performance and compatibility with Kit 106");

    for (Vector2& uv : m_uvs)
    {
        uv.y = 1.f - uv.y;
    }
}

std::vector<Vector2> TexturedMesh::getUvs() const
{
    if (!_getData<TexturedMeshData>().m_legacyFlippedV)
    {
        return m_uvs;
    }

    OMNIUI_LOG_WARN("TexturedMesh uvs should be specified in usd coordinate space for better performance and compatibility with Kit 106");

    decltype(m_uvs) flippedBack;
    flippedBack.reserve(m_uvs.size());
    for (const Vector2& uv : m_uvs)
    {
        flippedBack.emplace_back(uv.x, 1.f - uv.y);
    }
    return flippedBack;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
