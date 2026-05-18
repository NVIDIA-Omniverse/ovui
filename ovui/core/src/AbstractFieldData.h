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

#pragma once

#include <omni/ui/AbstractField.h>
#include <omni/ui/Rectangle.h>

#include "WidgetData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct AbstractField::AbstractFieldData : public Widget::WidgetData
{
    ~AbstractFieldData() override = default;

    // The text of the model. It's cached because we can't query the model every frame because the model can be written
    // in python and query filesystem or USD.
    std::string m_textModelCache = {};

    // Internal cache. It represents the text in the field see AbstractField::onModelUpdated() for the description why
    // it's a vector.
    std::vector<char> m_textBuffer;

    // The rectangle used instead of the background
    std::shared_ptr<Rectangle> m_backgroundRect;

    // We change ID every time the user wants to defocus this field.
    int m_underlyingId = 0;
    // True if the cursor is in the field
    bool m_fieldActive = false;
    // Puts cursor to this field.
    bool m_focusKeyboard = false;
    // Flag that specifies that the model is changed because the user pressed a key.
    bool m_isModelChangedInternally = false;
    // Force set content from the model.
    bool m_forceContentChange = false;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
