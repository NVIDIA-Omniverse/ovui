/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

// Reverse of ImGui_ImplGlfw_KeyToImGuiKey: maps ImGuiKey values back to the
// GLFW key codes that ``key_pressed_fn`` / ``set_key_pressed_fn`` callbacks
// have always reported. Pre-1.87 ImGui used a dense 0..511 key space where
// the legacy index happened to equal the GLFW code; ImGui 1.87+ moved named
// keys to [512..) via ``io.AddKeyEvent(ImGuiKey_X)``, so iterating 0..256
// and forwarding the raw index (what ``Window::_updateWindow`` and
// ``Widget::_update`` used to do) never fires for any real keyboard input.
//
// Callers should iterate [ImGuiKey_NamedKey_BEGIN, ImGuiKey_NamedKey_END)
// and translate to GLFW codes before invoking user callbacks so existing
// Python handlers (ord('W'), ord('Z'), GLFW_KEY_F2=291, etc.) keep working.
#pragma once

#include <imgui/imgui.h>

namespace omni {
namespace ui {
namespace detail {

// GLFW key codes (copied from glfw3.h so we don't need a GLFW dependency here).
// Only the subset ImGui_ImplGlfw_KeyToImGuiKey can produce is covered.
inline int imguiKeyToGlfwKey(ImGuiKey key)
{
    switch (key)
    {
        case ImGuiKey_Tab: return 258;            // GLFW_KEY_TAB
        case ImGuiKey_LeftArrow: return 263;      // GLFW_KEY_LEFT
        case ImGuiKey_RightArrow: return 262;     // GLFW_KEY_RIGHT
        case ImGuiKey_UpArrow: return 265;        // GLFW_KEY_UP
        case ImGuiKey_DownArrow: return 264;      // GLFW_KEY_DOWN
        case ImGuiKey_PageUp: return 266;         // GLFW_KEY_PAGE_UP
        case ImGuiKey_PageDown: return 267;       // GLFW_KEY_PAGE_DOWN
        case ImGuiKey_Home: return 268;           // GLFW_KEY_HOME
        case ImGuiKey_End: return 269;            // GLFW_KEY_END
        case ImGuiKey_Insert: return 260;         // GLFW_KEY_INSERT
        case ImGuiKey_Delete: return 261;         // GLFW_KEY_DELETE
        case ImGuiKey_Backspace: return 259;      // GLFW_KEY_BACKSPACE
        case ImGuiKey_Space: return 32;           // GLFW_KEY_SPACE
        case ImGuiKey_Enter: return 257;          // GLFW_KEY_ENTER
        case ImGuiKey_Escape: return 256;         // GLFW_KEY_ESCAPE
        case ImGuiKey_Apostrophe: return 39;      // GLFW_KEY_APOSTROPHE
        case ImGuiKey_Comma: return 44;           // GLFW_KEY_COMMA
        case ImGuiKey_Minus: return 45;           // GLFW_KEY_MINUS
        case ImGuiKey_Period: return 46;          // GLFW_KEY_PERIOD
        case ImGuiKey_Slash: return 47;           // GLFW_KEY_SLASH
        case ImGuiKey_Semicolon: return 59;       // GLFW_KEY_SEMICOLON
        case ImGuiKey_Equal: return 61;           // GLFW_KEY_EQUAL
        case ImGuiKey_LeftBracket: return 91;     // GLFW_KEY_LEFT_BRACKET
        case ImGuiKey_Backslash: return 92;       // GLFW_KEY_BACKSLASH
        case ImGuiKey_RightBracket: return 93;    // GLFW_KEY_RIGHT_BRACKET
        case ImGuiKey_GraveAccent: return 96;     // GLFW_KEY_GRAVE_ACCENT
        case ImGuiKey_CapsLock: return 280;       // GLFW_KEY_CAPS_LOCK
        case ImGuiKey_ScrollLock: return 281;     // GLFW_KEY_SCROLL_LOCK
        case ImGuiKey_NumLock: return 282;        // GLFW_KEY_NUM_LOCK
        case ImGuiKey_PrintScreen: return 283;    // GLFW_KEY_PRINT_SCREEN
        case ImGuiKey_Pause: return 284;          // GLFW_KEY_PAUSE
        case ImGuiKey_Keypad0: return 320;
        case ImGuiKey_Keypad1: return 321;
        case ImGuiKey_Keypad2: return 322;
        case ImGuiKey_Keypad3: return 323;
        case ImGuiKey_Keypad4: return 324;
        case ImGuiKey_Keypad5: return 325;
        case ImGuiKey_Keypad6: return 326;
        case ImGuiKey_Keypad7: return 327;
        case ImGuiKey_Keypad8: return 328;
        case ImGuiKey_Keypad9: return 329;
        case ImGuiKey_KeypadDecimal: return 330;
        case ImGuiKey_KeypadDivide: return 331;
        case ImGuiKey_KeypadMultiply: return 332;
        case ImGuiKey_KeypadSubtract: return 333;
        case ImGuiKey_KeypadAdd: return 334;
        case ImGuiKey_KeypadEnter: return 335;
        case ImGuiKey_KeypadEqual: return 336;
        case ImGuiKey_LeftShift: return 340;
        case ImGuiKey_LeftCtrl: return 341;
        case ImGuiKey_LeftAlt: return 342;
        case ImGuiKey_LeftSuper: return 343;
        case ImGuiKey_RightShift: return 344;
        case ImGuiKey_RightCtrl: return 345;
        case ImGuiKey_RightAlt: return 346;
        case ImGuiKey_RightSuper: return 347;
        case ImGuiKey_Menu: return 348;
        case ImGuiKey_0: return 48;
        case ImGuiKey_1: return 49;
        case ImGuiKey_2: return 50;
        case ImGuiKey_3: return 51;
        case ImGuiKey_4: return 52;
        case ImGuiKey_5: return 53;
        case ImGuiKey_6: return 54;
        case ImGuiKey_7: return 55;
        case ImGuiKey_8: return 56;
        case ImGuiKey_9: return 57;
        case ImGuiKey_A: return 65;
        case ImGuiKey_B: return 66;
        case ImGuiKey_C: return 67;
        case ImGuiKey_D: return 68;
        case ImGuiKey_E: return 69;
        case ImGuiKey_F: return 70;
        case ImGuiKey_G: return 71;
        case ImGuiKey_H: return 72;
        case ImGuiKey_I: return 73;
        case ImGuiKey_J: return 74;
        case ImGuiKey_K: return 75;
        case ImGuiKey_L: return 76;
        case ImGuiKey_M: return 77;
        case ImGuiKey_N: return 78;
        case ImGuiKey_O: return 79;
        case ImGuiKey_P: return 80;
        case ImGuiKey_Q: return 81;
        case ImGuiKey_R: return 82;
        case ImGuiKey_S: return 83;
        case ImGuiKey_T: return 84;
        case ImGuiKey_U: return 85;
        case ImGuiKey_V: return 86;
        case ImGuiKey_W: return 87;
        case ImGuiKey_X: return 88;
        case ImGuiKey_Y: return 89;
        case ImGuiKey_Z: return 90;
        case ImGuiKey_F1: return 290;
        case ImGuiKey_F2: return 291;
        case ImGuiKey_F3: return 292;
        case ImGuiKey_F4: return 293;
        case ImGuiKey_F5: return 294;
        case ImGuiKey_F6: return 295;
        case ImGuiKey_F7: return 296;
        case ImGuiKey_F8: return 297;
        case ImGuiKey_F9: return 298;
        case ImGuiKey_F10: return 299;
        case ImGuiKey_F11: return 300;
        case ImGuiKey_F12: return 301;
        case ImGuiKey_F13: return 302;
        case ImGuiKey_F14: return 303;
        case ImGuiKey_F15: return 304;
        case ImGuiKey_F16: return 305;
        case ImGuiKey_F17: return 306;
        case ImGuiKey_F18: return 307;
        case ImGuiKey_F19: return 308;
        case ImGuiKey_F20: return 309;
        case ImGuiKey_F21: return 310;
        case ImGuiKey_F22: return 311;
        case ImGuiKey_F23: return 312;
        case ImGuiKey_F24: return 313;
        default: return 0;
    }
}

inline ImGuiKey normalizeInjectedImguiKey(int key)
{
    if (key >= ImGuiKey_NamedKey_BEGIN && key < ImGuiKey_NamedKey_END)
    {
        return static_cast<ImGuiKey>(key);
    }

    switch (key)
    {
        // Common pre-1.87 ImGui / ASCII control key values.
        case 8: return ImGuiKey_Backspace;
        case 9: return ImGuiKey_Tab;
        case 13: return ImGuiKey_Enter;
        case 27: return ImGuiKey_Escape;
        case 32: return ImGuiKey_Space;

        // GLFW key values used by standalone keyboard callbacks.
        case 256: return ImGuiKey_Escape;
        case 257: return ImGuiKey_Enter;
        case 258: return ImGuiKey_Tab;
        case 259: return ImGuiKey_Backspace;
        case 260: return ImGuiKey_Insert;
        case 261: return ImGuiKey_Delete;
        case 262: return ImGuiKey_RightArrow;
        case 263: return ImGuiKey_LeftArrow;
        case 264: return ImGuiKey_DownArrow;
        case 265: return ImGuiKey_UpArrow;
        case 266: return ImGuiKey_PageUp;
        case 267: return ImGuiKey_PageDown;
        case 268: return ImGuiKey_Home;
        case 269: return ImGuiKey_End;
        default: break;
    }

    if (key >= '0' && key <= '9')
    {
        return static_cast<ImGuiKey>(static_cast<int>(ImGuiKey_0) + (key - '0'));
    }
    if (key >= 'A' && key <= 'Z')
    {
        return static_cast<ImGuiKey>(static_cast<int>(ImGuiKey_A) + (key - 'A'));
    }
    if (key >= 'a' && key <= 'z')
    {
        return static_cast<ImGuiKey>(static_cast<int>(ImGuiKey_A) + (key - 'a'));
    }
    if (key >= 290 && key <= 313)
    {
        return static_cast<ImGuiKey>(static_cast<int>(ImGuiKey_F1) + (key - 290));
    }
    if (key >= 320 && key <= 329)
    {
        return static_cast<ImGuiKey>(static_cast<int>(ImGuiKey_Keypad0) + (key - 320));
    }

    switch (key)
    {
        case 39: return ImGuiKey_Apostrophe;
        case 44: return ImGuiKey_Comma;
        case 45: return ImGuiKey_Minus;
        case 46: return ImGuiKey_Period;
        case 47: return ImGuiKey_Slash;
        case 59: return ImGuiKey_Semicolon;
        case 61: return ImGuiKey_Equal;
        case 91: return ImGuiKey_LeftBracket;
        case 92: return ImGuiKey_Backslash;
        case 93: return ImGuiKey_RightBracket;
        case 96: return ImGuiKey_GraveAccent;
        case 280: return ImGuiKey_CapsLock;
        case 281: return ImGuiKey_ScrollLock;
        case 282: return ImGuiKey_NumLock;
        case 283: return ImGuiKey_PrintScreen;
        case 284: return ImGuiKey_Pause;
        case 330: return ImGuiKey_KeypadDecimal;
        case 331: return ImGuiKey_KeypadDivide;
        case 332: return ImGuiKey_KeypadMultiply;
        case 333: return ImGuiKey_KeypadSubtract;
        case 334: return ImGuiKey_KeypadAdd;
        case 335: return ImGuiKey_KeypadEnter;
        case 336: return ImGuiKey_KeypadEqual;
        case 340: return ImGuiKey_LeftShift;
        case 341: return ImGuiKey_LeftCtrl;
        case 342: return ImGuiKey_LeftAlt;
        case 343: return ImGuiKey_LeftSuper;
        case 344: return ImGuiKey_RightShift;
        case 345: return ImGuiKey_RightCtrl;
        case 346: return ImGuiKey_RightAlt;
        case 347: return ImGuiKey_RightSuper;
        case 348: return ImGuiKey_Menu;
        default: return ImGuiKey_None;
    }
}

}  // namespace detail
}  // namespace ui
}  // namespace omni
