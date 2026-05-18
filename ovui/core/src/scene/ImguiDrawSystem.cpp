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

#include <glm/glm.hpp>
#include <glm/gtc/matrix_access.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <imgui/imgui.h>
#include <omni/ui/Alignment.h>
#include <omni/ui/scene/DrawBuffer.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/ImguiDrawSystem.h>

#include <algorithm>
#include <numeric>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

/**
 * @brief Cut tle line with the plane perpendicular to Z-axis
 *
 * @param p0 point on negative side of Z-axis
 * @param p1 point on positive side of Z-axis
 * @param depth coordinate on Z-axis to cut
 */
static inline Vector4 _zCut(const Vector4& p0, const Vector4& p1, Float depth)
{
    Float l = (p1.z + depth) / (p1.z - p0.z);
    return Vector4{ p1.x - (p1.x - p0.x) * l, p1.y - (p1.y - p0.y) * l, p1.z - (p1.z - p0.z) * l,
                    p1.w - (p1.w - p0.w) * l };
}

/**
 * @brief Apply perspective and output the given point as path.
 */
static inline void _pathLineTo(ImDrawList* drawlist, Vector4 p, const ImVec2& cursor, Float width, Float height)
{
    // Perspective
    p = p / p.w;
    // NDC to Screen space
    p.x = (p.x + (Float)1.0) * (Float).5;
    p.y = (Float)1.0 - (p.y + (Float)1.0) * (Float).5;
    // Apply window size
    p.x *= width;
    p.y *= height;
    // Send to ImGui
    drawlist->PathLineTo({ static_cast<float>(p.x) + cursor.x, static_cast<float>(p.y) + cursor.y });
}

ImguiDrawSystem::ImguiDrawSystem()
    : m_flatPolyCache{ std::make_unique<DrawBuffer>() }, m_flatPointCache{ std::make_unique<DrawBuffer>() }
{
    m_flatPolyCache->setBufferType(DrawBuffer::BufferType::ePolys);
    m_flatPointCache->setBufferType(DrawBuffer::BufferType::ePoints);
}

ImguiDrawSystem::~ImguiDrawSystem()
{
}

void ImguiDrawSystem::setup()
{
}

void ImguiDrawSystem::beginFrame()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    m_flatPolyCache->beginFrame();
    m_flatPointCache->beginFrame();

    // It's important not to recuce capacity here. Clear leaves the capacity of
    // the vector unchanged.
    m_polyDepth.clear();
    m_polySorted.clear();
    m_indexStart.clear();
    m_pointSorted.clear();
}

void ImguiDrawSystem::render(const DrawBuffer* const * buffers,
                             size_t bufferCount,
                             const Matrix44& projection,
                             const Matrix44& view,
                             float width,
                             float height,
                             float dpiScale)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    {
        for (size_t i = 0; i < bufferCount; ++i)
        {
            if (!buffers[i])
            {
                continue;
            }

            const DrawBuffer& buffer = *buffers[i];
            switch (buffer.getBufferType())
            {
            case DrawBuffer::BufferType::ePoints:
                this->_cachePoints(buffer, projection * view, width, height);
                break;
            case DrawBuffer::BufferType::eLines:
                this->_drawLines(buffer, projection * view, width, height, dpiScale);
                break;
            case DrawBuffer::BufferType::ePolys:
                this->_cachePolys(buffer, projection * view, width, height);
                break;
            default:
                break;
            }
        }
    }

    this->_drawPoints(projection * view, width, height, dpiScale);
    this->_drawPolys(projection * view, width, height, dpiScale);

    for (size_t i = 0; i < bufferCount; ++i)
    {
        const DrawBuffer& buffer = *buffers[i];
        switch (buffer.getBufferType())
        {
        case DrawBuffer::BufferType::eTexts:
            this->_drawTexts(buffer, projection * view, width, height, dpiScale);
            break;
        default:
            break;
        }
    }
}

void ImguiDrawSystem::endFrame()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    m_flatPolyCache->endFrame();
    m_flatPointCache->endFrame();
}

