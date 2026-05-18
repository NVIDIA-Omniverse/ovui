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

#include "AbstractGesture.h"
#include "AbstractItem.h"

#include <memory>
#include <unordered_set>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class ShapeGesture;

/**
 * @brief Base class for all the items that can be drawn and intersected with
 * mouse pointer.
 */
class OMNIUI_SCENE_CLASS_API AbstractShape : public AbstractItem
{
    OMNIUI_SCENE_OBJECT(AbstractShape);

public:
    OMNIUI_SCENE_API
    ~AbstractShape() override;

    OMNIUI_SCENE_API
    void destroy() override;

    /**
     * @brief All the gestures assigned to this shape
     */
    OMNIUI_SCENE_API
    const std::vector<std::shared_ptr<ShapeGesture>>& getGestures() const;

    /**
     * @brief Replace the gestures of the shape
     */
    OMNIUI_SCENE_API
    void setGestures(std::vector<std::shared_ptr<ShapeGesture>> gestures);

    /**
     * @brief Add a single gesture to the shape
     */
    OMNIUI_SCENE_API
    void addGesture(std::shared_ptr<ShapeGesture> gesture);

    OMNIUI_SCENE_API
    virtual void intersect(const Vector3 origin,
                           const Vector3 direction,
                           const Vector2 mouse,
                           const Matrix44& projection,
                           const Matrix44& view,
                           GestureState state) = 0;

    /**
     * @brief Contains all the information about the intersection
     */
    OMNIUI_SCENE_API
    virtual const AbstractGesture::GesturePayload* getGesturePayload() const = 0;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    virtual const AbstractGesture::GesturePayload* getGesturePayload(GestureState state) const = 0;

    /**
     * @brief The distance in pixels from mouse pointer to the shape for the intersection.
     */
    OMNIUI_SCENE_API
    virtual Float getIntersectionDistance() const;

protected:
    friend class ShapeGesture;
    struct AbstractShapeData;

    OMNIUI_SCENE_API
    AbstractShape(AbstractShapeData* = nullptr);

    OMNIUI_SCENE_API
    void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height) override;

    void _setParent(const AbstractContainer* const& parent) override;

    void _collectManagers(std::unordered_set<GestureManager*>& managers) const override;

    void _cacheGesturePayload(const Vector3 origin,
                              const Vector3 direction,
                              const Vector2 mouse,
                              const Matrix44& projection,
                              const Matrix44& view,
                              GestureState state);

    template <typename T> T& _getData() const { return static_cast<T&>(*m_data); }

    std::unique_ptr<AbstractShapeData> m_data;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
