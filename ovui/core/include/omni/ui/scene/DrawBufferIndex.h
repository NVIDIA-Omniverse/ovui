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

#include <algorithm>
#include <array>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief A simple array with BufferType::eCount elements. Every transform can
 * match to several types of bufferrs (Line and Point for example). We use this
 * object to track the index of each type.
 */
class DrawBufferIndex
{
public:
    DrawBufferIndex()
    {
        this->clear();
    }

    size_t& operator[](size_t i)
    {
        return m_index[i];
    }

    const size_t& operator[](size_t i) const
    {
        return m_index[i];
    }

    constexpr size_t size() const
    {
        return static_cast<size_t>(DrawBuffer::BufferType::eCount);
    }

    void clear()
    {
        // Default is SIZE_MAX which means "no buffer"
        std::fill(m_index.begin(), m_index.end(), SIZE_MAX);
        this->setDirty(true);
    }

    bool empty() const
    {
        for (size_t i = 0, n = this->size(); i < n; ++i)
        {
            if ((*this)[i] != SIZE_MAX)
            {
                return false;
            }
        }

        return true;
    }

    bool isContentDirty() const
    {
        return m_contentDirty;
    }

    void setContentDirty(bool dirty)
    {
        m_contentDirty = dirty;
    }

    bool isDescendantDirty() const
    {
        return m_descendantDirty;
    }

    void setDescendantDirty(bool dirty)
    {
        m_descendantDirty = dirty;
    }

    bool isTransformDirty() const
    {
        return m_transformDirty;
    }

    void setTransformDirty(bool dirty)
    {
        m_transformDirty = dirty;
    }

    bool anyDirty() const
    {
        return m_contentDirty || m_descendantDirty || m_transformDirty;
    }

    void setDirty(bool dirty)
    {
        m_contentDirty = dirty;
        m_descendantDirty = dirty;
        m_transformDirty = dirty;
    }

private:
    typedef std::array<size_t, static_cast<size_t>(DrawBuffer::BufferType::eCount)> _BufferIndexArray;
    _BufferIndexArray m_index;

    bool m_contentDirty = true;
    bool m_descendantDirty = true;
    bool m_transformDirty = true;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
