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

// Profiling macros that default to no-ops.
// In Kit mode, the adapter layer redefines these before any widget header is included
// to forward to the platform's native profiling infrastructure.
// In standalone mode, these can optionally be redirected to Tracy or another profiler
// via compile-time defines.

#ifndef OMNIUI_PROFILE_ZONE
#define OMNIUI_PROFILE_ZONE(name, ...) ((void)0)
#endif

#ifndef OMNIUI_PROFILE_FUNCTION
#define OMNIUI_PROFILE_FUNCTION ((void)0)
#endif

#ifndef OMNIUI_PROFILE_WIDGET_FUNCTION
#define OMNIUI_PROFILE_WIDGET_FUNCTION ((void)0)
#endif

// Verbose variants for recursive Widget layout/draw functions.
// Disabled by default even when profiling is enabled because the call volume
// causes measurable overhead. Enable by defining OMNIUI_PROFILE_VERBOSE before
// including this header (or pass -DOMNIUI_PROFILE_VERBOSE on the command line).

#ifdef OMNIUI_PROFILE_VERBOSE
#ifndef OMNIUI_PROFILE_VERBOSE_ZONE
#define OMNIUI_PROFILE_VERBOSE_ZONE(name, ...) OMNIUI_PROFILE_ZONE(name, ##__VA_ARGS__)
#endif
#ifndef OMNIUI_PROFILE_VERBOSE_FUNCTION
#define OMNIUI_PROFILE_VERBOSE_FUNCTION OMNIUI_PROFILE_FUNCTION
#endif
#ifndef OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION
#define OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION OMNIUI_PROFILE_WIDGET_FUNCTION
#endif
#else
#ifndef OMNIUI_PROFILE_VERBOSE_ZONE
#define OMNIUI_PROFILE_VERBOSE_ZONE(name, ...) ((void)0)
#endif
#ifndef OMNIUI_PROFILE_VERBOSE_FUNCTION
#define OMNIUI_PROFILE_VERBOSE_FUNCTION ((void)0)
#endif
#ifndef OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION
#define OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION ((void)0)
#endif
#endif
