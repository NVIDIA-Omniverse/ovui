/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
