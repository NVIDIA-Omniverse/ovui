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

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Scene.h>
#include <omni/ui/scene/SceneView.h>
#include <omni/ui/scene/Transform.h>

#include "AbstractContainerData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

AbstractContainer::AbstractContainerData::~AbstractContainerData()
{
}

AbstractContainer::AbstractContainer(AbstractContainerData* dataPtr)
    : AbstractItem(dataPtr ? dataPtr : new AbstractContainerData)
{
}

AbstractContainer::~AbstractContainer()
{
    this->destroy();
}

const std::vector<std::shared_ptr<AbstractItem>>& AbstractContainer::_getChildren() const
{
    auto& data = _getData<AbstractContainerData>();
    return data.m_children;
}


void AbstractContainer::destroy()
{
    auto& children = _getData<AbstractContainerData>().m_children;
    for (auto& child : children)
    {
        child->destroy();
    }
    children.clear();

    AbstractItem::destroy();
}

void AbstractContainer::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    for (auto& child : _getChildren())
    {
        child->preDrawContent(input, projection, view, width, height);
    }

    if (this->_isCaching())
    {
        auto drawList = this->_getDrawList();
        if (OMNIUI_LIKELY(drawList))
        {
            drawList->setDrawBufferCacheState(this->_getDrawBufferIndex());
        }
    }
}

void AbstractContainer::_postDrawContent(const Matrix44& projection, const Matrix44& view)
{
    if (this->_isCaching())
    {
        this->_getDrawBufferIndex().setDirty(false);
    }
    for (auto& child : _getChildren())
    {
        child->postDrawContent(projection, view);
    }
}

Vector3 AbstractContainer::transformSpace(Space fromSpace, Space toSpace, const Vector3& point) const
{
    return Vector3{ this->transformSpace(fromSpace, toSpace, Vector4{ point, 1.0 }) };
}

Vector4 AbstractContainer::transformSpace(Space fromSpace, Space toSpace, const Vector4& vector) const
{
    if (fromSpace == Space::eWorld && toSpace == Space::eObject)
    {
        auto inversed = this->getAccumulatedTransform().getInverse();
        return inversed * vector;
    }
    else if (fromSpace == Space::eObject && toSpace == Space::eWorld)
    {
        return this->getAccumulatedTransform() * vector;
    }
    else if (fromSpace == Space::eWorld && toSpace == Space::eNdc)
    {
        auto projectionView = this->getSceneView()->getAmendedProjection() * this->getSceneView()->getView();
        const Matrix44 pv = projectionView;

        Vector4 result = pv * vector;

        // Perspective
        result = result / result.w;

        return result;
    }
    else if (fromSpace == Space::eNdc && toSpace == Space::eWorld)
    {
        // Inverse of the above, at least one inversion will to occur, so just keep the operation order and invert
        // result.
        auto projectionView = this->getSceneView()->getAmendedProjection() * this->getSceneView()->getView();
        Matrix44 pv = projectionView;
        pv = pv.getInverse();

        Vector4 result = pv * vector;

        // Perspective
        result = result / result.w;

        return result;
    }
    else if (fromSpace == Space::eObject && toSpace == Space::eNdc)
    {
        Vector4 world = this->transformSpace(Space::eObject, Space::eWorld, vector);
        return this->transformSpace(Space::eWorld, Space::eNdc, world);
    }
    else if (fromSpace == Space::eNdc && toSpace == Space::eObject)
    {
        Vector4 world = this->transformSpace(Space::eNdc, Space::eWorld, vector);
        return this->transformSpace(Space::eWorld, Space::eObject, world);
    }
    // TODO: Object to Screen, etc...
    else if (fromSpace == toSpace)
    {
        // Do nothing
    }
    else
    {
        OMNIUI_LOG_ERROR_ONCE("[omni.ui.scene] Can't convert %s space to %s space", getSpaceName(fromSpace).c_str(),
                            getSpaceName(toSpace).c_str());
    }

    return vector;
}

void AbstractContainer::addChild(std::shared_ptr<AbstractItem> item)
{
    auto& data = _getData<AbstractContainerData>();
    data.m_children.push_back(std::move(item));
}

void AbstractContainer::clear()
{
    std::vector<std::shared_ptr<AbstractItem>>& children = _getData<AbstractContainerData>().m_children;
    do {
        std::vector<std::shared_ptr<AbstractItem>> localChildren(std::move(children));

        for (auto& child : localChildren)
        {
            if (child)
            {
                child->destroy();
            }
        }

        if (children.empty())
        {
            break;
        }

        OMNIUI_LOG_ERROR_ONCE("Children were added during clear/destroy, which is not allowed.");
    } while (true);

    if (this->_isCaching())
    {
        // Propagate upward.
        this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
    }
}

