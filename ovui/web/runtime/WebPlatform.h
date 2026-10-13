/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <cstddef>
#include <string>

namespace omni {
namespace ui {
namespace web {

bool init(const char* canvasSelector, int width, int height, float devicePixelRatio = 1.0f);
bool tick();
void shutdown();
void resetWorkspace();
bool setCanvasSize(int width, int height, float devicePixelRatio = 1.0f);
size_t windowCallbackCount();
std::string backendInfo();
std::string fontInfo();
std::string dpiInfo();

} // namespace web
} // namespace ui
} // namespace omni
