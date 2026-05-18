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
#include "Api.h"
#include "Math.h"

#include <unordered_map>
#include <unordered_set>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class AbstractGesture;
struct MouseInput;

/**
 * @brief The object that controls batch processing and preventing of gestures.
 * Typically each scene has a default manager and if the user wants to have own
 * prevention logic, he can reimplement it.
 */
class OMNIUI_SCENE_CLASS_API GestureManager
{
public:
    /**
     * @brief Constructor
     */
    OMNIUI_SCENE_API
    GestureManager();

    OMNIUI_SCENE_API
    virtual ~GestureManager();

    /**
     * @brief Set the camera
     *
     * @todo resolution
     */
    void setView(const Matrix44& projection, const Matrix44& view, const Vector2& frameSize);

    /**
     * @brief Process mouse inputs and do all the intersections.
     */
    void preProcess(const MouseInput& input);

    /**
     * @brief Process all the prevention logic and reduce the number of
     * gestures.
     */
    void prevent(const std::unordered_set<AbstractGesture*>& cachedGestures);

    /**
     * @brief  Process the gestures.
     */
    void process();

    /**
     * @brief Clean-up caches, save states.
     */
    void postProcess();

    /**
     * @brief Called per gesture. Determines if the gesture can be prevented.
     */
    OMNIUI_SCENE_API
    virtual bool canBePrevented(AbstractGesture* gesture) const;

    /**
     * @brief Called per gesture. Determines if the gesture should be prevented
     * with another gesture. Useful to resolve intersections.
     */
    OMNIUI_SCENE_API
    virtual bool shouldPrevent(AbstractGesture* gesture, const AbstractGesture* gesturePreventer) const;

    /**
     * @brief Called once a frame. Should be overriden to inject own input to the gestures.
     */
    OMNIUI_SCENE_API
    virtual MouseInput amendInput(MouseInput input) const;

    OMNIUI_SCENE_API
    void setMaxWait(uint32_t);

    OMNIUI_SCENE_API
    void setMaxWait(uint32_t, bool force);

    OMNIUI_SCENE_API
    uint32_t getMaxWait() const;

private:
    friend class AbstractItem;
    friend class AbstractGesture;
    friend class Scene;
    struct GestureManagerData;

    struct PreventCache
    {
        // The latest state shouldPrevent is called for
        GestureState canBePreventedState = GestureState::eNone;
    };

    void _trackGesture(AbstractGesture* gesture);
    void _loseGesture(AbstractGesture* gesture);

    void _collectGestures(std::unordered_set<AbstractGesture*>& gesture) const;

    std::unique_ptr<GestureManagerData> m_data;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
