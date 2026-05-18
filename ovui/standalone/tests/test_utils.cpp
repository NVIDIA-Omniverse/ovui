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
