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

#include "Object.h"
#include "ShapeGesture.h"
#include "GestureButtons.h"

#include <chrono>
#include <functional>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The gesture that provides a way to capture click mouse event.
 */
class OMNIUI_SCENE_CLASS_API ClickGesture : public ShapeGesture
{
    OMNIUI_GESTURE_OBJECT(ClickGesture)

public:
    OMNIUI_SCENE_API
    ~ClickGesture();

    /**
     * @brief Called before processing to determine the state of the gesture.
     */
    OMNIUI_SCENE_API
    void preProcess(const Matrix44& projection, const Matrix44& view) override;

    /**
     * @brief Process the gesture and call callbacks if necessary.
     */
    OMNIUI_SCENE_API
    void process() override;

    /**
     * @brief Called if the callback is not set when the user releases the mouse
     * button.
     */
    OMNIUI_SCENE_API
    virtual void onEnded();

    /**
     * @brief Set the internal state of the gesture. It's the way to cancel,
     * prevent, or restore the gesture.
     */
    OMNIUI_SCENE_API
    virtual void setState(GestureState state);

    /**
     * @brief The mouse button this gesture is watching.
     */
    OMNIUI_PROPERTY(uint32_t, mouseButtons, DEFAULT, 0, READ, getMouseButton, WRITE, setMouseButton);

    /**
     * @brief The modifier that should be pressed to trigger this gesture.
     */
    OMNIUI_PROPERTY(uint32_t, modifiers, DEFAULT, UINT32_MAX, READ, getModifiers, WRITE, setModifiers);

    /**
     * @brief Called when the user releases the button.
     */
    OMNIUI_CALLBACK(OnEnded, void, AbstractShape const*);

    OMNIUI_SCENE_API void setMouseButtons(const std::vector<uint32_t>& mouseButtons)
    {
        GestureButtonEditor(m_mouseButtons).setMouseButtons(mouseButtons);
    }

    OMNIUI_SCENE_API std::vector<uint32_t> getMouseButtons() const
    {
        uint32_t mouseButons = m_mouseButtons;
        return GestureButtons(mouseButons).getMouseButtons();
    }

protected:
    // We need this delay to be able to finish double click if it exists
    static constexpr int64_t kGestureWaitForEnd = 100;

    struct ClickGestureData;

    /**
     * @brief Constructs an gesture to track when the user clicked the mouse.
     *
     * @param onEnded Function that is called when the user clicked the mouse
     * button.
     */
    OMNIUI_SCENE_API
    ClickGesture(std::function<void(AbstractShape const*)> onEnded = nullptr,
                 ClickGestureData* = nullptr);

    /**
     * @brief The core implementation of preProcess to specify the number of clicks to use.
     *
     * @param nClicks The number of clicks (single / double) this gesture represents.
     */
    OMNIUI_SCENE_API
    void clickPreProcess(const Matrix44& projection, const Matrix44& view, uint32_t nClicks);
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
