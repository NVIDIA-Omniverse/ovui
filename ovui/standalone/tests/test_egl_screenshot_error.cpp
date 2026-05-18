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

// E7: Verify that hadLastScreenshotError() returns true when the screenshot
// path is unwritable, and that pollScreenshotDone() is set (no hang).
#include "StandaloneInit.h"
#include <cassert>
#include <cstdio>

namespace standalone = omni::ui::standalone;

int main()
{
    standalone::init("err_test", 320, 240);
    standalone::scheduleScreenshot("/nonexistent/dir/err_out.png");
    standalone::tick();
    assert(standalone::pollScreenshotDone());
    assert(standalone::hadLastScreenshotError());
    fprintf(stdout, "hadLastScreenshotError correctly returned true\n");
    standalone::shutdown();
    return 0;
}
