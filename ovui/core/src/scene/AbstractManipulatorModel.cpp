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

#include <omni/ui/scene/AbstractManipulatorModel.h>
#include <omni/ui/scene/ManipulatorModelHelper.h>

#include "AbstractManipulatorModelData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

AbstractManipulatorModel::AbstractManipulatorModelData::~AbstractManipulatorModelData()
{
}

AbstractManipulatorModel::AbstractManipulatorModel(AbstractManipulatorModelData* dataPtr)
    : m_modelData(dataPtr ? dataPtr : new AbstractManipulatorModelData)
{
}

AbstractManipulatorModel::~AbstractManipulatorModel() = default;

void AbstractManipulatorModel::subscribe(ManipulatorModelHelper* widget)
{
    m_modelData->m_manipulators.insert(widget);
}

std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem> AbstractManipulatorModel::getItem(
    const std::string& identifier)
{
    auto& defaultItems = m_modelData->m_defaultItems;

    // It's used when the user doesn't want to implement getItem. We create an
    // empty one and return it. Very useful if the user doesn't want to deal
    // with items at all and wants to work with the model as with a dict.
    auto found = defaultItems.find(identifier);
    if (found == defaultItems.end())
    {
        auto created = std::make_shared<const AbstractManipulatorItem>();
        defaultItems[identifier] = created;
        return created;
    }

    return found->second;
}

void AbstractManipulatorModel::unsubscribe(ManipulatorModelHelper* widget)
{
    m_modelData->m_manipulators.erase(widget);
}

uint32_t AbstractManipulatorModel::addItemChangedFn(AbstractManipulatorModel::ItemChangedCallback&& fn)
{
    auto& callbacks = m_modelData->m_itemChangedCallbacks;
    uint32_t id = static_cast<uint32_t>(callbacks.size());
    callbacks.emplace_back(std::move(fn));
    return id;
}

void AbstractManipulatorModel::removeItemChangedFn(uint32_t id)
{
    OMNIUI_ASSERT(id < m_modelData->m_itemChangedCallbacks.size());

    // We don't remove it to keep the ids that we already returned. Instead, we make this function NULL, so it will be
    // skipped.
    m_modelData->m_itemChangedCallbacks[id] = nullptr;
}

void AbstractManipulatorModel::_itemChanged(
    const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>& item)
{
    // Notify everyone the value is changed
    for (auto manipulator : m_modelData->m_manipulators)
    {
        manipulator->onModelUpdated(item);
    }

    for (const auto& callback : m_modelData->m_itemChangedCallbacks)
    {
        if (!callback)
        {
            continue;
        }

        callback(this, item.get());
    }
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
