/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#include "imgui_kit_compat.h"
namespace ImGui::KitCompatibility
{
namespace { thread_local float legacyPower = 1.0f; }
float getLegacyPower() { return legacyPower; }
float setLegacyPower(float power)
{
    const float previous = legacyPower;
    legacyPower = power;
    return previous;
}
}
