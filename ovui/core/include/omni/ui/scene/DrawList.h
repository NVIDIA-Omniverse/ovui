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
#include "DrawBuffer.h"
#include "DrawBufferIndex.h"
#include "Math.h"

#include <cstddef>
#include <memory>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class AbstractDrawSystem;

struct DrawData
{
    DrawBuffer** buffers = nullptr;
    size_t bufferCount = 0;

    operator bool() const
    {
        return buffers != nullptr && bufferCount != 0;
    }
};

/**
 * @brief The InvisibleButton widget provides a transparent command button.
 */
class OMNIUI_SCENE_CLASS_API DrawList
{
public:
    enum LINE_FLAGS
    {
        LINE_FLAG_NONE = 0x0,
        LINE_FLAG_BACK_CULLING = 0x1 << 0,
        LINE_FLAG_FRONT_CULLING = 0x1 << 1,
    };

    OMNIUI_SCENE_API
    DrawList();

    OMNIUI_SCENE_API
    ~DrawList();

    void destroy();

    void addLine(const Vector3& begin, const Vector3& end, const Color4& color, float thickness);
    void addRect(Float width, Float height, const Color4& color, const void* texture);
    void addText(const std::string& text, const Vector3& point, const Color4& color, float size, uint32_t flag);

    void addPolygonLines(const Vector3* points,
                         const Color4* colors,
                         const float* thicknesses,
                         const uint32_t* vertexIndices,
                         const uint32_t* vertexCounts,
                         const uint32_t* flags,
                         size_t vertexCountSize);

    void addPolygonMesh(const Vector4* points,
                        const Color4* colors,
                        const uint32_t* vertexIndices,
                        const uint32_t* vertexCounts,
                        size_t vertexCountSize,
                        const Vector2* uvs = nullptr,
                        const void* const* textures = nullptr,
                        const void* const* resources = nullptr);

    void addPolygonMesh(const Vector3* points,
                        const Color4* colors,
                        const uint32_t* vertexIndices,
                        const uint32_t* vertexCounts,
                        size_t vertexCountSize,
                        const Vector2* uvs = nullptr,
                        const void* const* textures = nullptr,
                        const void* const* resources = nullptr);

    void addPoints(const Vector4* positions, const Color4* colors, const float* sizes, size_t pointCount);
    void addPoints(const Vector4* positions, const Color4& color, float size, size_t pointCount);
    void addPoints(const Vector3* positions, const Color4* colors, const float* sizes, size_t pointCount);
    void addPoints(const Vector3* positions, const Color4& color, float size, size_t pointCount);

    void beginTransform(const Matrix44& matrix,
                        const DrawBufferIndex& index,
                        std::shared_ptr<TransformBasis> basis = nullptr);
    DrawBufferIndex endTransform();
    void beginFrame();
    void endFrame();

    /**
     * @brief Clears the buffers of the given index. We use it when destroying items.
     */
    void clearBuffers(DrawBufferIndex& index);

    const DrawData& getDrawData() const;

    /**
     * @brief Return the number of buffers used. Using for unit testing.
     */
    size_t getBufferCount() const;

    DrawBufferIndex& getRootBufferIndex();

    void setDrawBufferCacheState(DrawBufferIndex& drawBufferIndex);

private:
    size_t _getBufferIndex(DrawBuffer::BufferType bufferType);

    std::vector<DrawBufferIndex> m_currentBufferStack;
    size_t m_maxBufferIndex;
    std::vector<Matrix44> m_transformStack;
    std::vector<std::shared_ptr<TransformBasis>> m_basisStack;

    std::vector<std::unique_ptr<DrawBuffer>> m_buffers;

    std::vector<DrawBuffer*> m_outputBuffers;
    DrawData m_outputData;

    DrawBufferIndex m_rootBufferIndex;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
