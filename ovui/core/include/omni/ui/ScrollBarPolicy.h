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
