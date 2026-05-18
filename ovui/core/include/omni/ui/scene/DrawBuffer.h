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

#include "Api.h"
#include "Math.h"
#include "TransformBasis.h"

#include <omni/ui/Property.h>

#include <memory>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_USING_DIRECTIVE

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The InvisibleButton widget provides a transparent command button.
 */
class OMNIUI_SCENE_CLASS_API DrawBuffer
{
public:
    typedef uint32_t DirtyBits;
    static constexpr DirtyBits kDirtyBitTransform = (1 << 0);

    struct Buffer
    {
        virtual ~Buffer();

        std::vector<Vector4> m_positions;
        std::vector<Color4> m_colors;

        // Hashing
        size_t m_positionsHash = 0;
        size_t m_colorsHash = 0;

        // Dirty Bits
        static constexpr DirtyBits kDirtyBitPositions = (1 << 1);
        static constexpr DirtyBits kDirtyBitColors = (1 << 2);
        static constexpr DirtyBits kDirtyBitAll = UINT32_MAX;
    };
    struct Points : public Buffer
    {
        ~Points() override;

        std::vector<float> m_sizes;

        // Hashing
        size_t m_sizesHash = 0;

        // Dirty Bits
        static constexpr DirtyBits kDirtyBitSizes = (1 << 3);
        static constexpr DirtyBits kDirtyBitAll =
            kDirtyBitTransform | kDirtyBitPositions | kDirtyBitColors | kDirtyBitSizes;
    };
    struct Lines : public Buffer
    {
        ~Lines() override;

        std::vector<float> m_thicknesses;
        std::vector<uint32_t> m_vertexCounts;
        std::vector<uint32_t> m_vertexIndices;
        std::vector<uint32_t> m_flags;

        // Hashing
        size_t m_thicknessesHash = 0;
        size_t m_vertexCountsHash = 0;
        size_t m_vertexIndicesHash = 0;
        size_t m_flagsHash = 0;

        // Dirty Bits
        static constexpr DirtyBits kDirtyBitThicknesses = (1 << 3);
        static constexpr DirtyBits kDirtyBitVertexCounts = (1 << 4);
        static constexpr DirtyBits kDirtyBitVertexIndices = (1 << 5);
        static constexpr DirtyBits kDirtyBitFlags = (1 << 6);
        static constexpr DirtyBits kDirtyBitAll = kDirtyBitTransform | kDirtyBitPositions | kDirtyBitColors |
                                                  kDirtyBitThicknesses | kDirtyBitVertexCounts |
                                                  kDirtyBitVertexIndices | kDirtyBitFlags;
    };
    struct Polys : public Buffer
    {
        ~Polys() override;

        std::vector<uint32_t> m_vertexCounts;
        std::vector<uint32_t> m_vertexIndices;
        std::vector<Vector2> m_uvs;
        std::vector<const void*> m_textures;
        std::vector<const void*> m_resources;

        // Hashing
        size_t m_vertexCountsHash = 0;
        size_t m_vertexIndicesHash = 0;
        size_t m_uvsHash = 0;
        size_t m_texturesHash = 0;
        // Resources are linked to textures. It's impossible that resources
        // changed and textures didn't change.

        // Dirty Bits
        static constexpr DirtyBits kDirtyBitVertexCounts = (1 << 3);
        static constexpr DirtyBits kDirtyBitVertexIndices = (1 << 4);
        static constexpr DirtyBits kDirtyBitUvs = (1 << 5);
        static constexpr DirtyBits kDirtyBitTextures = (1 << 6);
        static constexpr DirtyBits kDirtyBitAll = kDirtyBitTransform | kDirtyBitPositions | kDirtyBitColors |
                                                  kDirtyBitVertexCounts | kDirtyBitVertexIndices | kDirtyBitUvs |
                                                  kDirtyBitTextures;
    };
    struct Texts : public Buffer
    {
        ~Texts() override;

        std::vector<char> m_text;
        std::vector<uint32_t> m_charactersCounts;
        std::vector<float> m_sizes;
        std::vector<uint32_t> m_flags;

        // Hashing
        size_t m_textHash = 0;
        size_t m_charactersCountsHash = 0;
        size_t m_sizesHash = 0;
        size_t m_flagsHash = 0;

        // Dirty Bits
        static constexpr DirtyBits kDirtyBitText = (1 << 3);
        static constexpr DirtyBits kDirtyBitCharactersCounts = (1 << 4);
        static constexpr DirtyBits kDirtyBitSizes = (1 << 5);
        static constexpr DirtyBits kDirtyBitFlags = (1 << 6);
        static constexpr DirtyBits kDirtyBitAll = kDirtyBitTransform | kDirtyBitPositions | kDirtyBitColors |
                                                  kDirtyBitText | kDirtyBitCharactersCounts | kDirtyBitSizes |
                                                  kDirtyBitFlags;
    };

