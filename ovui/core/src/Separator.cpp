/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "platform/Log.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Separator.h>

#include "WidgetData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Separator::SeparatorData : public Widget::WidgetData
{
    ~SeparatorData() override = default;
};

Separator::Separator(const std::string& text)
    : MenuItem(text, new SeparatorData)
{
}

Separator::~Separator() = default;

void Separator::cascadeStyle()
{
    MenuItem::cascadeStyle();

    // Separator is always disabled, so it's not highlighted when hovered
    this->setEnabled(false);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
