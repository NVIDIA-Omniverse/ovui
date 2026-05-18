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
