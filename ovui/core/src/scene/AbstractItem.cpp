/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/Profile.h>

#include <omni/ui/scene/AbstractItem.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/Scene.h>

#include "AbstractItemData.h"
#include "DragFollow.h"

#include <atomic>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

namespace
{
std::atomic<uint64_t> s_writeCounter{ 0 };
} // namespace

AbstractItem::AbstractItemData::~AbstractItemData()
{
}

AbstractItem::AbstractItem(AbstractItemData* dataPtr)
    : m_itemData(dataPtr ? dataPtr : new AbstractItemData)
{
}

AbstractItem::~AbstractItem()
{
    this->destroy();
}

void AbstractItem::destroy()
{
    this->_setSceneView(nullptr);
    this->setScene(nullptr);
    this->_setParent(nullptr);
    this->destroyCallbacks();
}

void AbstractItem::preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    if (this->isVisible())
    {
        OMNIUI_PROFILE_VERBOSE_FUNCTION;
        this->_preDrawContent(input, projection, view, width, height);
    }
    else
    {
        m_itemData->m_skipPreDraw = true;
    }
}

void AbstractItem::drawContent(const Matrix44& projection, const Matrix44& view)
{
    if (!m_itemData->m_skipPreDraw && this->isVisible() && this->needDrawContent())
    {
        OMNIUI_PROFILE_VERBOSE_FUNCTION;
        this->_drawContent(projection, view);
    }
}

void AbstractItem::postDrawContent(const Matrix44& projection, const Matrix44& view)
{
    // If preDrawContent was called always call postDrawContent.
    // visibility can mutate between these calls, so do not check it.
    if (!m_itemData->m_skipPreDraw /* && this->isVisible() */)
    {
        OMNIUI_PROFILE_VERBOSE_FUNCTION;
        this->_postDrawContent(projection, view);
    }
    else
    {
        // Reset
        m_itemData->m_skipPreDraw = false;
    }
}

Vector3 AbstractItem::transformSpace(Space fromSpace, Space toSpace, const Vector3& point) const
{
    const auto& parent = this->getParent();
    if (parent)
    {
        OMNIUI_PROFILE_VERBOSE_FUNCTION;
        return parent->transformSpace(fromSpace, toSpace, point);
    }

    return point;
}

Vector4 AbstractItem::transformSpace(Space fromSpace, Space toSpace, const Vector4& vector) const
{
    const auto& parent = this->getParent();
    if (parent)
    {
        OMNIUI_PROFILE_VERBOSE_FUNCTION;
        return parent->transformSpace(fromSpace, toSpace, vector);
    }

    return vector;
}

bool AbstractItem::computeVisibility() const
{
    return this->isVisible() && (!this->getParent() || this->getParent()->computeVisibility());
}

void AbstractItem::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
}

void AbstractItem::_postDrawContent(const Matrix44& projection, const Matrix44& view)
{
}

DrawList* AbstractItem::_getDrawList() const
{
    const omni::ui::scene::Scene* scene = this->_getScene();
    if (scene)
    {
        return scene->_getDrawList();
    }


    return nullptr;
}

void AbstractItem::forceDirty(DirtyReason reason)
{
    // A content change that starts at this item is a write to it. The redraw of a transform that changed
    // (kDirtyReasonDescendantChanged) and the notification that a descendant changed are not.
    if (reason == DirtyReason::kDirtyReasonContentChanged)
    {
        this->_markWritten();
    }
    this->_forceDirty(reason);
}

uint64_t AbstractItem::getWriteStamp() const
{
    return m_itemData->m_writeStamp;
}

void AbstractItem::_markWritten()
{
    // Not a read-modify-write: the scene is used by one thread at a time, and a lock-prefixed add costs more than a write.
    const uint64_t stamp = s_writeCounter.load(std::memory_order_relaxed) + 1;
    s_writeCounter.store(stamp, std::memory_order_relaxed);
    m_itemData->m_writeStamp = stamp;
    DragFollow::noteWrite(this);
}

void AbstractItem::_forceDirty(DirtyReason reason)
{
    auto parent = this->getParent();
    if (parent != nullptr)
    {
        auto modParent = const_cast<AbstractContainer*>(parent);
        // The notification that a descendant changed is not a write of the parent: it does not take a stamp.
        static_cast<AbstractItem*>(modParent)->_forceDirty(reason);
    }
}

bool AbstractItem::needDrawContent()
{
    return this->_needDrawContent();
}

bool AbstractItem::_needDrawContent()
{
    return true;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
