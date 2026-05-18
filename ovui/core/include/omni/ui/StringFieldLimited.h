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

#include "Callback.h"
#include "StringField.h"

#include <cstdint>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief A StringField with an optional maximum character length.
 *
 * Inherits every capability of StringField and adds a configurable character limit. When the limit is reached, further
 * input is blocked and an optional callback is invoked so the caller can provide visual feedback (e.g. change border
 * color, show a tooltip). Only instances of this class carry the extra bookkeeping -- plain StringField is untouched.
 */
class OMNIUI_CLASS_API StringFieldLimited : public StringField
{
    OMNIUI_OBJECT(StringFieldLimited)

public:
    /**
     * @brief This property holds the maximum number of characters allowed in the field.
     * 0 means no limit (uses ImGui's internal buffer limit).
     * When set, further input is blocked at the limit. When the limit is reached, the optional
     * character_limit_reached_fn callback is invoked (e.g. to customize style, tooltip, or drawing).
     */
    OMNIUI_PROPERTY(uint32_t, maxLength, DEFAULT, 0, READ, getMaxLength, WRITE, setMaxLength);

    /**
     * @brief Callback invoked when the "at character limit" state changes (reached limit or left limit).
     * at_limit is True when just reached limit, False when no longer at limit.
     * Use character_limit_reached_fn to customize feedback (e.g. style, tooltip, or drawing).
     */
    OMNIUI_CALLBACK(CharacterLimitReached, void, bool);

protected:
    struct StringFieldLimitedData;

    /**
     * @brief Constructs StringFieldLimited
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    StringFieldLimited(std::shared_ptr<AbstractValueModel> model = {});

    OMNIUI_API
    void _drawContent(float elapsedTime) override;

    OMNIUI_API
    void onModelUpdated() override;

private:
    std::string _generateTextForField() override;
    void _updateSystemText(void*) override;
    int32_t _getSystemFlags() const override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
