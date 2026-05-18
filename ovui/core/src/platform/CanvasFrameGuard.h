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

namespace omni {
namespace ui {

/// Data passed from CanvasFrame to Widget tooltip code.
/// Replaces the IO.UserData aliasing hack (SRD Section 6.15).
struct ActiveCanvasFrameInfo
{
    float cachedMousePosX = 0.0f;
    float cachedMousePosY = 0.0f;
};

/// Global pointer to the active canvas frame info.
/// Non-null only while inside a CanvasFrame's child draw section.
inline ActiveCanvasFrameInfo* g_activeCanvasFrameData = nullptr;

/// RAII guard that sets/restores g_activeCanvasFrameData.
/// Supports nesting (saves previous value and restores it).
struct CanvasFrameGuard
{
    ActiveCanvasFrameInfo* previous;
    CanvasFrameGuard(ActiveCanvasFrameInfo* data)
        : previous(g_activeCanvasFrameData)
    {
        g_activeCanvasFrameData = data;
    }
    ~CanvasFrameGuard()
    {
        g_activeCanvasFrameData = previous;
    }
    CanvasFrameGuard(const CanvasFrameGuard&) = delete;
    CanvasFrameGuard& operator=(const CanvasFrameGuard&) = delete;
};

} // namespace ui
} // namespace omni
