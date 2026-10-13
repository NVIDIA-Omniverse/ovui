/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "Api.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Used to specify how shadow is rendered
 */
enum ShadowFlag : uint8_t
{
    eNone = 0,
    eCutOutShapeBackground = 1 << 0   // Do not render the shadow shape under the objects to be shadowed to save on
                                      // fill-rate or facilitate blending. Slower on CPU.
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
