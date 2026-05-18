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
#include <omni/ui/InvisibleButton.h>

#include "WidgetData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE


InvisibleButton::InvisibleButton(WidgetData* data) : Widget(data)
{
}

InvisibleButton::~InvisibleButton() = default;

void InvisibleButton::_drawContent(float elapsedTime)
{
    if (!this->isEnabled())
    {
        return;
    }

    float width = this->getComputedContentWidth();
    float height = this->getComputedContentHeight();

    // ImGui doesn't like when InvisibleButton has 0 size
    if (width > 0.0f && height > 0.0f)
    {
        // PR7: When the parent Stack sets AllowOverlap (ZStack with
        // send_mouse_events_to_back=false), propagate it to this
        // InvisibleButton so later-drawn siblings can take hover priority.
        if (_getData<WidgetData>().m_allowItemOverlap)
        {
            ImGui::SetNextItemAllowOverlap();
        }

        if (ImGui::InvisibleButton("", { width, height }))
        {
            _clicked();
            this->callClickedFn();
        }
    }
}

void InvisibleButton::_clicked()
{
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
