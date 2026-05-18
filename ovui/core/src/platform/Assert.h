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

#include <cassert>

// OMNIUI_ASSERT supports optional message: OMNIUI_ASSERT(expr) or OMNIUI_ASSERT(expr, "msg")
// The message is ignored at runtime but serves as documentation.
#ifndef OMNIUI_ASSERT
#define OMNIUI_ASSERT_1(expr) assert(expr)
#define OMNIUI_ASSERT_2(expr, msg) assert((expr) && (msg))
#define OMNIUI_ASSERT_GET_MACRO(_1, _2, NAME, ...) NAME
#define OMNIUI_ASSERT(...) OMNIUI_ASSERT_GET_MACRO(__VA_ARGS__, OMNIUI_ASSERT_2, OMNIUI_ASSERT_1)(__VA_ARGS__)
#endif

// Branch prediction hints for likely/unlikely conditions.
// Use __builtin_expect on GCC/Clang (works on all versions including C++20).
// Note: C++20 [[likely]]/[[unlikely]] are statement attributes, not expression
// attributes, so they cannot be used as drop-in replacements for the
// __builtin_expect expression pattern used by OMNIUI_LIKELY(x).
#if defined(__GNUC__) || defined(__clang__)
#define OMNIUI_LIKELY(x) (__builtin_expect(!!(x), 1))
#define OMNIUI_UNLIKELY(x) (__builtin_expect(!!(x), 0))
#else
#define OMNIUI_LIKELY(x) (!!(x))
#define OMNIUI_UNLIKELY(x) (!!(x))
#endif
