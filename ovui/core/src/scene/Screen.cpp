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

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Math.h>
#include <omni/ui/scene/Screen.h>

#include "AbstractShapeData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct Screen::ScreenData : public AbstractShapeData
{
    ScreenData()
        : m_lastGesturePayload(std::make_unique<ScreenGesturePayload>())
    {
    }
    ~ScreenData() override
    {
    }

    std::unique_ptr<ScreenGesturePayload> m_lastGesturePayload;
    std::array<std::unique_ptr<ScreenGesturePayload>, static_cast<uint32_t>(GestureState::eCount)> m_itersections;
};

Screen::Screen() : AbstractShape(new ScreenData)
{
}

Screen::~Screen() = default;

void Screen::_drawContent(const Matrix44& projection, const Matrix44& view)
{
}

void Screen::intersect(const Vector3 origin,
                       const Vector3 direction,
                       const Vector2 mouse,
                       const Matrix44& projection,
                       const Matrix44& view,
                       GestureState state)
{
    // TODO: All the shapes will have similar code with a different type. We
    // could put this code to a macro.
    auto& data = _getData<ScreenData>();
    auto& stateGesturePayload = data.m_itersections[static_cast<uint32_t>(state)];
    if (!stateGesturePayload)
    {
        stateGesturePayload = std::make_unique<ScreenGesturePayload>();
    }

    auto& lastGesturePayload = data.m_lastGesturePayload;
    Vector2 lastMouse = lastGesturePayload->mouse;

    // We can't get lastClosestPoint with saving it from the previous frame. The
    // camera could move, so we need to compensate it.
    Vector3 lastClosestPoint;
    createRay(projection, view, lastMouse, &lastClosestPoint, nullptr);

    lastGesturePayload->itemClosestPoint = origin;
    lastGesturePayload->rayClosestPoint = origin;
    lastGesturePayload->rayDistance = Float(1e-6);
    lastGesturePayload->direction = direction;
    lastGesturePayload->mouse = mouse;
    lastGesturePayload->moved = lastGesturePayload->itemClosestPoint - lastClosestPoint;
    lastGesturePayload->mouseMoved = mouse - lastMouse;

    // Copy
    *stateGesturePayload.get() = *lastGesturePayload.get();
}

const Screen::ScreenGesturePayload* Screen::getGesturePayload() const
{
    return _getData<ScreenData>().m_lastGesturePayload.get();
}

const Screen::ScreenGesturePayload* Screen::getGesturePayload(GestureState state) const
{
    return _getData<ScreenData>().m_itersections[static_cast<uint32_t>(state)].get();
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
