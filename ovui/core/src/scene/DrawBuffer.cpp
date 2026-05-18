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

#include <algorithm>
#include <iterator>
#include <numeric>

static constexpr uint64_t kProfilerMask = 1;

/**
 * @brief Combine hashes like in boost::hash_combine
 */
template <typename T>
inline void _hashCombine(size_t& seed, const T& v)
{
    // boost::hash_combine
    std::hash<T> hasher;
    seed ^= hasher(v) + 0x9e3779b9 + (seed << 6) + (seed >> 2);
}

// Hashers for the types
namespace std
{
template <>
struct hash<omni::ui::scene::Vector4>
{
    auto operator()(omni::ui::scene::Vector4 const& value) const -> size_t
    {
        size_t seed = 0;
        _hashCombine(seed, value.x);
        _hashCombine(seed, value.y);
        _hashCombine(seed, value.z);
        _hashCombine(seed, value.w);
        return seed;
    }
};

template <>
struct hash<omni::ui::scene::Vector2>
{
    auto operator()(omni::ui::scene::Vector2 const& value) const -> size_t
    {
        size_t seed = 0;
        _hashCombine(seed, value.x);
        _hashCombine(seed, value.y);
        return seed;
    }
};

template <>
struct hash<omni::ui::scene::Matrix44>
{
    auto operator()(omni::ui::scene::Matrix44 const& value) const -> size_t
    {
        size_t seed = 0;
        for (omni::ui::scene::Matrix44::length_type i = 0; i < 4; ++i)
        {
            for (omni::ui::scene::Matrix44::length_type j = 0; j < 4; ++j)
            {
                _hashCombine(seed, value[i][j]);
            }
        }
        return seed;
    }
};
}

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief Hashes the std::vector
 */
template <typename A>
inline size_t _hashVector(std::vector<A> const& vec)
{
    size_t seed = vec.size();
    for (auto& i : vec)
    {
        _hashCombine(seed, i);
    }
    return seed;
}

/**
 * @every subclass of Buffer need a virtual destructor, even 'default'
 */
DrawBuffer::Buffer::~Buffer() = default;
DrawBuffer::Points::~Points() = default;
DrawBuffer::Lines::~Lines() = default;
DrawBuffer::Polys::~Polys() = default;
DrawBuffer::Texts::~Texts() = default;

/**
 * @brief Repetetive macro to hash vector, compare with the vrevious hash value
 * and return the given bit if the hash is changed.
 */
template <typename T>
static DrawBuffer::DirtyBits _hashIt(size_t& hash, std::vector<T> const& vectorToHash, DrawBuffer::DirtyBits bit)
{
    size_t current = _hashVector(vectorToHash);
    if (current != hash)
    {
        hash = current;
        return bit;
    }

    return 0;
}

DrawBuffer::DrawBuffer() = default;

DrawBuffer::DrawBuffer(DrawBuffer&&) = default;

DrawBuffer::~DrawBuffer() = default;

void DrawBuffer::beginFrame()
{
    if (!m_buffer)
    {
        return;
    }
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // Do not clear the data if this buffer is cached.
    if (m_cached)
    {
        return;
    }

    // Clear doesn't change the capacity of std::vector. We expect that the
    // buffer has the same size every frame.
    m_buffer->m_positions.clear();
    m_buffer->m_colors.clear();

    switch (this->getBufferType())
    {
    case BufferType::ePoints:
    {
        auto buffer = reinterpret_cast<Points*>(m_buffer.get());
        buffer->m_sizes.clear();
    }
    break;
    case BufferType::eLines:
    {
        auto buffer = reinterpret_cast<Lines*>(m_buffer.get());
        buffer->m_thicknesses.clear();
        buffer->m_vertexCounts.clear();
        buffer->m_vertexIndices.clear();
        buffer->m_flags.clear();
    }
    break;
    case BufferType::ePolys:
    {
        auto buffer = reinterpret_cast<Polys*>(m_buffer.get());
        buffer->m_vertexCounts.clear();
        buffer->m_vertexIndices.clear();
        buffer->m_uvs.clear();
        buffer->m_resources.clear();
        buffer->m_textures.clear();
    }
    break;
    case BufferType::eTexts:
    {
        auto buffer = reinterpret_cast<Texts*>(m_buffer.get());
        buffer->m_text.clear();
        buffer->m_charactersCounts.clear();
        buffer->m_sizes.clear();
        buffer->m_flags.clear();
    }
    break;
    default:
        break;
    }
}

