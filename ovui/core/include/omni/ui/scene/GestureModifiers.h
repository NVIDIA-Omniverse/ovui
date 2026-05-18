/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <cstdint>

#include "Api.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

// Keyboard modifier flag bitmask constants.
//
// Bit positions match carb::input::kKeyboardModifierFlag values exactly, so
// that modifier checks written against carb constants work identically when
// compared against values produced by SceneView::_captureInput().
//
//   carb::input::kKeyboardModifierFlagShift   = 1 << 0  = 1
//   carb::input::kKeyboardModifierFlagControl = 1 << 1  = 2
//   carb::input::kKeyboardModifierFlagAlt     = 1 << 2  = 4
//   carb::input::kKeyboardModifierFlagSuper   = 1 << 3  = 8
//
// Source: carb/input/InputTypes.h in Kit's carb headers.
constexpr uint32_t kModifierFlagShift   = 1u << 0;   // 1
constexpr uint32_t kModifierFlagControl = 1u << 1;   // 2
constexpr uint32_t kModifierFlagAlt     = 1u << 2;   // 4
constexpr uint32_t kModifierFlagSuper   = 1u << 3;   // 8

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
