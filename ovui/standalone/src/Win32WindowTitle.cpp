/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "Win32WindowTitle.h"

#ifdef _WIN32

#include <vector>

namespace omni {
namespace ui {
namespace standalone {

static std::wstring utf8ToWide(const char* text)
{
    if (!text)
        return {};
    const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, nullptr, 0);
    if (count <= 0)
        return {};
    std::wstring wide(static_cast<size_t>(count), L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, wide.data(), count) <= 0)
        return {};
    wide.resize(static_cast<size_t>(count - 1));
    return wide;
}

std::string getWin32WindowTitle(HWND window)
{
    if (!window)
        return {};
    const int wideCount = GetWindowTextLengthW(window);
    if (wideCount <= 0)
        return {};
    std::vector<wchar_t> wide(static_cast<size_t>(wideCount) + 1, L'\0');
    const int copied = GetWindowTextW(window, wide.data(), static_cast<int>(wide.size()));
    if (copied <= 0)
        return {};

    const int utf8Count = WideCharToMultiByte(
        CP_UTF8, WC_ERR_INVALID_CHARS, wide.data(), copied, nullptr, 0, nullptr, nullptr);
    if (utf8Count <= 0)
        return {};
    std::string utf8(static_cast<size_t>(utf8Count), '\0');
    if (WideCharToMultiByte(
            CP_UTF8, WC_ERR_INVALID_CHARS, wide.data(), copied,
            utf8.data(), utf8Count, nullptr, nullptr) <= 0)
        return {};
    return utf8;
}

bool setWin32WindowTitle(HWND window, const char* utf8Title)
{
    if (!window || !utf8Title)
        return false;
    const std::wstring wideTitle = utf8ToWide(utf8Title);
    if (wideTitle.empty() || !SetWindowTextW(window, wideTitle.c_str()))
        return false;
    RedrawWindow(
        window, nullptr, nullptr,
        RDW_FRAME | RDW_INVALIDATE | RDW_UPDATENOW);
    return getWin32WindowTitle(window) == utf8Title;
}

} // namespace standalone
} // namespace ui
} // namespace omni

#endif
