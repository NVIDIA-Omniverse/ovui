/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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

    /**
     * @brief Internal, for DragGesture. The ``moved`` of the payload that the shape has now, and the absolute point of it that
     * a consumer can follow. Returns false for a shape whose payload has none.
     */
    OMNIUI_SCENE_API
    virtual bool _getFollowReport(Vector3& moved) const;

protected:
    friend class ShapeGesture;
    friend class DragGesture;
    struct AbstractShapeData;

    OMNIUI_SCENE_API
    AbstractShape(AbstractShapeData* = nullptr);

    OMNIUI_SCENE_API
    void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height) override;

    void _setParent(const AbstractContainer* const& parent) override;

    /**
     * @brief For DragGesture. Takes the payload that the shape has now (the payload of a call) as the baseline that
     * ``moved`` is measured from in the next frame that is held.
     */
    virtual void _captureBaseline() const;

    /**
     * @brief For DragGesture. The next intersection measures ``moved`` and the other ``moved_*`` values from the baseline
     * instead of from the previous frame: a frame that has no call keeps its movement for the next call.
     */
    void _holdPayloadBaseline(bool hold = true) const;

    /**
     * @brief A property that is only drawn (a color, a thickness, a size) has changed: the shape is redrawn, but this is not
     * a write that can change the payload of a gesture, so it takes no write stamp.
     */
    void _dirtyAppearance();

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