void ImguiDrawSystem::destroy()
{
}

void ImguiDrawSystem::_drawLines(
    const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height, float dpiScale) const
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const DrawBuffer::Lines* lines;
    if (!buffer.getLineBuffer(&lines))
    {
        return;
    }

    const Matrix44& transform = buffer.getTransform();
    const Matrix44 pvc = projectionView * transform;

    ImDrawList* drawlist = ImGui::GetWindowDrawList();
    ImVec2 cursor = ImGui::GetCursorScreenPos();

    size_t indexCounter = 0;
    for (size_t vc = 0, nvc = lines->m_vertexCounts.size(); vc < nvc; ++vc)
    {
        size_t vertexCount = lines->m_vertexCounts[vc];

        auto prevPosition = pvc * lines->m_positions[lines->m_vertexIndices[indexCounter]];
        size_t verticesDrawn = 0;
        // Flag to indicate the previous line was cut
        bool prevCut = true;
        bool backCulling = lines->m_flags[vc] & DrawList::LINE_FLAG_BACK_CULLING;
        bool frontCulling = lines->m_flags[vc] & DrawList::LINE_FLAG_FRONT_CULLING;

        const auto& color = lines->m_colors[indexCounter];
        auto thickness = lines->m_thicknesses[indexCounter] * dpiScale;

        for (size_t i = 1; i < vertexCount; ++i)
        {
            auto nextPosition = pvc * lines->m_positions[lines->m_vertexIndices[indexCounter + i]];

            bool cullThisSegment = false;

            if (backCulling || frontCulling)
            {
                Vector3 normal{ 0.0 };

                if (i > 1)
                {
                    auto prevPrevPosition = pvc * lines->m_positions[lines->m_vertexIndices[indexCounter + i - 2]];
                    Vector3 v1 = prevPrevPosition - prevPosition;
                    Vector3 v2 = nextPosition - prevPosition;
                    normal += glm::normalize(glm::cross(v1, glm::cross(v1, v2)));
                }

                if (i < vertexCount - 1)
                {
                    auto nextNextPosition = pvc * lines->m_positions[lines->m_vertexIndices[indexCounter + i + 1]];
                    Vector3 v1 = nextNextPosition - nextPosition;
                    Vector3 v2 = prevPosition - nextPosition;
                    normal += glm::normalize(glm::cross(v1, glm::cross(v1, v2)));
                }

                if (normal[0] != 0.0 || normal[1] != 0.0 || normal[2] != 0.0)
                {
                    // TODO: It's possible it's normalized twice
                    normal = glm::normalize(normal);

                    if (backCulling)
                    {
                        cullThisSegment = normal[2] > 0.0;
                    }

                    if (frontCulling)
                    {
                        cullThisSegment = normal[2] <= 0.0;
                    }
                }
            }

            // Cut lines behind the camera
            constexpr Float depth = -1.0;
            if (cullThisSegment || (prevPosition.z <= depth && nextPosition.z <= depth))
            {
                if (verticesDrawn > 1)
                {
                    drawlist->PathStroke(
                        ImGui::ColorConvertFloat4ToU32({ static_cast<float>(color.r), static_cast<float>(color.g),
                                                         static_cast<float>(color.b), static_cast<float>(color.a) }),
                        false, static_cast<float>(thickness));
                    verticesDrawn = 0;
                }

                // The line is entirely cut
                prevPosition = nextPosition;
                prevCut = true;
                continue;
            }

            if (prevPosition.z < depth)
            {
                // The first point is cut, not the last one
                prevPosition = _zCut(prevPosition, nextPosition, depth);
            }

            if (prevCut)
            {
                // Output the previous point. It's either the first one or the first one after it's cut.
                _pathLineTo(drawlist, prevPosition, cursor, width, height);
                verticesDrawn++;
            }

            if (nextPosition.z < depth)
            {
                // The last point is cut, not the first one one
                prevPosition = _zCut(nextPosition, prevPosition, depth);
                prevCut = true;
            }
            else
            {
                prevPosition = nextPosition;
                prevCut = false;
            }

            _pathLineTo(drawlist, prevPosition, cursor, width, height);
            verticesDrawn++;

            prevPosition = nextPosition;
        }

        if (verticesDrawn > 1)
        {
            drawlist->PathStroke(
                ImGui::ColorConvertFloat4ToU32({ static_cast<float>(color.r), static_cast<float>(color.g),
                                                 static_cast<float>(color.b), static_cast<float>(color.a) }),
                false, static_cast<float>(thickness));
        }
        else if (verticesDrawn == 1)
        {
            drawlist->PathClear();
        }

        indexCounter += vertexCount;
    }
}

