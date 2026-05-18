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
#include "AbstractItem.h"
#include "DrawBufferIndex.h"

#include <memory>
#include <unordered_set>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief Base class for all the items that have children
 */
class OMNIUI_SCENE_CLASS_API AbstractContainer : public AbstractItem
{
public:
    OMNIUI_SCENE_API
    ~AbstractContainer() override;

    OMNIUI_SCENE_API
    void destroy() override;

    /**
     * @brief Transform the given point from the coordinate system fromspace to
     * the coordinate system tospace.
     */
    OMNIUI_SCENE_API
    Vector3 transformSpace(Space fromSpace, Space toSpace, const Vector3& point) const override;

    /**
     * @brief Transform the given vector from the coordinate system fromspace to
     * the coordinate system tospace.
     */
    OMNIUI_SCENE_API
    Vector4 transformSpace(Space fromSpace, Space toSpace, const Vector4& vector) const override;

    /**
     * @brief Adds item to this container in a manner specific to the container. If it's allowed to have one
     * sub-widget only, it will be overwriten.
     */
    OMNIUI_SCENE_API
    virtual void addChild(std::shared_ptr<AbstractItem> item);

    /**
     * @brief Removes the container items from the container.
     */
    OMNIUI_SCENE_API
    virtual void clear();

    OMNIUI_SCENE_API
    virtual Matrix44 getAccumulatedTransform() const;

    /**
     * @brief Invalidates all the buffer caches in the hierarchy.
     */
    OMNIUI_SCENE_API
    virtual void dirtyHierarchy();

protected:
    struct AbstractContainerData;

    OMNIUI_SCENE_API
    AbstractContainer(AbstractContainerData* = nullptr);

    void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height) override;
    void _postDrawContent(const Matrix44& projection, const Matrix44& view) override;

    OMNIUI_SCENE_API
    void _collectManagers(std::unordered_set<GestureManager*>& managers) const override;

    OMNIUI_SCENE_API
    virtual DrawBufferIndex& _getDrawBufferIndex();

    OMNIUI_SCENE_API
    void _forceDirty(DirtyReason reason) override;

    OMNIUI_SCENE_API
    bool _needDrawContent() override;

    OMNIUI_SCENE_API
    void _setParent(const AbstractContainer* const& parent) override;

    OMNIUI_SCENE_API
    bool _isCaching() const;

    OMNIUI_SCENE_API
    void _drawChildren(const Matrix44& projection, const Matrix44& view);

    OMNIUI_SCENE_API
    const std::vector<std::shared_ptr<AbstractItem>>& _getChildren() const;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