Matrix44 AbstractContainer::getAccumulatedTransform() const
{
    if (this->getParent())
    {
        return this->getParent()->getAccumulatedTransform();
    }

    return Matrix44{ (Float)1.0 };
}

void AbstractContainer::_collectManagers(std::unordered_set<GestureManager*>& managers) const
{
    for (auto& child : _getChildren())
    {
        if (child->isVisible())
        {
            child->_collectManagers(managers);
        }
    }
}

DrawBufferIndex& AbstractContainer::_getDrawBufferIndex()
{
    auto& data = _getData<AbstractContainerData>();
    return data.m_bufferIndex;
}

void AbstractContainer::dirtyHierarchy()
{
    DrawBufferIndex& drawBufferIndex = this->_getDrawBufferIndex();
    drawBufferIndex.setContentDirty(true);

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        drawList->setDrawBufferCacheState(drawBufferIndex);
    }

    for (auto& child : _getChildren())
    {
        AbstractContainer* pContainer = dynamic_cast<AbstractContainer*>(child.get());
        if (pContainer)
        {
            pContainer->dirtyHierarchy();
        }
    }
}

void AbstractContainer::_forceDirty(DirtyReason reason)
{
    if (this->_isCaching())
    {
        DrawBufferIndex& drawBufferIndex = this->_getDrawBufferIndex();
        if (reason == DirtyReason::kDirtyReasonContentChanged)
        {
            if (!drawBufferIndex.isContentDirty())
            {
                drawBufferIndex.setContentDirty(true);
                // This might be triggered by the gestures in Scene::_drawContent(). Need to set the cache
                // state for the postponed DrawList::beginFrame() to clear the dirty buffers.
                auto drawList = this->_getDrawList();
                if (OMNIUI_LIKELY(drawList))
                {
                    drawList->setDrawBufferCacheState(drawBufferIndex);
                }
            }
            // Transform and Scene own buffer will not propage the content change upward.
            if (dynamic_cast<Transform*>(this) != nullptr || dynamic_cast<Scene*>(this) != nullptr)
            {
                reason = DirtyReason::kDirtyReasonDescendantChanged;
            }
        }
        else if (reason == DirtyReason::kDirtyReasonDescendantChanged)
        {
            drawBufferIndex.setDescendantDirty(true);
        }
        AbstractItem::_forceDirty(reason);
    }
}

bool AbstractContainer::_needDrawContent()
{
    return !this->_isCaching() || this->_getDrawBufferIndex().anyDirty();
}

void AbstractContainer::_setParent(const AbstractContainer* const& parent)
{
    AbstractItem::_setParent(parent);
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
    this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
}

bool AbstractContainer::_isCaching() const
{
    auto sceneView = this->getSceneView();
    if (sceneView)
    {
        return sceneView->getCacheDrawBuffer();
    }
    else if (this->getParent())
    {
        return this->getParent()->_isCaching();
    }
    return false;
}

void AbstractContainer::_drawChildren(const Matrix44& projection, const Matrix44& view)
{
    const bool isCaching = this->_isCaching();
    const auto& drawBufferIndex = this->_getDrawBufferIndex();
    const bool contentDirty = drawBufferIndex.isContentDirty();
    const bool descendantDirty = drawBufferIndex.isDescendantDirty();
    const bool transformDirty = drawBufferIndex.isTransformDirty();

    auto needDrawChild = [&](const std::shared_ptr<AbstractItem>& child) -> bool
    {
        if (!isCaching)
            return true;

        AbstractItem* pChild = child.get();

        if (dynamic_cast<Transform*>(pChild) != nullptr)
        {
            // A transform (a buffer owner) does not affect the parent's content, need to call its
            // drawContent() when descendant or transform is dirty.
            return descendantDirty || transformDirty;
        }
        else if (dynamic_cast<AbstractContainer*>(pChild) != nullptr)
        {
            return contentDirty || descendantDirty;
        }
        else if (dynamic_cast<AbstractShape*>(pChild) != nullptr)
        {
            return contentDirty;
        }
        return true;
    };

    for (auto& child : _getChildren())
    {
        if (needDrawChild(child))
        {
            child->drawContent(projection, view);
        }
    }
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
