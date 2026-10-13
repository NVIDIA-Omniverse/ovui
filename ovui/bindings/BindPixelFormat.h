/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "PlatformBindings.h"

void wrapPixelFormat(pybind11::module_& m)
{
    omni::ui::registerPlatformPixelFormat(m);
}
