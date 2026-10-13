// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "Transform.h"
#include <cstdint>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/** Application-owned immutable selection data. Scene UI never interprets it.
 * Retained frames may release it on a renderer thread: do not retain UI objects
 * or require the originating scene to exist in its destructor.
 */
struct SelectionData
{
    virtual ~SelectionData() = default;
};

struct SelectionLabel
{
    uint64_t id = 0;
    std::shared_ptr<const SelectionData> data;
};

/** Optional selection label for descendant draw buffers.
 *
 * Identifiers are opaque to Scene UI. The application owns their meaning and
 * must not reuse an identifier within the same immutable data snapshot while a
 * retained result can reference it. Zero marks descendants unselectable.
 * Nested groups override their parent; ordinary transforms inherit its label.
 * This annotation does not install gestures or change drawing/selection itself.
 */
class OMNIUI_SCENE_CLASS_API SelectionGroup : public Transform
{
    OMNIUI_SCENE_OBJECT(SelectionGroup);
public:
    OMNIUI_SCENE_API
    uint64_t getSelectionId() const;
    OMNIUI_SCENE_API
    void setSelectionId(uint64_t id);
    OMNIUI_SCENE_API
    std::shared_ptr<const SelectionData> getSelectionData() const;
    /** Null inherits the nearest ancestor's data. A new snapshot invalidates
     * labels without rebuilding shape geometry. */
    OMNIUI_SCENE_API
    void setSelectionData(std::shared_ptr<const SelectionData> data);

protected:
    OMNIUI_SCENE_API
    explicit SelectionGroup(uint64_t id = 0);
    OMNIUI_SCENE_API
    void _preDrawContent(const MouseInput&, const Matrix44&, const Matrix44&, float, float) override;
    OMNIUI_SCENE_API
    void _drawContent(const Matrix44&, const Matrix44&) override;

private:
    uint64_t m_selectionId = 0;
    std::shared_ptr<const SelectionData> m_selectionData;
};

class DrawBuffer;

/** Borrowed buffer identity, valid only until the next scene draw/destruction.
 * A renderer must snapshot the labels alongside its retained frame resources;
 * these pointers are not lifetime leases for a later asynchronous query.
 */
struct SelectionDrawBuffer
{
    const DrawBuffer* buffer;
    uint64_t id;
    std::shared_ptr<const SelectionData> data;

    bool operator==(const SelectionDrawBuffer& other) const
    {
        return buffer == other.buffer && id == other.id && data == other.data;
    }
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
