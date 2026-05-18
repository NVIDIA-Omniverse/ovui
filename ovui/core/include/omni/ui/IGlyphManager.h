/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Font.h>

namespace omni
{
namespace ui
{

struct GlyphInfo
{
    const char* code;
    float scale;
};

constexpr char kFontFileSettingsPath[] = "/app/font/file";
constexpr char kFontSizeSettingsPath[] = "/app/font/size";
constexpr char kFontScaleSettingsPath[] = "/app/font/scale";
constexpr char kResourceConfigFileSettingsPath[] = "/app/resourceConfig";
constexpr char kFontSaveAtlasSettingsPath[] = "/app/font/saveAtlas";
constexpr char kFontCustomRegionFilesSettingsPath[] = "/app/font/customRegionFiles";
constexpr char kFontCustomFontPathSettingsPath[] = "/app/font/customFontPath";

struct FontAtlas;

/**
 * Defines a interface managing custom glyphs for the UI system.
 */
class IGlyphManager
{
public:
    virtual ~IGlyphManager(){};

    virtual void setFontPath(const char* fontPath) = 0;
    virtual void setFontSize(float fontSize) = 0;
    virtual void setFontScale(float fontScale) = 0;
    virtual void setResourcesConfigPath(const char* resourcesConfigPath) = 0;

    virtual FontAtlas* createFontAtlas() = 0;
    virtual void destroyFontAtlas(FontAtlas* fontAtlas) = 0;
    virtual void* getContextFontAtlas(FontAtlas* fontAtlas) = 0;
    /**
     * Rebuilds fonts. If fontAtlas is nullptr, will create internal font atlas - deprecated approach.
     */
    virtual void rebuildFonts(FontAtlas* fontAtlas) = 0;

    /**
     * Associates a registered glyph such as a SVG or PNG
     *
     * @param glyphPath The glyph resource path. Ex ${glyphs}/folder-solid.svg
     */
    virtual bool registerGlyph(const char* glyphPath, FontStyle style) = 0;

    /**
     * Retrieves glyph Unicode character code for a registered glyph resource.
     *
     * @param glyphPath The glyph resource path. Ex ${glyphs}/folder-solid.svg
     * @return The glyph information
     */
    virtual GlyphInfo getGlyphInfo(const char* glyphPath, FontStyle style = FontStyle::eNormal) const = 0;

    virtual void* getFont(FontStyle style) = 0;
};
}
}
