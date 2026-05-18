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
#include "Api.h"
#include "Math.h"

#include <memory>
#include <string>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class GestureManager;

/**
 * @brief The state of all the gestures. Basically it's begin-change-end, but
 * each gesture gesides its workflow.
 */
enum class GestureState : uint32_t
{
    eNone = 0,
    ePossible,
    eBegan,
    eChanged,
    eEnded,
    eCanceled,
    ePrevented,
    eCount
};

/**
 * @brief The base class for the gestures to provides a way to capture mouse
 * events in 3d scene.
 */
class OMNIUI_SCENE_CLASS_API AbstractGesture : protected CallbackHelper<AbstractGesture>
{
public:
    class GesturePayload
    {
    public:
        Vector3 itemClosestPoint;
        Vector3 rayClosestPoint;
        Float rayDistance;
    };

    OMNIUI_SCENE_API
    virtual ~AbstractGesture();

    /**
     * @brief Set the Manager that controld this gesture
     */
    OMNIUI_SCENE_API
    void setManager(const std::shared_ptr<GestureManager>& manager);

    /**
     * @brief The Manager that controld this gesture
     */
    OMNIUI_SCENE_API
    const std::shared_ptr<GestureManager>& getManager() const;

    /**
     * @brief Called by scene to process the mouse inputs and do intersections
     * with shapes. It can be an entry point to simulate the mouse input.
     *
     * @todo We probably don't need projection-view here. We can get it from
     * manager.
     */
    virtual void dispatchInput(const MouseInput& input,
                               const Matrix44& projection,
                               const Matrix44& view,
                               const Vector2& frameSize) = 0;

    /**
     * @brief Called before the processing to determine the state of the gesture.
     */
    OMNIUI_SCENE_API
    virtual void preProcess(const Matrix44& projection, const Matrix44& view);

    /**
     * @brief Process the gesture and call callbacks if necessary.
     */
    OMNIUI_SCENE_API
    virtual void process();

    /**
     * @brief Gestures are finished. Clean-up.
     */
    OMNIUI_SCENE_API
    virtual void postProcess();

    /**
     * @brief Get the internal state that was before the current state.
     */
    OMNIUI_SCENE_API
    GestureState getPreviousState() const;

    /**
     * @brief Get the internal state of the gesture.
     */
    OMNIUI_SCENE_API
    GestureState getState() const;

    /**
     * @brief Set the internal state of the gesture. It's the way to cancel,
     * prevent, or restore the gesture.
     */
    OMNIUI_SCENE_API
    virtual void setState(GestureState state);

    /**
     * @brief Returns true if the gesture is just changed at the current frame.
     * If the state is not changed, `process()` will not be executed.
     */
    bool isStateChanged() const;

    /**
     * @brief Returns the relevant shape driving the gesture.
     */
    OMNIUI_SCENE_API
    virtual const AbstractItem* getSender() const = 0;

    /**
     * @brief Shortcut for sender.get_gesturePayload
     *
     * @return OMNIUI_SCENE_API const*
     */
    OMNIUI_SCENE_API
    virtual const GesturePayload* getGesturePayload() const = 0;

    /**
     * @brief Shortcut for sender.get_gesturePayload
     *
     * @return OMNIUI_SCENE_API const*
     */
    OMNIUI_SCENE_API
    virtual const GesturePayload* getGesturePayload(GestureState state) const = 0;

    /**
     * @brief The name of the object. It's used for debugging.
     */
    OMNIUI_PROPERTY(std::string, name, READ, getName, WRITE, setName);

protected:
    friend class GestureManager;
    friend class Scene;
    struct AbstractGestureData;

    OMNIUI_SCENE_API
    AbstractGesture(AbstractGestureData* = nullptr);

    template <typename T> T& _getData() const { return static_cast<T&>(*m_data); }

    std::unique_ptr<AbstractGestureData> m_data;

private:
    void _setCanBePrevented(bool canBe);
    bool _getCanBePrevented() const;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
