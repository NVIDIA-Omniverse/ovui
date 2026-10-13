/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
