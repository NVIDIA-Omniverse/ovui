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

#include <cstdarg>

namespace omni {
namespace ui {

/// Abstract logging interface for omni.ui core.
///
/// In Kit mode, KitLogAdapter routes messages through Carbonite logging.
/// In standalone mode, StandaloneLog prints to stderr.
///
/// Implementations receive a printf-style format string and a va_list.
class IUiLog
{
public:
    virtual ~IUiLog() = default;

    virtual void logError(const char* fmt, va_list args) = 0;
    virtual void logWarn(const char* fmt, va_list args) = 0;
    virtual void logInfo(const char* fmt, va_list args) = 0;

    /// Dump the current Python call stack for diagnostic purposes.
    /// Kit implements this via IApp/IPythonScripting; standalone is a no-op.
    virtual void dumpPythonStack(bool toStdOut = false) { (void)toStdOut; }
};

} // namespace ui
} // namespace omni