    enum class BufferType : size_t
    {
        eLines = 0,
        ePoints,
        ePolys,
        eTexts,
        eCount
    };

    OMNIUI_SCENE_API
    DrawBuffer();

    OMNIUI_SCENE_API
    DrawBuffer(DrawBuffer&&);

    OMNIUI_SCENE_API
    ~DrawBuffer();

    OMNIUI_SCENE_API
    void beginFrame();

    OMNIUI_SCENE_API
    void endFrame();

    OMNIUI_SCENE_API
    bool empty() const;

    OMNIUI_SCENE_API
    void addLine(const Vector3& begin, const Vector3& end, const Color4& color, float thickness);

    OMNIUI_SCENE_API
    void addText(const std::string& text, const Vector3& point, const Color4& color, float size, uint32_t flag);

    OMNIUI_SCENE_API
    void addPolygonLines(const Vector3* points,
                         const Color4* colors,
                         const float* thicknesses,
                         const uint32_t* vertexIndices,
                         const uint32_t* vertexCounts,
                         const uint32_t* flags,
                         size_t vertexCountSize);

    OMNIUI_SCENE_API
    void addRect(Float width, Float height, const Color4& color, const void* texture);

    OMNIUI_SCENE_API
    void addPolygonMesh(const Vector4* points,
                        const Color4* colors,
                        const uint32_t* vertexIndices,
                        const uint32_t* vertexCounts,
                        size_t vertexCountSize,
                        const Matrix44* transform = nullptr,
                        const Vector2* uvs = nullptr,
                        const void* const* textures = nullptr,
                        const void* const* resources = nullptr);

    OMNIUI_SCENE_API
    void addPolygonMesh(const Vector3* points,
                        const Color4* colors,
                        const uint32_t* vertexIndices,
                        const uint32_t* vertexCounts,
                        size_t vertexCountSize,
                        const Matrix44* transform = nullptr,
                        const Vector2* uvs = nullptr,
                        const void* const* textures = nullptr,
                        const void* const* resources = nullptr);

    OMNIUI_SCENE_API
    void addPoints(const Vector4* positions,
                   const Color4* colors,
                   const float* sizes,
                   size_t pointCount,
                   const Matrix44* transform = nullptr);

    OMNIUI_SCENE_API
    void addPoints(const Vector4* positions,
                   const Color4& color,
                   float size,
                   size_t pointCount,
                   const Matrix44* transform = nullptr);

    OMNIUI_SCENE_API
    void addPoints(const Vector3* positions,
                   const Color4* colors,
                   const float* sizes,
                   size_t pointCount,
                   const Matrix44* transform = nullptr);

    OMNIUI_SCENE_API
    void addPoints(const Vector3* positions,
                   const Color4& color,
                   float size,
                   size_t pointCount,
                   const Matrix44* transform = nullptr);

    OMNIUI_SCENE_API
    bool getPointBuffer(const Points** points) const;

    OMNIUI_SCENE_API
    bool getLineBuffer(const Lines** lines) const;

    OMNIUI_SCENE_API
    bool getPolyBuffer(const Polys** polys) const;

    OMNIUI_SCENE_API
    bool getTextBuffer(const Texts** texts) const;

    OMNIUI_SCENE_API
    BufferType getBufferType() const;

    OMNIUI_SCENE_API
    void setBufferType(BufferType bufferType);

    /**
     * @brief Returns what changed since the last call.
     *
     * It knows what's changed with hashing all the arrays.
     *
     * @return OMNIUI_SCENE_API
     */
    OMNIUI_SCENE_API
    DirtyBits getDirtyBits() const;

    void setCached(bool dirty);
    void setHashed(bool hashed) const;

    OMNIUI_PROPERTY(Matrix44, transform, DEFAULT, Matrix44{ (Float)1.0 }, READ, getTransform, WRITE, setTransform);
    OMNIUI_PROPERTY(std::shared_ptr<TransformBasis>, basis, DEFAULT, nullptr, READ_VALUE, getBasis, WRITE, setBasis);

private:
    size_t calVertexIndexSize(const uint32_t* vertexCounts, size_t vertexCountSize);
    size_t calPointSize(const uint32_t* vertexIndices, size_t vertexIndexSize);

    template <typename PointsType>
    void _addPolygonMesh(const PointsType* points,
                         const Vector4* colors,
                         const uint32_t* vertexIndices,
                         const uint32_t* vertexCounts,
                         size_t vertexCountSize,
                         const Matrix44* transform = nullptr,
                         const Vector2* uvs = nullptr,
                         const void* const* textures = nullptr,
                         const void* const* resources = nullptr);

    mutable size_t m_transformHash = 0;
    BufferType m_bufferType = BufferType::eCount;
    std::unique_ptr<Buffer> m_buffer;
    bool m_cached = false;
    mutable bool m_hashed = false;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
