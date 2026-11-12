/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <imgui/imgui.h>

#include <string>

namespace omni
{
namespace ui
{
namespace standalone
{

inline std::string& headlessClipboardText()
{
    static std::string text;
    return text;
}

inline const char* getHeadlessClipboard(ImGuiContext*)
{
    return headlessClipboardText().c_str();
}

inline void setHeadlessClipboard(ImGuiContext*, const char* text)
{
    headlessClipboardText() = text ? text : "";
}

/// Give the current ImGui context a clipboard that lives in this process.
///
/// A headless run has no window, so it must not read or write the clipboard of
/// the user. Without this, Windows uses the default ImGui handler, which calls
/// the real Windows clipboard. Call it after ImGui::CreateContext().
inline void installHeadlessClipboard()
{
    ImGuiPlatformIO& platformIO = ImGui::GetPlatformIO();
    platformIO.Platform_GetClipboardTextFn = getHeadlessClipboard;
    platformIO.Platform_SetClipboardTextFn = setHeadlessClipboard;
}

/// True when the current ImGui context uses the clipboard of this process.
inline bool isHeadlessClipboardInstalled()
{
    if (!ImGui::GetCurrentContext())
        return false;
    const ImGuiPlatformIO& platformIO = ImGui::GetPlatformIO();
    return platformIO.Platform_GetClipboardTextFn == getHeadlessClipboard &&
           platformIO.Platform_SetClipboardTextFn == setHeadlessClipboard;
}

} // namespace standalone
} // namespace ui
} // namespace omni
