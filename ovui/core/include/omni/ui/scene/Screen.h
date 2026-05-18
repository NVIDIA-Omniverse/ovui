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

#include "AbstractShape.h"
#include "Math.h"
#include "Object.h"

#include <array>
#include <memory>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The empty shape that triggers all the gestures at any place. Is used
 * to track gestures when the user clicked the empty space. For example for
 * cameras.
 */
class OMNIUI_SCENE_CLASS_API Screen : public AbstractShape
{
    OMNIUI_SCENE_OBJECT(Screen);

public:
    class ScreenGesturePayload : public AbstractGesture::GesturePayload
    {
    public:
        Vector3 direction = Vector3{ 0.0 };
        Vector3 moved = Vector3{ 0.0 };
        // TODO: Maybe we need mouse in AbstractGesture::GesturePayload
        Vector2 mouse = Vector2{ 0.0 };
        Vector2 mouseMoved = Vector2{ 0.0 };
    };

    OMNIUI_SCENE_API
    virtual ~Screen();

    OMNIUI_SCENE_API
    void intersect(const Vector3 origin,
                   const Vector3 direction,
                   const Vector2 mouse,
                   const Matrix44& projection,
                   const Matrix44& view,
                   GestureState state) override;

    /**
     * @brief Contains all the information about the intersection
     */
    OMNIUI_SCENE_API
    const ScreenGesturePayload* getGesturePayload() const override;

    /**
     * @brief Contains all the information about the intersection at the specific state
     */
    OMNIUI_SCENE_API
    const ScreenGesturePayload* getGesturePayload(GestureState state) const override;

protected:
    /**
     * @brief Constructor
     */
    OMNIUI_SCENE_API
    Screen();

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    struct ScreenData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
