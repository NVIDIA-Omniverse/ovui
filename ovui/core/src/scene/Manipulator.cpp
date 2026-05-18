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

#include <omni/ui/platform/Assert.h>
#include <omni/ui/platform/Log.h>

#include <omni/ui/scene/Manipulator.h>
#include <omni/ui/scene/ManipulatorGesture.h>
#include <omni/ui/scene/Scene.h>

#include "AbstractContainerData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct Manipulator::ManipulatorData : public AbstractContainer::AbstractContainerData
{
    ~ManipulatorData() override = default;

    // We need it to keep the old children. We remove them in _postDrawContent.
    std::vector<std::shared_ptr<AbstractItem>> m_oldChildren;
    std::vector<std::shared_ptr<ManipulatorGesture>> m_gestures;

    bool m_dirty = true;
};

Manipulator::Manipulator()
    : AbstractContainer(new ManipulatorData)
    , ManipulatorModelHelper{nullptr}
{
    this->setOnBuildChangedFn(std::bind(&This::invalidate, this));
}

Manipulator::~Manipulator() = default;

void Manipulator::onBuild()
{
}

void Manipulator::invalidate()
{
    _getData<ManipulatorData>().m_dirty = true;
}

void Manipulator::onModelUpdated(const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>& item)
{
}

const std::vector<std::shared_ptr<ManipulatorGesture>>& Manipulator::getGestures() const
{
    return  _getData<ManipulatorData>().m_gestures;
}

void Manipulator::setGestures(std::vector<std::shared_ptr<ManipulatorGesture>> gestures)
{
    auto& data = _getData<ManipulatorData>();
    auto& myGestures = data.m_gestures;
    for (auto& gesture : myGestures)
    {
        if (gesture)
        {
            gesture->_dischargeItem(this);
        }
    }

    myGestures = std::move(gestures);

    for (auto& gesture : myGestures)
    {
        if (gesture)
        {
            gesture->_assignItem(this);

            if (!gesture->getManager())
            {
                gesture->setManager(this->_getScene()->getDefaultGestureManager());
            }
        }
    }
    data.m_dirty = true;
}

void Manipulator::addGesture(std::shared_ptr<ManipulatorGesture> gesture)
{
    if (!gesture)
    {
        return;
    }

    gesture->_assignItem(this);

    if (!gesture->getManager())
    {
        gesture->setManager(this->_getScene()->getDefaultGestureManager());
    }

    auto& data = _getData<ManipulatorData>();
    data.m_gestures.emplace_back(std::move(gesture));
    data.m_dirty = true;
}

void Manipulator::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    auto& data = _getData<ManipulatorData>();
    if (data.m_dirty)
    {
        data.m_dirty = false;

        OMNIUI_ASSERT(data.m_oldChildren.empty());
        data.m_oldChildren.swap(data.m_children);

        OMNIUI_SCENE_WITH_CONTAINER(this->castShared())
        {
            if (this->hasOnBuildFn())
            {
                this->callOnBuildFn(this);
            }
            else
            {
                this->onBuild();
            }
        }
    }

    AbstractContainer::_preDrawContent(input, projection, view, width, height);
}

void Manipulator::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    this->_drawChildren(projection, view);
}

void Manipulator::_postDrawContent(const Matrix44& projection, const Matrix44& view)
{
    AbstractContainer::_postDrawContent(projection, view);

    // Destroy old children at the end because they still can be senders of
    // gestures.
    auto& data = _getData<ManipulatorData>();
    for (auto& oldChild : data.m_oldChildren)
    {
        oldChild->destroy();
    }
    data.m_oldChildren.clear();
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
