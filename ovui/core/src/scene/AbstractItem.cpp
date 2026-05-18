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

#include <omni/ui/Profile.h>

#include <omni/ui/scene/AbstractItem.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/Scene.h>

#include "AbstractItemData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

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
    this->_forceDirty(reason);
}

void AbstractItem::_forceDirty(DirtyReason reason)
{
    auto parent = this->getParent();
    if (parent != nullptr)
    {
        auto modParent = const_cast<AbstractContainer*>(parent);
        modParent->forceDirty(reason);
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
