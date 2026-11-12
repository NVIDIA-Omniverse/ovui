/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
     *
     * Contract of ``on_changed``:
     *
     * - ``on_began`` and ``on_ended`` are called once for each drag. ``on_changed`` is called in each frame of the drag in
     *   which the payload of the shape changed (the item closest point or the ray closest point is not the one of the
     *   previous frame), except a frame that only shows the follow of the last call (below). Pointer movements that are
     *   queued before one frame give one call, with the payload of the last of them. A frame in which nothing changed gives
     *   no call, also when the pointer is held.
     * - The payload changes when the pointer moves, when the camera moves, and when the shape or one of the items above it
     *   is written by any code. Every such change is called, also under a still pointer, however small it is (one unit of
     *   the last digit of a number counts): a turn, a scale, an edit of the geometry (the new position of a ``Points`` is
     *   called with ``moved`` of zero and the new item closest point), a move of the shape. A color, a thickness or a size
     *   is not geometry and is not a change of the payload.
     * - ``moved`` (and the other ``moved_*`` values) is the change of the payload values since the last call. The change of
     *   a frame that has no call stays in the next call, so the ``moved`` of the calls add up to the change of the payload
     *   since the drag began. ``angle`` of an ``Arc`` is continuous across the full turn.
     * - The follow of the pointer. A consumer that follows the pointer moves the shape, or a ``Transform`` above it, by the
     *   ``moved`` that a call reported. The next frame has the payload of the new place under the same pointer and camera:
     *   that is the movement that was already reported, and it has no call (before, it was a second call for the same
     *   movement, with ``moved`` of zero or of rounding noise and, for an ``Arc``, the angle that the pointer has on the
     *   moved shape). The gesture does not compare numbers of the payload: it knows what was written while the callback ran
     *   and by whom. The frame has no call when the pointer and the camera are the same, nothing has written to the shape or
     *   above it since the callback returned, and the writes of the callback are the follow. They are the follow when
     *   - the consumer declares them: ``with gesture.following():`` around the write, in the callback or in a later update
     *     that applies the movement (the translate gizmo does this, because its writes go through a model and a stage); or
     *   - each is what the movement gives, to the last digit, with every ``Transform`` above a plain translation (no
     *     rotation, scale, space to scale to, look at the camera or basis): the translation of one ``Transform`` is the old
     *     translation plus ``moved``; the translations of several ``Transform`` are each the old one plus
     *     ``moved`` divided by their number; or both ends of a ``Line``, or every position of a ``Points``, are each the
     *     old one plus ``moved``, each written once in the callback. A consumer that writes another number (the start plus the sum
     *     of the ``moved``, an absolute point) is called whenever that number is not the old translation plus ``moved``: an
     *     edit of one unit of the last digit writes the same number, the stored matrix and the payload are the same, so the
     *     two cannot be told apart and the call is delivered every time; nothing is learned from it. Such a consumer
     *     declares its write with ``following()`` to get no call.
     * - A callback that writes the same ``Transform``, end of a ``Line`` or list of positions more than once gives a history
     *   that is not one follow (the first write may be the follow and the second an independent correction), so it is
     *   called.
     * - Everything else is called, also when the same consumer wrote it: a write that is one unit away from the follow, a
     *   write through a parent that turns or scales, a snapped write, a write made in a later update that is not declared,
     *   a write of a ``Curve`` or another shape. Such a call has the data of a call for an independent edit that writes the
     *   same numbers (the payload is a function of the shapes only), so it cannot be told from one and is delivered: a lost
     *   real update is worse than one extra call.
     */
    OMNIUI_SCENE_API
    void process() override;

    /**
     * @brief Tells that the writes that follow, until ``endFollowing``, are the follow of the pointer: the consumer applies
     * the movement that the last call reported to the shape or to the transforms above it. The next frame, which has the
     * payload of the new place under a still pointer, is then not a second call for the same movement.
     *
     * It is for a consumer whose writes the gesture cannot recognise by itself (see ``process``): for example a write that
     * goes through a model and a stage, or a movement that is applied in a later update. It can be used inside a
     * callback or after it. Calls can be nested. Outside of a drag it does nothing.
     */
    OMNIUI_SCENE_API
    void beginFollowing();

    /**
     * @brief Ends what ``beginFollowing`` began.
     */
    OMNIUI_SCENE_API
    void endFollowing();

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
