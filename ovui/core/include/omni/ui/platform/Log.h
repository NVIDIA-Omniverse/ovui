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
#include <omni/ui/platform/PlatformRegistry.h>

#include <cstdarg>

// Logging macros for omni.ui core.
//
// Messages are routed through the IUiLog implementation registered in
// PlatformRegistry. If no backend is registered, messages are silently
// dropped. Kit registers KitLogAdapter; standalone registers StandaloneLog.
//
// This header is intentionally header-only: the inline dispatch functions
// forward to the registered IUiLog backend. No implementation logic lives
// in shared/core -- all actual logging behavior is in the backends.
//
// NOTE: These macros append a newline. Do NOT include trailing \n in format strings.

namespace omni {
namespace ui {
namespace log {

inline void error(const char* fmt, ...)
{
    IUiLog* logger = PlatformRegistry::instance().log();
    if (!logger)
        return;
    va_list args;
    va_start(args, fmt);
    logger->logError(fmt, args);
    va_end(args);
}

inline void warn(const char* fmt, ...)
{
    IUiLog* logger = PlatformRegistry::instance().log();
    if (!logger)
        return;
    va_list args;
    va_start(args, fmt);
    logger->logWarn(fmt, args);
    va_end(args);
}

inline void info(const char* fmt, ...)
{
    IUiLog* logger = PlatformRegistry::instance().log();
    if (!logger)
        return;
    va_list args;
    va_start(args, fmt);
    logger->logInfo(fmt, args);
    va_end(args);
}

} // namespace log
} // namespace ui
} // namespace omni

#ifndef OMNIUI_LOG_ERROR
#define OMNIUI_LOG_ERROR(fmt, ...) ::omni::ui::log::error(fmt, ##__VA_ARGS__)
#endif

#ifndef OMNIUI_LOG_WARN
#define OMNIUI_LOG_WARN(fmt, ...) ::omni::ui::log::warn(fmt, ##__VA_ARGS__)
#endif

#ifndef OMNIUI_LOG_INFO
#define OMNIUI_LOG_INFO(fmt, ...) ::omni::ui::log::info(fmt, ##__VA_ARGS__)
#endif

// Log-once variants: emit the message only on the first call per call site.
// Use for deprecated API warnings or error conditions that would spam every frame.
#ifndef OMNIUI_LOG_ERROR_ONCE
#define OMNIUI_LOG_ERROR_ONCE(fmt, ...) do { static bool _logged = false; \
    if (!_logged) { _logged = true; OMNIUI_LOG_ERROR(fmt, ##__VA_ARGS__); } } while(0)
#endif

#ifndef OMNIUI_LOG_WARN_ONCE
#define OMNIUI_LOG_WARN_ONCE(fmt, ...) do { static bool _logged = false; \
    if (!_logged) { _logged = true; OMNIUI_LOG_WARN(fmt, ##__VA_ARGS__); } } while(0)
#endif
