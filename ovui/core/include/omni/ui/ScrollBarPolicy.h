/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Describes when the scroll bar should appear.
 */
enum class ScrollBarPolicy : uint8_t
{
    /**
     * @brief Show a scroll bar when the content is too big to fit to the provided area.
     */
    eScrollBarAsNeeded = 0,

    /**
     * @brief Never show a scroll bar.
     */
    eScrollBarAlwaysOff,

    /**
     * @brief Always show a scroll bar.
     */
    eScrollBarAlwaysOn
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
