/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once
#include <cstdint>
#include <vector>

int getPixelTolerance();
bool checkPixel(const std::vector<uint8_t>& pixels, int w, int h,
                int x, int y, uint8_t r, uint8_t g, uint8_t b, int tol);