void DrawBuffer::endFrame()
{
}

bool DrawBuffer::empty() const
{
    return !m_buffer || m_buffer->m_positions.empty();
}

void DrawBuffer::addLine(const Vector3& begin, const Vector3& end, const Color4& color, float thickness)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::eLines);

    auto buffer = reinterpret_cast<Lines*>(m_buffer.get());

    uint32_t firstIndex = static_cast<uint32_t>(buffer->m_positions.size());

    _ensureCapacity(buffer->m_positions, buffer->m_positions.size() + 2);
    _ensureCapacity(buffer->m_colors, buffer->m_colors.size() + 2);
    _ensureCapacity(buffer->m_thicknesses, buffer->m_thicknesses.size() + 2);
    _ensureCapacity(buffer->m_vertexIndices, buffer->m_vertexIndices.size() + 2);

    buffer->m_positions.emplace_back(begin, 1.0);
    buffer->m_positions.emplace_back(end, 1.0);
    buffer->m_colors.push_back(color);
    buffer->m_colors.push_back(color);
    buffer->m_thicknesses.push_back(thickness);
    buffer->m_thicknesses.push_back(thickness);
    buffer->m_vertexCounts.push_back(2);
    buffer->m_flags.push_back(0);

    std::generate_n(std::back_inserter(buffer->m_vertexIndices), 2, [&]() { return firstIndex++; });
}

void DrawBuffer::addText(const std::string& text, const Vector3& point, const Color4& color, float size, uint32_t flag)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::eTexts);

    Texts* buffer = reinterpret_cast<Texts*>(m_buffer.get());

    size_t textLen = text.size();

    buffer->m_positions.emplace_back(point, 1.0);
    buffer->m_colors.push_back(color);

    _ensureCapacity(buffer->m_text, buffer->m_text.size() + textLen);
    std::copy(text.begin(), text.end(), std::back_inserter(buffer->m_text));

    buffer->m_charactersCounts.push_back(static_cast<uint32_t>(textLen));
    buffer->m_sizes.push_back(size);
    buffer->m_flags.push_back(flag);
}

// TODO: We need to template addPolygonMesh. It's 90% the same.
void DrawBuffer::addPolygonLines(const Vector3* points,
                                 const Color4* colors,
                                 const float* thicknesses,
                                 const uint32_t* vertexIndices,
                                 const uint32_t* vertexCounts,
                                 const uint32_t* flags,
                                 size_t vertexCountSize)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::eLines);

    auto buffer = reinterpret_cast<Lines*>(m_buffer.get());

    size_t vertexIndexSize = calVertexIndexSize(vertexCounts, vertexCountSize);
    size_t pointSize = calPointSize(vertexIndices, vertexIndexSize);

    uint32_t firstIndex = static_cast<uint32_t>(buffer->m_positions.size());

    std::transform(points, points + pointSize, std::back_inserter(buffer->m_positions), [](const Vector3& a) {
        return Vector4{ a, 1.0 };
    });
    std::copy(colors, colors + vertexIndexSize, std::back_inserter(buffer->m_colors));
    std::copy(thicknesses, thicknesses + vertexIndexSize, std::back_inserter(buffer->m_thicknesses));
    std::copy(vertexCounts, vertexCounts + vertexCountSize, std::back_inserter(buffer->m_vertexCounts));

    if (flags)
    {
        std::copy(flags, flags + vertexCountSize, std::back_inserter(buffer->m_flags));
    }
    else
    {
        size_t first = buffer->m_flags.size();
        buffer->m_flags.resize(buffer->m_flags.size() + vertexCountSize);
        std::fill(buffer->m_flags.begin() + first, buffer->m_flags.end(), 0);
    }

    // Transforming vertexIndices to the new merged buffer
    _ensureCapacity(buffer->m_vertexIndices, buffer->m_vertexIndices.size() + vertexIndexSize);
    for (size_t i = 0; i < vertexIndexSize; ++i)
    {
        buffer->m_vertexIndices.push_back(firstIndex + vertexIndices[i]);
    }
}

