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

#include <omni/ui/platform/IUiLog.h>

#include <cstdarg>
#include <cstdio>

namespace omni {
namespace ui {

/// Standalone log backend: prints to stderr with an [omni.ui] prefix.
/// Registered with PlatformRegistry during standalone::init().
class StandaloneLog : public IUiLog
{
public:
    void logError(const char* fmt, va_list args) override
    {
        fprintf(stderr, "[omni.ui] [error] ");
        vfprintf(stderr, fmt, args);
        fprintf(stderr, "\n");
    }

    void logWarn(const char* fmt, va_list args) override
    {
        fprintf(stderr, "[omni.ui] [warn] ");
        vfprintf(stderr, fmt, args);
        fprintf(stderr, "\n");
    }

    void logInfo(const char* fmt, va_list args) override
    {
        fprintf(stderr, "[omni.ui] [info] ");
        vfprintf(stderr, fmt, args);
        fprintf(stderr, "\n");
    }
};

} // namespace ui
} // namespace omni
