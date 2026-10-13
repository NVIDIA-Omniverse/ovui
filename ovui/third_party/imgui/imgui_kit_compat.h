/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once
#include "imgui.h"
#include <algorithm>
#include <cmath>
namespace ImGui::KitCompatibility
{
// Private, non-overlapping status bit in the pinned 1.92.7 item-status layout.
constexpr int kHoveredTreeArrow = 1 << 27;
IMGUI_API float getLegacyPower();
IMGUI_API float setLegacyPower(float power);
struct ScopedLegacyPower
{
    explicit ScopedLegacyPower(float power) : previous(setLegacyPower(power)) {}
    ~ScopedLegacyPower() { setLegacyPower(previous); }
    const float previous;
};
inline bool hasLegacyPower(ImGuiDataType type)
{
    return getLegacyPower() != 1.0f && (type == ImGuiDataType_Float || type == ImGuiDataType_Double);
}
// These are the old public carb.imgui power-curve formulas, including the
// symmetric split at zero. They are active only inside a legacy API call.
template<class T> float zeroPosition(T low, T high, float power)
{
    if (low * high < T(0))
    {
        const T a = std::pow(std::abs(low), T(1) / power);
        const T b = std::pow(std::abs(high), T(1) / power);
        return float(a / (a + b));
    }
    return low < T(0) ? 1.0f : 0.0f;
}
template<class T> float ratio(T value, T low, T high, float power)
{
    if (low == high) return 0.0f;
    value = std::max(std::min(low, high), std::min(std::max(low, high), value));
    const float zero = zeroPosition(low, high, power);
    if (value < T(0))
    {
        const float fraction = 1.0f - float((value - low) / (std::min(T(0), high) - low));
        return (1.0f - std::pow(fraction, 1.0f / power)) * zero;
    }
    const float fraction = float((value - std::max(T(0), low)) / (high - std::max(T(0), low)));
    return zero + std::pow(fraction, 1.0f / power) * (1.0f - zero);
}
template<class T> T value(float position, T low, T high, float power)
{
    if (position <= 0.0f || low == high) return low;
    if (position >= 1.0f) return high;
    const float zero = zeroPosition(low, high, power);
    if (position < zero)
    {
        const float fraction = std::pow(1.0f - position / zero, power);
        const T start = std::min(high, T(0));
        return start + (low - start) * fraction;
    }
    const float fraction = std::pow(std::abs(zero - 1.0f) > 1.e-6f ?
                                   (position - zero) / (1.0f - zero) : position, power);
    const T start = std::max(low, T(0));
    return start + (high - start) * fraction;
}
}
