/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <string>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

namespace omni {
namespace ui {
namespace standalone {

bool setWin32WindowTitle(HWND window, const char* utf8Title);
std::string getWin32WindowTitle(HWND window);

} // namespace standalone
} // namespace ui
} // namespace omni
#endif