void DrawBuffer::addRect(Float width, Float height, const Color4& color, const void* texture)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::ePolys);

    auto buffer = reinterpret_cast<Polys*>(m_buffer.get());

    Float halfWidth = width * (Float).5;
    Float halfHeight = height * (Float).5;

    uint32_t firstIndex = static_cast<uint32_t>(buffer->m_positions.size());

    _ensureCapacity(buffer->m_positions, buffer->m_positions.size() + 4);
    buffer->m_positions.emplace_back(-halfWidth, -halfHeight, 0.0, 1.0);
    buffer->m_positions.emplace_back(halfWidth, -halfHeight, 0.0, 1.0);
    buffer->m_positions.emplace_back(halfWidth, halfHeight, 0.0, 1.0);
    buffer->m_positions.emplace_back(-halfWidth, halfHeight, 0.0, 1.0);

    _ensureCapacity(buffer->m_colors, buffer->m_colors.size() + 4);
    std::generate_n(std::back_inserter(buffer->m_colors), 4, [&]() { return color; });

    buffer->m_vertexCounts.push_back(4);

    _ensureCapacity(buffer->m_vertexIndices, buffer->m_vertexIndices.size() + 4);
    std::generate_n(std::back_inserter(buffer->m_vertexIndices), 4, [&]() { return firstIndex++; });

    _ensureCapacity(buffer->m_uvs, buffer->m_uvs.size() + 4);
    // TODO: is the order correct?
    buffer->m_uvs.emplace_back(0.0, 0.0);
    buffer->m_uvs.emplace_back(1.0, 0.0);
    buffer->m_uvs.emplace_back(1.0, 1.0);
    buffer->m_uvs.emplace_back(0.0, 1.0);

    buffer->m_textures.push_back(texture);
}

static Vector4 toVector4(const Vector4& v)
{
    return v;
}

static Vector4 toVector4(const Vector3& v)
{
    return Vector4(v, 1);
}

template <typename PointsType>
void DrawBuffer::_addPolygonMesh(const PointsType* points,
                                 const Vector4* colors,
                                 const uint32_t* vertexIndices,
                                 const uint32_t* vertexCounts,
                                 size_t vertexCountSize,
                                 const Matrix44* transform,
                                 const Vector2* uvs,
                                 const void* const* textures,
                                 const void* const* resources)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::ePolys);

    Polys* buffer = reinterpret_cast<Polys*>(m_buffer.get());

    const size_t vertexIndexSize = calVertexIndexSize(vertexCounts, vertexCountSize);
    const size_t pointSize = calPointSize(vertexIndices, vertexIndexSize);

    // TODO: Possible truncation for large buffers
    const uint32_t firstIndex = static_cast<uint32_t>(buffer->m_positions.size());

    // Reserve all required space known now
    buffer->m_positions.reserve(buffer->m_positions.size() + vertexCountSize);
    buffer->m_vertexCounts.reserve(buffer->m_vertexCounts.size() + vertexCountSize);
    buffer->m_textures.reserve(buffer->m_textures.size() + vertexCountSize);
    buffer->m_resources.reserve(buffer->m_resources.size() + vertexCountSize);
    buffer->m_uvs.reserve(buffer->m_uvs.size() + vertexCountSize);

    std::copy(colors, colors + vertexIndexSize, std::back_inserter(buffer->m_colors));
    std::copy(vertexCounts, vertexCounts + vertexCountSize, std::back_inserter(buffer->m_vertexCounts));

    // the points should be arranged in the order of m_vertexIndices and possibly transformed
    if (transform)
    {
        for (size_t i = 0; i < vertexIndexSize; ++i)
        {
            buffer->m_positions.emplace_back(*transform * toVector4(points[vertexIndices[i]]));
        }
    }
    else
    {
        for (size_t i = 0; i < vertexIndexSize; ++i)
        {
            buffer->m_positions.emplace_back(toVector4(points[vertexIndices[i]]));
        }
    }

    // Transforming vertexIndices to the new merged buffer
    _ensureCapacity(buffer->m_vertexIndices, buffer->m_vertexIndices.size() + vertexIndexSize);
    for (uint32_t i = 0; i < vertexIndexSize; ++i)
    {
        buffer->m_vertexIndices.push_back(firstIndex + i);
    }

    if (uvs && textures)
    {
        std::copy(textures, textures + vertexCountSize, std::back_inserter(buffer->m_textures));
        std::copy(resources, resources + vertexCountSize, std::back_inserter(buffer->m_resources));
        std::copy(uvs, uvs + vertexIndexSize, std::back_inserter(buffer->m_uvs));
    }
    else
    {
        // Fill with 0
        {
            size_t first = buffer->m_textures.size();
            buffer->m_textures.resize(buffer->m_textures.size() + vertexCountSize);
            std::fill(buffer->m_textures.begin() + first, buffer->m_textures.end(), nullptr);
        }
        {
            size_t first = buffer->m_resources.size();
            buffer->m_resources.resize(buffer->m_resources.size() + vertexCountSize);
            std::fill(buffer->m_resources.begin() + first, buffer->m_resources.end(), nullptr);
        }
        {
            size_t first = buffer->m_uvs.size();
            buffer->m_uvs.resize(buffer->m_uvs.size() + vertexIndexSize);
            std::fill(buffer->m_uvs.begin() + first, buffer->m_uvs.end(), Vector2{ 0.0 });
        }
    }
}