void ImguiDrawSystem::_cachePolys(const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height) const
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const DrawBuffer::Polys* polys;
    if (!buffer.getPolyBuffer(&polys))
    {
        return;
    }

    const Matrix44& transform = buffer.getTransform();
    const Matrix44 pvc = projectionView * transform;

    m_flatPolyCache->addPolygonMesh(polys->m_positions.data(), polys->m_colors.data(), polys->m_vertexIndices.data(),
                                    polys->m_vertexCounts.data(), polys->m_vertexCounts.size(), &pvc,
                                    polys->m_uvs.data(), polys->m_textures.data(), polys->m_resources.data());
}

void ImguiDrawSystem::_cachePoints(const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height) const
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const DrawBuffer::Points* points;
    if (!buffer.getPointBuffer(&points))
    {
        return;
    }

    const Matrix44& transform = buffer.getTransform();
    const Matrix44 pvc = projectionView * transform;

    m_flatPointCache->addPoints(
        points->m_positions.data(), points->m_colors.data(), points->m_sizes.data(), points->m_positions.size(), &pvc);
}

void ImguiDrawSystem::_drawPolys(const Matrix44& projectionView, float width, float height, float dpiScale)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const DrawBuffer::Polys* polys;
    if (!m_flatPolyCache || m_flatPolyCache->empty() || !m_flatPolyCache->getPolyBuffer(&polys))
    {
        return;
    }

    // Index to have fast access to m_vertexIndices
    if (m_indexStart.capacity() < polys->m_vertexCounts.size())
    {
        m_indexStart.reserve(polys->m_vertexCounts.size());
    }

    // Cache the depth of each poly
    size_t indexCounter = 0;
    size_t lastVertexCount = 0;
    for (size_t vc = 0, nvc = polys->m_vertexCounts.size(); vc < nvc; ++vc)
    {
        if (vc == 0)
        {
            m_indexStart.push_back(0);
        }
        else
        {
            m_indexStart.push_back(m_indexStart.back() + lastVertexCount);
        }

        lastVertexCount = polys->m_vertexCounts[vc];

        if (lastVertexCount)
        {
            for (size_t i = 0; i < lastVertexCount; ++i, ++indexCounter)
            {
                const auto& position = polys->m_positions[polys->m_vertexIndices[indexCounter]];

                if (i == 0)
                {
                    m_polyDepth.push_back(position.z);
                }
                else
                {
                    m_polyDepth.back() += position.z;
                }
            }

            m_polyDepth.back() = m_polyDepth.back() / lastVertexCount;
        }
    }

    // It's important not to recuce capacity here. Vector capacity is never
    // reduced when resizing to smaller size.
    m_polySorted.resize(m_polyDepth.size());

    // Depth-sorting. It's not perfect and produces artifacts, but it's
    // impossible to have an ideal solution using ImGui because it's 2D. We
    // don't have intersections, and drawing it in ImGui is already a hack.
    std::iota(m_polySorted.begin(), m_polySorted.end(), 0);
    std::sort(m_polySorted.begin(), m_polySorted.end(),
              [this](size_t a, size_t b) { return this->m_polyDepth[a] > this->m_polyDepth[b]; });

    ImDrawList* drawlist = ImGui::GetWindowDrawList();
    ImVec2 cursor = ImGui::GetCursorScreenPos();

    for (size_t polyId : m_polySorted)
    {
        if (m_polyDepth[polyId] <= -1.0)
        {
            continue;
        }

        Color4 color = polys->m_colors[polys->m_vertexIndices[m_indexStart[polyId]]];

        const auto texture = polys->m_textures[polyId];
        // ImGui 1.92 renamed _TextureIdStack -> _TextureStack and now stores ImTextureRef
        // (wrapping ImTextureID = ImU64). Build a ref from the void* texture for comparison
        // and push. PushTextureID remains as an inline alias for PushTexture(ImTextureRef).
        ImTextureRef texRef(static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(texture)));
        const bool pushTextureId =
            texture && (drawlist->_TextureStack.empty() ||
                        texRef.GetTexID() != drawlist->_TextureStack.back().GetTexID());
        auto flagsToRestore = drawlist->Flags;
        if (pushTextureId)
        {
            drawlist->PushTexture(texRef);

            // TODO: It's pretty complicated to do image with AA. We need to find the way later.
            drawlist->Flags &= ~ImDrawListFlags_AntiAliasedFill;
        }

        int vertStartIdx = drawlist->VtxBuffer.Size;

        for (size_t i = 0, n = polys->m_vertexCounts[polyId]; i < n; ++i)
        {
            Vector4 p_transformed = polys->m_positions[polys->m_vertexIndices[m_indexStart[polyId] + i]];

            // TODO: cut lines behind the camera

            // Perspective
            p_transformed = p_transformed / p_transformed.w;

            // NDC to Screen space
            p_transformed.x = (p_transformed.x + (Float)1.0) * (Float).5;
            p_transformed.y = (Float)1.0 - (p_transformed.y + (Float)1.0) * (Float).5;

            p_transformed.x *= width;
            p_transformed.y *= height;

            // TODO: Anti-aliased filling requires points to be in clockwise order.
            drawlist->PathLineTo(
                { static_cast<float>(p_transformed.x) + cursor.x, static_cast<float>(p_transformed.y) + cursor.y });
        }

        drawlist->PathFillConvex(
            ImGui::ColorConvertFloat4ToU32({ static_cast<float>(color.r), static_cast<float>(color.g),
                                             static_cast<float>(color.b), static_cast<float>(color.a) }));

        int vertEndIdx = drawlist->VtxBuffer.Size;

        if (pushTextureId)
        {
            // Overwrite uvs
            ImDrawVert* vertStart = drawlist->VtxBuffer.Data + vertStartIdx;
            ImDrawVert* vertEnd = drawlist->VtxBuffer.Data + vertEndIdx;
            // We need to be sure that ImGui vertices has the same size as UVs we have
            OMNIUI_ASSERT(vertStart + polys->m_vertexCounts[polyId] == vertEnd);
            auto* uvs = &polys->m_uvs[m_indexStart[polyId]];
            for (ImDrawVert* vertex = vertStart; vertex < vertEnd; ++vertex, ++uvs)
            {
                vertex->uv = { static_cast<float>(uvs->x), static_cast<float>(uvs->y) };
                // Flip V coordinate for ImGui
                vertex->uv.y = 1.f - vertex->uv.y;
            }

            drawlist->Flags = flagsToRestore;

            drawlist->PopTexture();
        }
    }
}

