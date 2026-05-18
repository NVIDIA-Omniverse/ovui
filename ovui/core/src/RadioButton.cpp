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

#include "platform/Log.h"

#include <omni/ui/RadioButton.h>
#include <omni/ui/RadioCollection.h>

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

RadioButton::RadioButton() : Button{}
{
    // TODO: The way to move the button from one collection to another
    this->onRadioCollectionChangedFn([this](const auto& collection) { collection->_addRadioButton(this->castShared()); });
}

RadioButton::~RadioButton() = default;

void RadioButton::_clicked()
{
    const auto collection = this->getRadioCollection();
    if (!collection)
    {
        // TODO: Warning
        return;
    }

    collection->_clicked(this);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
