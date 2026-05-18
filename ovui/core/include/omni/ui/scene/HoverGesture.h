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

#include <functional>
#include <chrono>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The gesture that provides a way to capture event when mouse
 * enters/leaves the item.
 */
class OMNIUI_SCENE_CLASS_API HoverGesture : public ShapeGesture
{
    OMNIUI_GESTURE_OBJECT(HoverGesture)

public:
    OMNIUI_SCENE_API
    ~HoverGesture();

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
     * @brief Called if the callback is not set and the mouse enters the item
     */
    OMNIUI_SCENE_API
    virtual void onBegan();

    /**
     * @brief Called if the callback is not set and the mouse is hovering the item
     */
    OMNIUI_SCENE_API
    virtual void onChanged();

    /**
     * @brief Called if the callback is not set and the mouse leaves the item
     */
    OMNIUI_SCENE_API
    virtual void onEnded();

    /**
     * @brief The mouse button this gesture is watching.
     */
    OMNIUI_PROPERTY(uint32_t, mouseButtons, DEFAULT, 0, READ, getMouseButton, WRITE, setMouseButton);

    /**
     * @brief The modifier that should be pressed to trigger this gesture.
     */
    OMNIUI_PROPERTY(uint32_t, modifiers, DEFAULT, UINT32_MAX, READ, getModifiers, WRITE, setModifiers);

    /**
     * @brief Called when the mouse enters the item
     */
    OMNIUI_CALLBACK(OnBegan, void, AbstractShape const*);

    /**
     * @brief Called when the mouse is hovering the item
     */
    OMNIUI_CALLBACK(OnChanged, void, AbstractShape const*);

    /**
     * @brief Called when the mouse leaves the item
     */
    OMNIUI_CALLBACK(OnEnded, void, AbstractShape const*);

    OMNIUI_SCENE_API void setMouseButtons(const std::vector<uint32_t>& mouseButtons)
    {
        GestureButtonEditor(m_mouseButtons).setMouseButtons(mouseButtons);
    }

    OMNIUI_SCENE_API std::vector<uint32_t> getMouseButtons() const
    {
        uint32_t mouseButtons = m_mouseButtons;
        return GestureButtons(mouseButtons).getMouseButtons();
    }
protected:
    struct HoverGestureData;

    /**
     * @brief Constructs an gesture to track when the user clicked the mouse.
     *
     * @param onEnded Function that is called when the user clicked the mouse
     * button.
     */
    OMNIUI_SCENE_API
    HoverGesture(std::function<void(AbstractShape const*)> onEnded = nullptr);
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
