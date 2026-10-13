/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

//! @file
//!
//! @brief omni::ui Alignment types.
#pragma once

#include "Api.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Used when it's necessary to align the content to the wigget.
 */
enum Alignment : uint8_t
{
    eUndefined = 0,

    eLeft = 1 << 1,
    eRight = 1 << 2,
    eHCenter = 1 << 3,

    eTop = 1 << 4,
    eBottom = 1 << 5,
    eVCenter = 1 << 6,

    eLeftTop = eLeft | eTop,
    eLeftCenter = eLeft | eVCenter,
    eLeftBottom = eLeft | eBottom,

    eCenterTop = eHCenter | eTop,
    eCenter = eHCenter | eVCenter,
    eCenterBottom = eHCenter | eBottom,

    eRightTop = eRight | eTop,
    eRightCenter = eRight | eVCenter,
    eRightBottom = eRight | eBottom,
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
