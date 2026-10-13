/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "test_utils.h"
#include <cstdlib>

int getPixelTolerance()
{
    return 8;
}

bool checkPixel(const std::vector<uint8_t>& pixels, int w, int h,
                int x, int y, uint8_t r, uint8_t g, uint8_t b, int tol)
{
    if (x < 0 || x >= w || y < 0 || y >= h)
        return false;
    int idx = (y * w + x) * 4;
    return std::abs((int)pixels[idx + 0] - r) <= tol &&
           std::abs((int)pixels[idx + 1] - g) <= tol &&
           std::abs((int)pixels[idx + 2] - b) <= tol;
}
