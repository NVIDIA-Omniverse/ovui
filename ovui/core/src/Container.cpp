/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/Container.h>
#include "platform/Log.h"

#include "ContainerData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

Container::Container(ContainerData* data)
    : Widget(data)
{
}

Container::~Container() = default;

void Container::addChild(std::shared_ptr<Widget> widget)
{
    if (widget)
    {
        OMNIUI_LOG_ERROR("Container::addChild was reached but is unimplemented, omni::ui::Widget['%s'] = %p",
            widget->getIdentifier().c_str(), widget.get());
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
