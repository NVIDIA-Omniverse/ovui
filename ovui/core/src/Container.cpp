/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
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
