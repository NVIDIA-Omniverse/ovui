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


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The gesture that provides a way to capture click-and-drag mouse
 * event.
 */
class OMNIUI_SCENE_CLASS_API DragGesture : public ShapeGesture
{
    OMNIUI_GESTURE_OBJECT(DragGesture)

public:
    OMNIUI_SCENE_API
    ~DragGesture();

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
     * @brief Called if the callback is not set when the user clicks the mouse
     * button.
     */
    OMNIUI_SCENE_API
    virtual void onBegan();

    /**
     * @brief Called if the callback is not set when the user moves the clicked
     * button.
     */
    OMNIUI_SCENE_API
    virtual void onChanged();

    /**
     * @brief Called if the callback is not set when the user releases the mouse
     * button.
     */
    OMNIUI_SCENE_API
    virtual void onEnded();

    /**
     * @brief Mouse button that should be active to start the gesture
     */
    OMNIUI_PROPERTY(uint32_t, mouseButtons, DEFAULT, 0, READ, getMouseButton, WRITE, setMouseButton);

    /**
     * @brief The keyboard modifier that should be active ti start the gesture
     */
    OMNIUI_PROPERTY(uint32_t, modifiers, DEFAULT, UINT32_MAX, READ, getModifiers, WRITE, setModifiers);

    /**
     * @brief The check_mouse_moved property is a boolean flag that determines
     * whether the DragGesture should verify if the 2D screen position of the
     * mouse has changed before invoking the on_changed method. This property
     * is essential in a 3D environment, as changes in the camera position can
     * result in the mouse pointing to different locations in the 3D world even
     * when the 2D screen position remains unchanged.
     *
     * Usage
     *
     * When check_mouse_moved is set to True, the DragGesture will only
     * call the on_changed method if the actual 2D screen position of the
     * mouse has changed. This can be useful when you want to ensure that the
     * on_changed method is only triggered when there is a genuine change in
     * the mouse's 2D screen position.
     *
     * If check_mouse_moved is set to False, the DragGesture will not
     * check for changes in the mouse's 2D screen position before calling the
     * on_changed method. This can be useful when you want the on_changed
     * method to be invoked even if the mouse's 2D screen position hasn't
     * changed, such as when the camera position is altered, and the mouse now
     * points to a different location in the 3D world.
     */
    OMNIUI_PROPERTY(bool, checkMouseMoved, DEFAULT, false, READ, isCheckMouseMoved, WRITE, setCheckMouseMoved);

    /**
     * @brief Called when the user starts drag
     */
    OMNIUI_CALLBACK(OnBegan, void, AbstractShape const*);

    /**
     * @brief Called when the user is dragging
     */
    OMNIUI_CALLBACK(OnChanged, void, AbstractShape const*);

    /**
     * @brief Called when the user releases the mouse and finishes the drag
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
    /**
     * @brief Construct the gesture to track mouse drags.
     */
    OMNIUI_SCENE_API
    DragGesture();

private:
    struct DragGestureData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
