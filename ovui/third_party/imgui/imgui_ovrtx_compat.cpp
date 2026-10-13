/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
// ImGui 1.77 entry points imported by public OVRTX 0.4/0.5.
//
// A process has one library named imgui. Renderers built against ImGui 1.77
// (for example public OVRTX 0.4/0.5, whose static carb.imgui wrapper imports
// the whole 1.77 API) import these old signatures by name. They are defined
// here so the process' single ImGui satisfies those imports: Windows binds
// every import at load time, and a missing one fails the load.
//
// They are inert: they draw nothing and return neutral values. They are only
// called by the old ImGui wrapper's debug UI, which cannot run on this ImGui.
//
// Self-contained: removing this file and its build line removes the compat.
// This file deliberately does not include imgui.h: the old signatures are
// declared with the 1.77 types they were compiled with (plain int flags,
// void* texture ids), which only exist here to give the symbols their names.

#ifndef IMGUI_API
#define IMGUI_API
#endif

typedef unsigned int ImU32;
typedef unsigned int ImGuiID;
struct ImVec2 { float x, y; };
struct ImVec4 { float x, y, z, w; };
struct ImDrawCmd;
struct ImFont;
struct ImGuiViewport;
struct ImGuiWindowClass;

struct ImDrawList
{
    IMGUI_API void AddCallback(void (*callback)(const ImDrawList*, const ImDrawCmd*), void* callback_data);
    IMGUI_API void AddPolyline(const ImVec2* points, int num_points, ImU32 col, bool closed, float thickness);
    IMGUI_API void AddImageQuad(void* tex, const ImVec2& p1, const ImVec2& p2, const ImVec2& p3, const ImVec2& p4,
                                const ImVec2& uv1, const ImVec2& uv2, const ImVec2& uv3, const ImVec2& uv4, ImU32 col);
    IMGUI_API void AddBezierCurve(const ImVec2& p1, const ImVec2& p2, const ImVec2& p3, const ImVec2& p4, ImU32 col,
                                  float thickness, int num_segments);
    IMGUI_API void AddImageRounded(void* tex, const ImVec2& p_min, const ImVec2& p_max, const ImVec2& uv_min,
                                   const ImVec2& uv_max, ImU32 col, float rounding, int rounding_corners);
    IMGUI_API void AddText(const ImFont* font, float font_size, const ImVec2& pos, ImU32 col, const char* text_begin,
                           const char* text_end, float wrap_width, const ImVec4* cpu_fine_clip_rect);
    IMGUI_API void AddImage(void* tex, const ImVec2& p_min, const ImVec2& p_max, const ImVec2& uv_min,
                            const ImVec2& uv_max, ImU32 col);
};

void ImDrawList::AddCallback(void (*)(const ImDrawList*, const ImDrawCmd*), void*) {}
void ImDrawList::AddPolyline(const ImVec2*, int, ImU32, bool, float) {}
void ImDrawList::AddImageQuad(void*, const ImVec2&, const ImVec2&, const ImVec2&, const ImVec2&, const ImVec2&,
                              const ImVec2&, const ImVec2&, const ImVec2&, ImU32) {}
void ImDrawList::AddBezierCurve(const ImVec2&, const ImVec2&, const ImVec2&, const ImVec2&, ImU32, float, int) {}
void ImDrawList::AddImageRounded(void*, const ImVec2&, const ImVec2&, const ImVec2&, const ImVec2&, ImU32, float, int) {}
void ImDrawList::AddText(const ImFont*, float, const ImVec2&, ImU32, const char*, const char*, float, const ImVec4*) {}
void ImDrawList::AddImage(void*, const ImVec2&, const ImVec2&, const ImVec2&, const ImVec2&, ImU32) {}

