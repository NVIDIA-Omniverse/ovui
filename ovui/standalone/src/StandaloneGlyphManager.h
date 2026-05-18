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

#pragma once

#include <omni/ui/IGlyphManager.h>
#include <string>
#include <unordered_map>

namespace omni {
namespace ui {
namespace standalone {

/**
 * Minimal IGlyphManager for the standalone backend.
 *
 * Loads the body typeface (or a fallback) at all standard FontStyle sizes into
 * ImGui's font atlas so that omni.ui widgets can render any font_size
 * using the real typeface rather than ImGui's built-in bitmap font.
 *
 * Call loadFonts() BEFORE ImGui_ImplOpenGL3_NewFrame() (i.e. during window
 * creation), then register this instance with PlatformRegistry.
 */
class StandaloneGlyphManager : public IGlyphManager
{
public:
    StandaloneGlyphManager() = default;
    ~StandaloneGlyphManager() override = default;

    /**
     * Load the TTF at every standard size.  Must be called before the first
     * ImGui render frame so the atlas can be built.
     *
     * @param fontPath  Absolute path to the .ttf file.
     * @param dpiScale  Content scale factor (1.0 on macOS logical-pixel path).
     * @return true if at least one size was loaded successfully.
     */
    bool loadFonts(const std::string& fontPath, float dpiScale);

    // ── IGlyphManager ────────────────────────────────────────────────────────
    void* getFont(FontStyle style) override;

    // The remaining methods are Kit-only plumbing; stub them out.
    void  setFontPath(const char*) override {}
    void  setFontSize(float) override {}
    void  setFontScale(float) override {}
    void  setResourcesConfigPath(const char*) override {}

    FontAtlas* createFontAtlas() override { return nullptr; }
    void       destroyFontAtlas(FontAtlas*) override {}
    void*      getContextFontAtlas(FontAtlas*) override { return nullptr; }
    void       rebuildFonts(FontAtlas*) override {}

    bool      registerGlyph(const char*, FontStyle) override { return false; }
    GlyphInfo getGlyphInfo(const char*, FontStyle) const override { return {}; }

private:
    // FontStyle enum value → ImFont* (owned by ImGui's atlas, not by us)
    std::unordered_map<int, void*> m_fonts;
};

} // namespace standalone
} // namespace ui
} // namespace omni
