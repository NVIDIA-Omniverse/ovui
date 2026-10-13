/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "ClickGesture.h"
#include "Object.h"

#include <functional>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The gesture that provides a way to capture double clicks.
 */
class OMNIUI_SCENE_CLASS_API DoubleClickGesture : public ClickGesture
{
    OMNIUI_GESTURE_OBJECT(DoubleClickGesture)

public:
    OMNIUI_SCENE_API
    ~DoubleClickGesture();

    /**
     * @brief Called before processing to determine the state of the gesture.
     */
    OMNIUI_SCENE_API
    void preProcess(const Matrix44& projection, const Matrix44& view) override;

protected:
    /**
     * @brief Construct the gesture to track double clicks
     *
     * @param onEnded Called when the user double clicked
     */
    OMNIUI_SCENE_API
    DoubleClickGesture(std::function<void(AbstractShape const*)> onEnded = nullptr);

private:
    struct DoubleClickGestureData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
