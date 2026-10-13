/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

enum class Axis : uint8_t
{
    eNone = 0,
    eX = 1,
    eY = 2,
    eXY = 3,
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
