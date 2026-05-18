/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Menu.h>
#include <omni/ui/MenuItemCollection.h>
#include <omni/ui/StyleContainer.h>

#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct MenuItemCollection::MenuItemCollectionData
{
};


MenuItemCollection::MenuItemCollection(const std::string& text) : Menu{ text }
{
}

MenuItemCollection::~MenuItemCollection() = default;

void MenuItemCollection::addChild(std::shared_ptr<Widget> widget)
{
    auto* widgetPtr = widget.get();
    widget->setCheckedChangedFn([this, widgetPtr](const bool& checked) {
        if (checked)
        {
            // Unceck siblings
            for (auto& child : _getChildren())
            {
                if (child.get() == widgetPtr)
                {
                    continue;
                }

                child->setChecked(false);
            }
        }
    });

    Menu::addChild(widget);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
