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
#include <omni/ui/platform/Log.h>

#include <omni/ui/scene/DrawBuffer.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/ImguiDrawSystem.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

DrawList::DrawList() = default;

DrawList::~DrawList() = default;

void DrawList::destroy()
{
    m_buffers.clear();
}

void DrawList::addLine(const Vector3& begin, const Vector3& end, const Color4& color, float thickness)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::eLines)];
    buffer->addLine(begin, end, color, thickness);
}

void DrawList::addRect(Float width, Float height, const Color4& color, const void* texture)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::ePolys)];
    buffer->addRect(width, height, color, texture);
}

void DrawList::addText(const std::string& text, const Vector3& point, const Color4& color, float size, uint32_t flag)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::eTexts)];
    buffer->addText(text, point, color, size, flag);
}

void DrawList::addPolygonLines(const Vector3* points,
                               const Color4* colors,
                               const float* thicknesses,
                               const uint32_t* vertexIndices,
                               const uint32_t* vertexCounts,
                               const uint32_t* flags,
                               size_t vertexCountSize)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::eLines)];
    buffer->addPolygonLines(points, colors, thicknesses, vertexIndices, vertexCounts, flags, vertexCountSize);
}

void DrawList::addPolygonMesh(const Vector4* points,
                              const Color4* colors,
                              const uint32_t* vertexIndices,
                              const uint32_t* vertexCounts,
                              size_t vertexCountSize,
                              const Vector2* uvs,
                              const void* const* textures,
                              const void* const* resources)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::ePolys)];
    buffer->addPolygonMesh(points, colors, vertexIndices, vertexCounts, vertexCountSize,
                           nullptr, uvs, textures, resources);
}

void DrawList::addPolygonMesh(const Vector3* points,
                              const Color4* colors,
                              const uint32_t* vertexIndices,
                              const uint32_t* vertexCounts,
                              size_t vertexCountSize,
                              const Vector2* uvs,
                              const void* const* textures,
                              const void* const* resources)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::ePolys)];
    buffer->addPolygonMesh(points, colors, vertexIndices, vertexCounts, vertexCountSize,
                           nullptr, uvs, textures, resources);
}

void DrawList::addPoints(const Vector4* positions, const Color4* colors, const float* sizes, size_t pointCount)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::ePoints)];
    buffer->addPoints(positions, colors, sizes, pointCount);
}

void DrawList::addPoints(const Vector4* positions, const Color4& color, float size, size_t pointCount)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::ePoints)];
    buffer->addPoints(positions, color, size, pointCount);
}

void DrawList::addPoints(const Vector3* positions, const Color4* colors, const float* sizes, size_t pointCount)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::ePoints)];
    buffer->addPoints(positions, colors, sizes, pointCount);
}

void DrawList::addPoints(const Vector3* positions, const Color4& color, float size, size_t pointCount)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& buffer = m_buffers[this->_getBufferIndex(DrawBuffer::BufferType::ePoints)];
    buffer->addPoints(positions, color, size, pointCount);
}

void DrawList::beginTransform(const Matrix44& transform, const DrawBufferIndex& index, std::shared_ptr<TransformBasis> basis)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    m_currentBufferStack.push_back(index);

    // If there is a basis provided, then we start the transform over from there
    // so functionally it is like resetting the stack, except we preserve the
    // stack underneath.
    if (m_transformStack.empty() || bool(basis))
    {
        m_transformStack.push_back(transform);
        m_basisStack.push_back(basis);
    }
    else
    {
        // When there is no basis and this isn't the first transform,
        // accumulate the transform and push whatever the most-recent basis was.
        m_transformStack.push_back(m_transformStack.back() * transform);
        m_basisStack.push_back(m_basisStack.back());
    }

    // Update transforms
    for (size_t i = 0, n = index.size(); i < n; ++i)
    {
        if (index[i] != SIZE_MAX)
        {
            auto& current = m_buffers[index[i]];
            if (current && (current->empty() || index.isTransformDirty()))
            {
                current->setTransform(m_transformStack.back());
                current->setBasis(m_basisStack.back());
            }
        }
    }
}

