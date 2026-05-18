/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "Api.h"

#include <memory>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class _FontAtlasTexture;
class _FontAtlasTextureRegistry;

/**
 * @brief A single font. It has a texture with all the letters and a table with
 * data for every character.
 */
class FontAtlasTexture
{
public:
    ~FontAtlasTexture();

    /**
     * @brief Get the pointer to the underlying system font object.
     */
    OMNIUI_API
    void* getFont() const;

    /**
     * @brief GPU reference to the buffer with the font texture.
     */
    OMNIUI_API
    void* getTextureId() const;

    /**
     * @brief True if it's the font with the given path and size.
     */
    OMNIUI_API
    bool isA(const char* fontName, float size) const;

private:
    friend class FontAtlasTextureRegistry;

    FontAtlasTexture(const char* fontPath, const char* fontName, float fontSize, bool mipMaps, bool extendedGlyphs);

    // To avoid including ImGui libs
    std::unique_ptr<_FontAtlasTexture> m_prv;
};

/**
 * @brief Registry for the fonts. It's the object that creates fonts. It stores
 * weak pointers so if the font is not used, it destroyes.
 *
 * TODO: Languages
 */
class FontAtlasTextureRegistry
{
public:
    OMNIUI_API
    static FontAtlasTextureRegistry& instance();

    // Singleton
    FontAtlasTextureRegistry(FontAtlasTextureRegistry const&) = delete;
    void operator=(FontAtlasTextureRegistry const&) = delete;

    /**
     * @brief Retrieves the FontAtlasTexture associated with the specified font
     * path and size.
     *
     * @param fontName - The path to the font file.
     * @param fontSize - The desired size of the font.
     * @param mipMaps - An optional parameter indicating whether to generate
     * mipmaps for the font atlas texture. Defaults to false.
     *
     * @return std::shared_ptr<FontAtlasTexture> - A shared pointer to the
     * FontAtlasTexture object associated with the specified font and size.
     */
    OMNIUI_API
    std::shared_ptr<FontAtlasTexture> getAtlas(const char* fontName, float fontSize, bool mipMaps = false, bool extendedGlyphs = false);

private:
    friend class Inspector;

    FontAtlasTextureRegistry();

    /**
     * @brief Returns all the fonts in the cache. We need it for tests.
     */
    std::vector<std::pair<std::string, uint32_t>> _getStoredFonts() const;

    /**
     * @brief Create a new atlas.
     */
    std::shared_ptr<FontAtlasTexture> _createAtlas(const char* font, float roundFontSize, bool mipMaps, bool extendedGlyphs);

    std::unique_ptr<_FontAtlasTextureRegistry> m_prv;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