void ImguiDrawSystem::_drawPoints(const Matrix44& projectionView, float width, float height, float dpiScale)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const DrawBuffer::Points* points;
    if (!m_flatPointCache || m_flatPointCache->empty() || !m_flatPointCache->getPointBuffer(&points))
    {
        return;
    }

    // It's important not to recuce capacity here. Vector capacity is never
    // reduced when resizing to smaller size.
    m_pointSorted.resize(points->m_positions.size());
    std::iota(m_pointSorted.begin(), m_pointSorted.end(), 0);
    // Depth-sorting
    std::sort(m_pointSorted.begin(), m_pointSorted.end(),
              [points](size_t a, size_t b) { return points->m_positions[a].z > points->m_positions[b].z; });

    ImDrawList* drawlist = ImGui::GetWindowDrawList();
    ImVec2 cursor = ImGui::GetCursorScreenPos();

    for (size_t pointId : m_pointSorted)
    {
        if (points->m_positions[pointId].z <= -1.0)
        {
            continue;
        }

        Vector4 p_transformed = points->m_positions[pointId];

        // Perspective
        p_transformed = p_transformed / p_transformed.w;

        // NDC to Screen space
        p_transformed.x = (p_transformed.x + (Float)1.0) * (Float)0.5;
        p_transformed.y = (Float)1.0 - (p_transformed.y + (Float)1.0) * (Float)0.5;

        p_transformed.x *= width;
        p_transformed.y *= height;

        const auto& color = points->m_colors[pointId];
        auto size = 0.5 * points->m_sizes[pointId] * dpiScale;

        // Rectangle
        drawlist->AddRectFilled(
            { static_cast<float>(p_transformed.x) + cursor.x - static_cast<float>(size),
              static_cast<float>(p_transformed.y) + cursor.y - static_cast<float>(size) },
            { static_cast<float>(p_transformed.x) + cursor.x + static_cast<float>(size),
              static_cast<float>(p_transformed.y) + cursor.y + static_cast<float>(size) },
            ImGui::ColorConvertFloat4ToU32({ static_cast<float>(color.r), static_cast<float>(color.g),
                                             static_cast<float>(color.b), static_cast<float>(color.a) }));
    }
}