void DrawBuffer::addPolygonMesh(const Vector4* points,
                                const Vector4* colors,
                                const uint32_t* vertexIndices,
                                const uint32_t* vertexCounts,
                                size_t vertexCountSize,
                                const Matrix44* transform,
                                const Vector2* uvs,
                                const void* const* textures,
                                const void* const* resources)
{
    _addPolygonMesh(points, colors, vertexIndices, vertexCounts,
                    vertexCountSize, transform, uvs, textures, resources);
}

void DrawBuffer::addPolygonMesh(const Vector3* points,
                                const Vector4* colors,
                                const uint32_t* vertexIndices,
                                const uint32_t* vertexCounts,
                                size_t vertexCountSize,
                                const Matrix44* transform,
                                const Vector2* uvs,
                                const void* const* textures,
                                const void* const* resources)
{
    _addPolygonMesh(points, colors, vertexIndices, vertexCounts,
                    vertexCountSize, transform, uvs, textures, resources);
}

size_t DrawBuffer::calVertexIndexSize(const uint32_t* vertexCounts, size_t vertexCountSize)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    size_t vertexIndexSize = std::accumulate(vertexCounts, vertexCounts + vertexCountSize, 0);
    return vertexIndexSize;
}

size_t DrawBuffer::calPointSize(const uint32_t* vertexIndices, size_t vertexIndexSize)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    size_t maxIndex = *std::max_element(vertexIndices, vertexIndices + vertexIndexSize);
    return maxIndex + 1;
}

void DrawBuffer::addPoints(
    const Vector4* positions, const Color4* colors, const float* sizes, size_t pointCount, const Matrix44* transform)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::ePoints);

    auto buffer = reinterpret_cast<Points*>(m_buffer.get());

    if (transform)
    {
        std::transform(positions, positions + pointCount, std::back_inserter(buffer->m_positions),
                       [transform](const Vector4& a) { return *transform * a; });
    }
    else
    {
        std::copy(positions, positions + pointCount, std::back_inserter(buffer->m_positions));
    }

    std::copy(colors, colors + pointCount, std::back_inserter(buffer->m_colors));
    std::copy(sizes, sizes + pointCount, std::back_inserter(buffer->m_sizes));
}

