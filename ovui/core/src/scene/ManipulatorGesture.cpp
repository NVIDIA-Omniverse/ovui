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

#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/Manipulator.h>
#include <omni/ui/scene/ManipulatorGesture.h>

#include "AbstractGestureData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct ManipulatorGesture::ManipulatorGestureData : public AbstractGestureData
{
    ~ManipulatorGestureData() override = default;

    // Last mouse event.
    MouseInput m_input;

    std::shared_ptr<AbstractGesture::GesturePayload> m_gesturePayload;
    std::unordered_set<const Manipulator*> m_items;
    const Manipulator* m_currentShape = nullptr;
};

ManipulatorGesture::ManipulatorGesture()
    : AbstractGesture(new ManipulatorGestureData)
{
}

ManipulatorGesture::~ManipulatorGesture()
{
}

const MouseInput& ManipulatorGesture::getMouseInput() const
{
    return _getData<ManipulatorGestureData>().m_input;
}

void ManipulatorGesture::dispatchInput(const MouseInput& input,
                                       const Matrix44& projection,
                                       const Matrix44& view,
                                       const Vector2& frameSize)
{
    _getData<ManipulatorGestureData>().m_input = input;

    // TODO: Depth sorting. But it's OK for now because since it's a gesture of high level depth-sorting happens
    // automatically on the level of Shape gesture.
}

void ManipulatorGesture::preProcess(const Matrix44& projection, const Matrix44& view)
{
    const auto sender = this->getSender();

    switch (this->getState())
    {
    case GestureState::ePossible:
    case GestureState::eBegan:
    case GestureState::eChanged:
        break;

    default:
        this->setState(GestureState::ePossible);
        break;
    };
}

const Manipulator* ManipulatorGesture::getSender() const
{
    return _getData<ManipulatorGestureData>().m_currentShape;
}

void ManipulatorGesture::_processWithGesturePayload(const Manipulator* sender,
                                                    GestureState state,
                                                    std::shared_ptr<AbstractGesture::GesturePayload> gesturePayload)
{
    auto& data = _getData<ManipulatorGestureData>();
    data.m_gesturePayload = std::move(gesturePayload);
    data.m_currentShape = sender;
    this->setState(state);
    // Force process
    this->process();
}

const AbstractGesture::GesturePayload* ManipulatorGesture::getGesturePayload() const
{
    return _getData<ManipulatorGestureData>().m_gesturePayload.get();
}

const AbstractGesture::GesturePayload* ManipulatorGesture::getGesturePayload(GestureState state) const
{
    // TODO: Implement per state
    return this->getGesturePayload();
}

void ManipulatorGesture::_assignItem(Manipulator* item)
{
    _getData<ManipulatorGestureData>().m_items.insert(item);
}

void ManipulatorGesture::_dischargeItem(Manipulator* item)
{
    auto& data = _getData<ManipulatorGestureData>();
    if (data.m_currentShape == item)
    {
        data.m_currentShape = nullptr;
        data.m_gesturePayload = nullptr;
    }
    data.m_items.erase(item);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
