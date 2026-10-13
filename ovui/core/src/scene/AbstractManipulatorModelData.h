/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/scene/AbstractManipulatorModel.h>

#include <map>
#include <unordered_map>
#include <unordered_set>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct AbstractManipulatorModel::AbstractManipulatorModelData
{
    virtual ~AbstractManipulatorModelData();

    // All the widgets who use this model.
    std::unordered_set<ManipulatorModelHelper*> m_manipulators;

    // All the callbacks.
    std::vector<ItemChangedCallback> m_itemChangedCallbacks;

    // If the derived model doesn't want to create new items, the default
    // implementation will do it.
    std::map<std::string, std::shared_ptr<const AbstractManipulatorItem>> m_defaultItems;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
