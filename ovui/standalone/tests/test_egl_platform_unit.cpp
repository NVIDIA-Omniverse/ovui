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

// E2 unit test harness: exercises HeadlessEglPlatform stub interface.
// At E2 time createWindow() is a stub that returns kInvalidWindowId (exits 1).
// CTest registers this with WILL_FAIL TRUE — exit 1 is the correct outcome.
// After E4 flips WILL_FAIL to FALSE, the test must exit 0 (EGL init succeeds).
#include "../src/HeadlessEglPlatform.h"
#include <cstdio>

using omni::ui::standalone::HeadlessEglPlatform;
using omni::ui::WindowId;
using omni::ui::kInvalidWindowId;

int main()
{
    HeadlessEglPlatform platform;
    WindowId wid = platform.createWindow("test", 640, 480);
    if (wid == kInvalidWindowId) { fprintf(stderr, "createWindow failed\n"); return 1; }
    for (int i = 0; i < 3; ++i) platform.tick();
    platform.destroyWindow(wid);  // explicit cleanup; destructor also safe
    return 0;
}
