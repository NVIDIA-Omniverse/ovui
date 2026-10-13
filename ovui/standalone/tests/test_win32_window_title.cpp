/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "Win32WindowTitle.h"

#include <cstdio>
#include <string>
#include <vector>

using omni::ui::standalone::getWin32WindowTitle;
using omni::ui::standalone::setWin32WindowTitle;

static std::wstring readNativeTitle(HWND window)
{
    const int count = GetWindowTextLengthW(window);
    std::vector<wchar_t> title(static_cast<size_t>(count) + 1, L'\0');
    const int copied = GetWindowTextW(window, title.data(), static_cast<int>(title.size()));
    return copied > 0 ? std::wstring(title.data(), static_cast<size_t>(copied)) : std::wstring();
}

int main()
{
    const HINSTANCE instance = GetModuleHandleW(nullptr);
    const wchar_t* className = L"OvuiWindowTitleContractTest";
    WNDCLASSW windowClass{};
    windowClass.lpfnWndProc = DefWindowProcW;
    windowClass.hInstance = instance;
    windowClass.lpszClassName = className;
    if (!RegisterClassW(&windowClass) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
    {
        std::fprintf(stderr, "RegisterClassW failed: %lu\n", GetLastError());
        return 1;
    }

    HWND window = CreateWindowExW(
        0, className, L"USD Viewer", WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT, 640, 480,
        nullptr, nullptr, instance, nullptr);
    if (!window)
    {
        std::fprintf(stderr, "CreateWindowExW failed: %lu\n", GetLastError());
        return 1;
    }
    ShowWindow(window, SW_SHOWNORMAL);
    UpdateWindow(window);

    struct ExpectedTitle
    {
        const char* utf8;
        const wchar_t* wide;
    };
    const ExpectedTitle titles[] = {
        { "USD Viewer \xE2\x80\x94 C:\\Users\\viewer\\first scene.usda",
          L"USD Viewer \u2014 C:\\Users\\viewer\\first scene.usda" },
        { "USD Viewer \xE2\x80\x94 omniverse://server/projects/second.usdc",
          L"USD Viewer \u2014 omniverse://server/projects/second.usdc" },
        { "USD Viewer", L"USD Viewer" },
    };

    for (const ExpectedTitle& expected : titles)
    {
        if (!setWin32WindowTitle(window, expected.utf8))
        {
            std::fprintf(stderr, "production Win32 title setter rejected: %s\n", expected.utf8);
            DestroyWindow(window);
            return 1;
        }
        if (readNativeTitle(window) != expected.wide)
        {
            std::fprintf(stderr, "GetWindowTextW did not observe the requested native title\n");
            DestroyWindow(window);
            return 1;
        }
        if (getWin32WindowTitle(window) != expected.utf8)
        {
            std::fprintf(stderr, "production Win32 title getter disagreed with the HWND\n");
            DestroyWindow(window);
            return 1;
        }
    }

    DestroyWindow(window);
    UnregisterClassW(className, instance);
    return 0;
}