void ImguiDrawSystem::_drawTexts(
    const DrawBuffer& buffer, const Matrix44& projectionView, float width, float height, float dpiScale)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    const DrawBuffer::Texts* texts;
    if (!buffer.getTextBuffer(&texts))
    {
        return;
    }

    const Matrix44& transform = buffer.getTransform();
    const Matrix44 pvc = projectionView * transform;

    ImDrawList* drawlist = ImGui::GetWindowDrawList();
    ImVec2 cursor = ImGui::GetCursorScreenPos();

    size_t textCounter = 0;
    for (size_t cc = 0, ncc = texts->m_charactersCounts.size(); cc < ncc; ++cc)
    {
        auto position = pvc * texts->m_positions[cc];

        constexpr Float depth = -1.0;
        if (position.z <= depth)
        {
            continue;
        }

        this->_pushFont(static_cast<float>(texts->m_sizes[cc]));

        // Perspective
        position = position / position.w;
        // NDC to Screen space
        position.x = (position.x + (Float)1.0) * (Float).5;
        position.y = (Float)1.0 - (position.y + (Float)1.0) * (Float).5;
        // Apply window size
        position.x *= width;
        position.y *= height;

        position.x += cursor.x;
        position.y += cursor.y;

        // Alignment
        auto textSize = ImGui::CalcTextSize(
            texts->m_text.data() + textCounter, texts->m_text.data() + textCounter + texts->m_charactersCounts[cc]);
        auto flag = texts->m_flags[cc];
        if (flag & Alignment::eLeft)
        {
            // Nothing to do
        }
        else if (flag & Alignment::eRight)
        {
            position.x -= textSize.x;
        }
        else if (flag & Alignment::eHCenter)
        {
            position.x -= (Float).5 * textSize.x;
        }

        if (flag & Alignment::eTop)
        {
            // Nothing to do
        }
        else if (flag & Alignment::eBottom)
        {
            position.y -= textSize.y;
        }
        else if (flag & Alignment::eVCenter)
        {
            position.y -= (Float).5 * textSize.y;
        }

        const auto& color = texts->m_colors[cc];
        drawlist->AddText(ImVec2{ static_cast<float>(position.x), static_cast<float>(position.y) },
                          ImGui::ColorConvertFloat4ToU32({ static_cast<float>(color.r), static_cast<float>(color.g),
                                                           static_cast<float>(color.b), static_cast<float>(color.a) }),
                          texts->m_text.data() + textCounter,
                          texts->m_text.data() + textCounter + texts->m_charactersCounts[cc]);
        textCounter += texts->m_charactersCounts[cc];

        this->_popFont();
    }
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