namespace ImGui
{
// Windows and child windows
IMGUI_API bool BeginChild(const char*, const ImVec2&, bool, int) { return false; }
IMGUI_API bool BeginChild(ImGuiID, const ImVec2&, bool, int) { return false; }
IMGUI_API bool BeginChildFrame(ImGuiID, const ImVec2&, int) { return false; }
IMGUI_API void EndChildFrame() {}
IMGUI_API float GetWindowContentRegionWidth() { return 0.0f; }
IMGUI_API ImU32 GetColorU32(ImU32 col) { return col; }
IMGUI_API void PushFont(ImFont*) {}
IMGUI_API void PushAllowKeyboardFocus(bool) {}
IMGUI_API void PopAllowKeyboardFocus() {}
IMGUI_API void PushButtonRepeat(bool) {}
IMGUI_API void PopButtonRepeat() {}

// Widgets
IMGUI_API bool ArrowButton(const char*, int) { return false; }
IMGUI_API bool InvisibleButton(const char*, const ImVec2&) { return false; }
IMGUI_API void Image(void*, const ImVec2&, const ImVec2&, const ImVec2&, const ImVec4&, const ImVec4&) {}
IMGUI_API bool ImageButton(void*, const ImVec2&, const ImVec2&, const ImVec2&, int, const ImVec4&, const ImVec4&) { return false; }
IMGUI_API bool ColorButton(const char*, const ImVec4&, int, ImVec2) { return false; }
IMGUI_API bool DragFloat(const char*, float*, float, float, float, const char*, float) { return false; }
IMGUI_API bool DragFloat2(const char*, float[2], float, float, float, const char*, float) { return false; }
IMGUI_API bool DragFloat3(const char*, float[3], float, float, float, const char*, float) { return false; }
IMGUI_API bool DragFloat4(const char*, float[4], float, float, float, const char*, float) { return false; }
IMGUI_API bool DragFloatRange2(const char*, float*, float*, float, float, float, const char*, const char*, float) { return false; }
IMGUI_API bool DragInt(const char*, int*, float, int, int, const char*) { return false; }
IMGUI_API bool DragInt2(const char*, int[2], float, int, int, const char*) { return false; }
IMGUI_API bool DragInt3(const char*, int[3], float, int, int, const char*) { return false; }
IMGUI_API bool DragInt4(const char*, int[4], float, int, int, const char*) { return false; }
IMGUI_API bool DragIntRange2(const char*, int*, int*, float, int, int, const char*, const char*) { return false; }
IMGUI_API bool DragScalar(const char*, int, void*, float, const void*, const void*, const char*, float) { return false; }
IMGUI_API bool DragScalarN(const char*, int, void*, int, float, const void*, const void*, const char*, float) { return false; }
IMGUI_API bool SliderFloat(const char*, float*, float, float, const char*, float) { return false; }
IMGUI_API bool SliderFloat2(const char*, float[2], float, float, const char*, float) { return false; }
IMGUI_API bool SliderFloat3(const char*, float[3], float, float, const char*, float) { return false; }
IMGUI_API bool SliderFloat4(const char*, float[4], float, float, const char*, float) { return false; }
IMGUI_API bool SliderAngle(const char*, float*, float, float, const char*) { return false; }
IMGUI_API bool SliderInt(const char*, int*, int, int, const char*) { return false; }
IMGUI_API bool SliderInt2(const char*, int[2], int, int, const char*) { return false; }
IMGUI_API bool SliderInt3(const char*, int[3], int, int, const char*) { return false; }
IMGUI_API bool SliderInt4(const char*, int[4], int, int, const char*) { return false; }
IMGUI_API bool SliderScalar(const char*, int, void*, const void*, const void*, const char*, float) { return false; }
IMGUI_API bool SliderScalarN(const char*, int, void*, int, const void*, const void*, const char*, float) { return false; }
IMGUI_API bool VSliderFloat(const char*, const ImVec2&, float*, float, float, const char*, float) { return false; }
IMGUI_API bool VSliderInt(const char*, const ImVec2&, int*, int, int, const char*) { return false; }
IMGUI_API bool VSliderScalar(const char*, const ImVec2&, int, void*, const void*, const void*, const char*, float) { return false; }
IMGUI_API bool InputFloat(const char*, float*, float, float, int, int) { return false; }
IMGUI_API bool InputFloat2(const char*, float[2], int, int) { return false; }
IMGUI_API bool InputFloat3(const char*, float[3], int, int) { return false; }
IMGUI_API bool InputFloat4(const char*, float[4], int, int) { return false; }
IMGUI_API bool ListBox(const char*, int*, bool (*)(void*, int, const char**), void*, int, int) { return false; }
IMGUI_API bool ListBoxHeader(const char*, const ImVec2&) { return false; }
IMGUI_API bool ListBoxHeader(const char*, int, int) { return false; }
IMGUI_API void ListBoxFooter() {}

// Popups, docking, items and inputs
IMGUI_API void OpenPopup(const char*) {}
IMGUI_API bool IsPopupOpen(const char*) { return false; }
IMGUI_API bool BeginPopupContextWindow(const char*, int, bool) { return false; }
IMGUI_API ImGuiID DockSpaceOverViewport(ImGuiViewport*, int, const ImGuiWindowClass*) { return 0; }
IMGUI_API ImGuiID DockBuilderSplitNode(ImGuiID, int, float, ImGuiID* out_at_dir, ImGuiID* out_opposite)
{
    if (out_at_dir)
        *out_at_dir = 0;
    if (out_opposite)
        *out_opposite = 0;
    return 0;
}
IMGUI_API bool IsItemIDActive(ImGuiID) { return false; }
IMGUI_API void SetItemAllowOverlap() {}
IMGUI_API void CalcListClipping(int, float, int* out_start, int* out_end)
{
    if (out_start)
        *out_start = 0;
    if (out_end)
        *out_end = 0;
}
IMGUI_API int GetKeyIndex(int key) { return key; }
IMGUI_API bool IsKeyDown(int) { return false; }
IMGUI_API bool IsKeyPressed(int, bool) { return false; }
IMGUI_API bool IsKeyReleased(int) { return false; }
IMGUI_API int GetKeyPressedAmount(int, float, float) { return 0; }
IMGUI_API int GetMergedKeyModFlags() { return 0; }
IMGUI_API void CaptureKeyboardFromApp(bool) {}
IMGUI_API void CaptureMouseFromApp(bool) {}
#if defined(_WIN32)
// MSVC names also encode the return type, which changed for these three.
IMGUI_API void BeginTooltip() {}
IMGUI_API void DockSpace(ImGuiID, const ImVec2&, int, const ImGuiWindowClass*) {}
IMGUI_API bool OpenPopupOnItemClick(const char*, int) { return false; }
#endif
} // namespace ImGui