void DrawBuffer::addPoints(
    const Vector4* positions, const Color4& color, float size, size_t pointCount, const Matrix44* transform)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::ePoints);

    auto buffer = reinterpret_cast<Points*>(m_buffer.get());

    if (transform)
    {
        std::transform(positions, positions + pointCount, std::back_inserter(buffer->m_positions),
                       [transform](const Vector4& a) { return *transform * a; });
    }
    else
    {
        std::copy(positions, positions + pointCount, std::back_inserter(buffer->m_positions));
    }

    if (buffer->m_colors.capacity() < buffer->m_positions.size())
    {
        buffer->m_colors.reserve(buffer->m_positions.size());
    }
    if (buffer->m_sizes.capacity() < buffer->m_positions.size())
    {
        buffer->m_sizes.reserve(buffer->m_positions.size());
    }

    for (size_t i = 0; i < pointCount; ++i)
    {
        buffer->m_colors.push_back(color);
        buffer->m_sizes.push_back(size);
    }
}

void DrawBuffer::addPoints(
    const Vector3* positions, const Color4* colors, const float* sizes, size_t pointCount, const Matrix44* transform)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::ePoints);

    auto buffer = reinterpret_cast<Points*>(m_buffer.get());

    if (transform)
    {
        std::transform(
            positions, positions + pointCount, std::back_inserter(buffer->m_positions), [transform](const Vector3& a) {
                return *transform * Vector4{ a, 1.0 };
            });
    }
    else
    {
        std::transform(positions, positions + pointCount, std::back_inserter(buffer->m_positions), [](const Vector3& a) {
            return Vector4{ a, 1.0 };
        });
    }

    std::copy(colors, colors + pointCount, std::back_inserter(buffer->m_colors));
    std::copy(sizes, sizes + pointCount, std::back_inserter(buffer->m_sizes));
}

void DrawBuffer::addPoints(
    const Vector3* positions, const Color4& color, float size, size_t pointCount, const Matrix44* transform)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    OMNIUI_ASSERT(m_buffer);
    OMNIUI_ASSERT(this->getBufferType() == BufferType::ePoints);

    auto buffer = reinterpret_cast<Points*>(m_buffer.get());

    if (transform)
    {
        std::transform(
            positions, positions + pointCount, std::back_inserter(buffer->m_positions), [transform](const Vector3& a) {
                return *transform * Vector4{ a, 1.0 };
            });
    }
    else
    {
        std::transform(positions, positions + pointCount, std::back_inserter(buffer->m_positions), [](const Vector3& a) {
            return Vector4{ a, 1.0 };
        });
    }

    if (buffer->m_colors.capacity() < buffer->m_positions.size())
    {
        buffer->m_colors.reserve(buffer->m_positions.size());
    }
    if (buffer->m_sizes.capacity() < buffer->m_positions.size())
    {
        buffer->m_sizes.reserve(buffer->m_positions.size());
    }

    for (size_t i = 0; i < pointCount; ++i)
    {
        buffer->m_colors.push_back(color);
        buffer->m_sizes.push_back(size);
    }
}

bool DrawBuffer::getPointBuffer(const Points** points) const
{
    if (this->getBufferType() != BufferType::ePoints)
    {
        return false;
    }

    *points = reinterpret_cast<Points*>(m_buffer.get());
    return true;
}

bool DrawBuffer::getLineBuffer(const Lines** lines) const
{
    if (this->getBufferType() != BufferType::eLines)
    {
        return false;
    }

    *lines = reinterpret_cast<Lines*>(m_buffer.get());
    return true;
}

bool DrawBuffer::getPolyBuffer(const Polys** polys) const
{
    if (this->getBufferType() != BufferType::ePolys)
    {
        return false;
    }

    *polys = reinterpret_cast<Polys*>(m_buffer.get());
    return true;
}

bool DrawBuffer::getTextBuffer(const Texts** texts) const
{
    if (this->getBufferType() != BufferType::eTexts)
    {
        return false;
    }

    *texts = reinterpret_cast<Texts*>(m_buffer.get());
    return true;
}

DrawBuffer::BufferType DrawBuffer::getBufferType() const
{
    return m_bufferType;
}

void DrawBuffer::setBufferType(BufferType bufferType)
{
    if (bufferType == m_bufferType)
    {
        return;
    }

    switch (bufferType)
    {
    case BufferType::ePoints:
        m_buffer = std::make_unique<Points>();
        break;
    case BufferType::eLines:
        m_buffer = std::make_unique<Lines>();
        break;
    case BufferType::ePolys:
        m_buffer = std::make_unique<Polys>();
        break;
    case BufferType::eTexts:
        m_buffer = std::make_unique<Texts>();
        break;
    default:
        break;
    }

    m_bufferType = bufferType;
}

