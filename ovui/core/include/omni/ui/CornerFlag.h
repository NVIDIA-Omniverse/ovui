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

#include "Api.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Used to specify one or many corners of a rectangle.
 */
enum CornerFlag : uint32_t
{
    eNone = 0,
    eTopLeft = 1 << 0, // 0x1
    eTopRight = 1 << 1, // 0x2
    eBottomLeft = 1 << 2, // 0x4
    eBottomRight = 1 << 3, // 0x8
    eTop = eTopLeft | eTopRight, // 0x3
    eBottom = eBottomLeft | eBottomRight, // 0xC
    eLeft = eTopLeft | eBottomLeft, // 0x5
    eRight = eTopRight | eBottomRight, // 0xA
    eAll = 0xF // In your function calls you may use ~0 (= all bits sets) instead of ImDrawCornerFlags_All, as a
               // convenience
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