DrawBufferIndex DrawList::endTransform()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    DrawBufferIndex index = m_currentBufferStack.back();

    m_currentBufferStack.pop_back();
    m_transformStack.pop_back();
    m_basisStack.pop_back();

    // Clean up buffers
    for (size_t i = 0, n = index.size(); i < n; ++i)
    {
        if (index[i] != SIZE_MAX)
        {
            auto& current = m_buffers[index[i]];
            if (current && current->empty())
            {
                // We are here because in past the current buffer was valid, and now
                // there is no data in it. We kill it so the next time someone else
                // will reuse this place.
                current = nullptr;
                // And we mark that this index doesn't have index anymore.
                index[i] = SIZE_MAX;
            }
        }
    }

    return index;
}

void DrawList::beginFrame()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    this->beginTransform(Matrix44{ (Float)1.0 }, m_rootBufferIndex);

    for (auto& buffer : m_buffers)
    {
        if (buffer)
        {
            buffer->beginFrame();
        }
    }

    m_maxBufferIndex = 0;
}

void DrawList::endFrame()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    for (auto& buffer : m_buffers)
    {
        if (buffer)
        {
            buffer->endFrame();
        }
    }

    m_outputBuffers.clear();
    m_outputBuffers.reserve(m_outputBuffers.size());

    // Get only valid buffers
    for (auto& buffer : m_buffers)
    {
        if (buffer && !buffer->empty())
        {
            m_outputBuffers.push_back(buffer.get());
        }
    }

    m_outputData.buffers = m_outputBuffers.empty() ? nullptr : m_outputBuffers.data();
    m_outputData.bufferCount = m_outputBuffers.size();

    m_rootBufferIndex = this->endTransform();
}

void DrawList::clearBuffers(DrawBufferIndex& index)
{
    if (m_buffers.empty())
    {
        return;
    }

    // Clear buffers
    for (size_t i = 0, n = index.size(); i < n; ++i)
    {
        if (index[i] != SIZE_MAX)
        {
            auto& current = m_buffers[index[i]];
            if (current)
            {
                current = nullptr;
                index[i] = SIZE_MAX;
            }
        }
    }
}

const DrawData& DrawList::getDrawData() const
{
    return m_outputData;
}

size_t DrawList::getBufferCount() const
{
    return m_buffers.size();
}

size_t DrawList::_getBufferIndex(DrawBuffer::BufferType bufferType)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    size_t& index = m_currentBufferStack.back()[static_cast<size_t>(bufferType)];
    if (index == SIZE_MAX)
    {
        // Find an empty one.
        for (size_t i = 0; i < m_buffers.size(); ++i)
        {
            if (!m_buffers[i])
            {
                m_buffers[i] = std::make_unique<DrawBuffer>();
                index = i;
                break;
            }
        }

        if (index == SIZE_MAX)
        {
            // Couldn't find. Create new.
            index = m_buffers.size();
            if (m_buffers.size() <= index)
            {
                m_buffers.push_back(std::make_unique<DrawBuffer>());
            }
        }

        OMNIUI_ASSERT(index != SIZE_MAX);

        // We either found empty or created a new one. Set its type.
        std::unique_ptr<DrawBuffer>& buffer = m_buffers[index];
        buffer->setBufferType(bufferType);
        buffer->setTransform(m_transformStack.back());

        if (!m_basisStack.empty())
        {
            buffer->setBasis(m_basisStack.back());
        }

    }

    return index;
}

DrawBufferIndex& DrawList::getRootBufferIndex()
{
    return m_rootBufferIndex;
}

void DrawList::setDrawBufferCacheState(DrawBufferIndex& index)
{
    for (size_t i = 0, n = index.size(); i < n; ++i)
    {
        if (index[i] != SIZE_MAX)
        {
            auto& current = m_buffers[index[i]];

            const bool dirty = index.isContentDirty();
            // Set the cached and hashed states asymmetrically: cached
            // controls the data transfer from shapes to draw buffer and hashed decides whether to do hashing in the
            // draw system render(). Due to the lazy creating of the draw system, the cache state could be reset while
            // the draw buffer has not been hashed.
            current->setCached(!dirty);
            if (dirty)
            {
                current->setHashed(false);
            }
        }
    }
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