DrawBuffer::DirtyBits DrawBuffer::getDirtyBits() const
{
    if (!m_buffer)
    {
        return 0;
    }

    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    DirtyBits dirty = 0;

    // Hashing transform
    std::hash<Matrix44> hasher;
    size_t transformHash = hasher(this->getTransform());
    if (transformHash != m_transformHash)
    {
        m_transformHash = transformHash;
        dirty |= kDirtyBitTransform;
    }

    // Skip hashing if the buffer is cached and hashed.
    if (m_cached && m_hashed)
    {
        return dirty;
    }

    // Hashing base arrays
    dirty |= _hashIt(m_buffer->m_colorsHash, m_buffer->m_colors, Buffer::kDirtyBitColors);
    dirty |= _hashIt(m_buffer->m_positionsHash, m_buffer->m_positions, Buffer::kDirtyBitPositions);

    // Hashing everything else depending on the type
    switch (m_bufferType)
    {
    case BufferType::ePoints:
    {
        Points* buffer = reinterpret_cast<Points*>(m_buffer.get());
        dirty |= _hashIt(buffer->m_sizesHash, buffer->m_sizes, Points::kDirtyBitSizes);
        if (dirty == Points::kDirtyBitAll)
        {
            dirty = Buffer::kDirtyBitAll;
        }

        break;
    }
    case BufferType::eLines:
    {
        Lines* buffer = reinterpret_cast<Lines*>(m_buffer.get());
        dirty |= _hashIt(buffer->m_thicknessesHash, buffer->m_thicknesses, Lines::kDirtyBitThicknesses);
        dirty |= _hashIt(buffer->m_vertexCountsHash, buffer->m_vertexCounts, Lines::kDirtyBitVertexCounts);
        dirty |= _hashIt(buffer->m_vertexIndicesHash, buffer->m_vertexIndices, Lines::kDirtyBitVertexIndices);
        dirty |= _hashIt(buffer->m_flagsHash, buffer->m_flags, Lines::kDirtyBitFlags);
        if (dirty == Lines::kDirtyBitAll)
        {
            dirty = Buffer::kDirtyBitAll;
        }

        break;
    }
    case BufferType::ePolys:
    {
        Polys* buffer = reinterpret_cast<Polys*>(m_buffer.get());
        dirty |= _hashIt(buffer->m_vertexCountsHash, buffer->m_vertexCounts, Polys::kDirtyBitVertexCounts);
        dirty |= _hashIt(buffer->m_vertexIndicesHash, buffer->m_vertexIndices, Polys::kDirtyBitVertexIndices);
        dirty |= _hashIt(buffer->m_uvsHash, buffer->m_uvs, Polys::kDirtyBitUvs);
        dirty |= _hashIt(buffer->m_texturesHash, buffer->m_textures, Polys::kDirtyBitTextures);
        if (dirty == Polys::kDirtyBitAll)
        {
            dirty = Buffer::kDirtyBitAll;
        }

        break;
    }
    case BufferType::eTexts:
    {
        Texts* buffer = reinterpret_cast<Texts*>(m_buffer.get());
        dirty |= _hashIt(buffer->m_textHash, buffer->m_text, Texts::kDirtyBitText);
        dirty |= _hashIt(buffer->m_charactersCountsHash, buffer->m_charactersCounts, Texts::kDirtyBitCharactersCounts);
        dirty |= _hashIt(buffer->m_sizesHash, buffer->m_sizes, Texts::kDirtyBitSizes);
        dirty |= _hashIt(buffer->m_flagsHash, buffer->m_flags, Texts::kDirtyBitFlags);
        if (dirty == Texts::kDirtyBitAll)
        {
            dirty = Buffer::kDirtyBitAll;
        }

        break;
    }
    default:
        break;
    }

    if (m_cached)
    {
        this->setHashed(true);
    }
    
    return dirty;
}

void DrawBuffer::setCached(bool cached)
{
    m_cached = cached;
}

void DrawBuffer::setHashed(bool hashed) const
{
    m_hashed = hashed;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
