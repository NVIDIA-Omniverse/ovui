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

#include "platform/Log.h"
#include "platform/PlatformRegistry.h"
#include "platform/IUiFileIO.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <imgui/misc/freetype/imgui_freetype.h>
#include <omni/ui/FontAtlasTexture.h>
#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/Profile.h>

#include <unordered_map>

OMNIUI_NAMESPACE_OPEN_SCOPE

// We keep the size for each 0.25. It means if the user sets 10.3, it will be
// rounded to 10.25.
static constexpr float kFontSizePrecision = 1.0f / 4.0f;

static inline uint32_t _getLookupSize(float size)
{
    return static_cast<uint32_t>(floorf(size / kFontSizePrecision));
}

static const ImWchar* _extendedGlyphRanges()
{
    static const ImWchar ranges[] = {
        0x0020, 0x00FF, // Basic Latin + Latin-1
        0x0100, 0x024F, // Latin Extended-A/B
        0x0370, 0x03FF, // Greek and Coptic
        0x0400, 0x052F, // Cyrillic + supplement
        0x2000, 0x206F, // General punctuation
        0x2070, 0x209F, // Superscripts/subscripts
        0x20A0, 0x20CF, // Currency symbols
        0x2100, 0x214F, // Letterlike symbols
        0x2150, 0x218F, // Number forms
        0x2190, 0x21FF, // Arrows
        0x2200, 0x22FF, // Mathematical operators
        0x2300, 0x23FF, // Misc technical
        0x25A0, 0x25FF, // Geometric shapes
        0x2600, 0x27BF, // Misc symbols + dingbats
        0xFFFD, 0xFFFD, // Replacement character
        0,
    };
    return ranges;
}

template <class T>
inline void hash_combine(std::size_t& seed, const T& v)
{
    std::hash<T> hasher;
    seed ^= hasher(v) + 0x9e3779b9 + (seed<<6) + (seed>>2);
}

class _FontAtlasTexture
{
private:
    friend class FontAtlasTexture;

    ImFontAtlas m_imGuiAtlas;
    ByteImageProvider m_image;

    const char* m_font;
    float m_fontSize;
    uint32_t m_lookupFontSize;
};

FontAtlasTexture::FontAtlasTexture(const char* fontPath, const char* fontName, float fontSize, bool mipMaps, bool extendedGlyphs)
    : m_prv{ std::make_unique<_FontAtlasTexture>() }
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    m_prv->m_font = fontName;
    m_prv->m_fontSize = fontSize;
    m_prv->m_lookupFontSize = _getLookupSize(fontSize);

    // Force the FreeType loader. Kit's ImGui is built with
    // IMGUI_ENABLE_FREETYPE so this is redundant in Kit, but the standalone
    // build does not set IMGUI_ENABLE_FREETYPE and the 1.92 default loader
    // there is stb_truetype. The pre-1.92 code path used
    // ImGuiFreeType::BuildFontAtlas unconditionally, so selecting FreeType
    // explicitly keeps the two backends rasterizing glyphs with the same
    // engine as the golden reference images.
    m_prv->m_imGuiAtlas.SetFontLoader(ImGuiFreeType::GetFontLoader());

    // ImGui 1.92 loads glyphs dynamically, so the legacy glyph-range argument
    // was dropped from AddFontFromFileTTF. The `extendedGlyphs` flag survives
    // in the registry hash key (below) so callers still get distinct atlases
    // when they want extended-Latin/arrow/Greek coverage, even if the backend
    // now pulls those glyphs on demand.
    (void)extendedGlyphs;
    ImFont* loadedFont = m_prv->m_imGuiAtlas.AddFontFromFileTTF(fontPath, fontSize);
    if (loadedFont)
    {
        // Lock baked sizes so ImGui::PushFont(font, other_size) returns the
        // closest match (our preloaded size) rather than dynamically baking
        // glyphs at the requested size. Dynamic baking would regenerate the
        // atlas pixel data after we've already uploaded it to the GPU, leaving
        // the GPU texture stale — glyph UVs would reference the rebuilt atlas
        // while the GPU still holds the original. Used by the overresolution
        // path where a single high-res atlas is scaled to serve many font
        // sizes (see FontHelper::_pushFont).
        loadedFont->Flags |= ImFontFlags_LockBakedSizes;
    }
    m_prv->m_imGuiAtlas.TexDesiredFormat = ImTextureFormat_RGBA32;
    ImFontAtlasBuildMain(&m_prv->m_imGuiAtlas);

    ImTextureData* texData = m_prv->m_imGuiAtlas.TexData;
    unsigned char* pixels = texData->Pixels;
    int width = texData->Width;
    int height = texData->Height;

    // ImGui 1.92 builds the RGBA32 atlas with (0,0,0,0) in some padding texels
    // (e.g. the 1-pixel border around each packed glyph rect written as 0
    // during the rect-packing clear phase). The pre-1.92 path used
    // GetTexDataAsRGBA32 which emitted IM_COL32(255,255,255,alpha) for every
    // texel — so padding was (255,255,255,0) (premultiplied-white transparent).
    //
    // With the shader `out_col = input.col * texture0.Sample(...)` and the
    // renderer's SrcAlpha/OneMinusSrcAlpha color blend, bilinear sampling near
    // a glyph's left edge in the 1.92 atlas reads the black padding texel and
    // pulls the sampled RGB down to ~0.75 × the intended color. That produces
    // the "dim left-edge AA" pattern the CanvasFrame compatibility goldens
    // flag as a ~0.08 mean error.
    //
    // Restore the pre-1.92 padding by forcing every alpha=0 texel to
    // (255,255,255,0). This is exactly what GetTexDataAsRGBA32 used to do.
    uint32_t* pixels32 = reinterpret_cast<uint32_t*>(pixels);
    const uint32_t kTransparentWhite = IM_COL32(255, 255, 255, 0);
    const uint32_t kAlphaMask = IM_COL32_A_MASK;
    for (int i = 0, n = width * height; i < n; ++i)
        if ((pixels32[i] & kAlphaMask) == 0)
            pixels32[i] = kTransparentWhite;

    // Save the atlas to the texture
    if (mipMaps)
    {
        m_prv->m_image.setMipMappedBytesData(reinterpret_cast<uint8_t*>(pixels),
                                             { static_cast<uint32_t>(width), static_cast<uint32_t>(height) },
                                             kAutoCalculateStride, PixelFormat::eRGBA8_UNORM);
    }
    else
    {
        m_prv->m_image.setBytesData(reinterpret_cast<uint8_t*>(pixels),
                                    { static_cast<uint32_t>(width), static_cast<uint32_t>(height) },
                                    kAutoCalculateStride, PixelFormat::eRGBA8_UNORM);
    }
    m_prv->m_image.prepareDraw(static_cast<float>(width), static_cast<float>(height));

    texData->SetTexID(static_cast<ImTextureID>(reinterpret_cast<intptr_t>(m_prv->m_image.getImGuiReference())));
}

FontAtlasTexture::~FontAtlasTexture()
{
}

void* FontAtlasTexture::getFont() const
{
    return m_prv->m_imGuiAtlas.Fonts.front();
}

void* FontAtlasTexture::getTextureId() const
{
    return reinterpret_cast<void*>(static_cast<intptr_t>(m_prv->m_imGuiAtlas.TexRef.GetTexID()));
}

bool FontAtlasTexture::isA(const char* fontName, float size) const
{
    return fontName == m_prv->m_font && _getLookupSize(size) == m_prv->m_lookupFontSize;
}

class _FontAtlasTextureRegistry
{
private:
    friend class FontAtlasTextureRegistry;

    struct _AtlasKey
    {
        std::string font;
        uint32_t size;
        bool extendedGlyphs;

        bool operator==(const _AtlasKey& other) const
        {
            return font == other.font && size == other.size && extendedGlyphs == other.extendedGlyphs;
        }
    };
    struct _AtlasKeyHash
    {
        std::size_t operator()(const _AtlasKey& k) const
        {
            size_t hash = 0;
            hash_combine(hash, k.font);
            hash_combine(hash, k.size);
            hash_combine(hash, k.extendedGlyphs);
            return hash;
        }
    };
    std::unordered_map<_AtlasKey, std::weak_ptr<FontAtlasTexture>, _AtlasKeyHash> m_atlases;
};

FontAtlasTextureRegistry::FontAtlasTextureRegistry() : m_prv{ std::make_unique<_FontAtlasTextureRegistry>() }
{
}

FontAtlasTextureRegistry& FontAtlasTextureRegistry::instance()
{
    static FontAtlasTextureRegistry instance;
    return instance;
}

std::shared_ptr<FontAtlasTexture> FontAtlasTextureRegistry::getAtlas(const char* font, float fontSize, bool mipMaps, bool extendedGlyphs)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    std::shared_ptr<FontAtlasTexture> result;

    uint32_t lookupFontSize = _getLookupSize(fontSize);
    float roundFontSize = floorf(fontSize / kFontSizePrecision) * kFontSizePrecision;

    // Find/create atlas
    // Emplace operation is designed to avoid copying, not to avoid unnecessary
    // construction of the mapped type.
    // https://exchangetuts.com/1640315883550645
    _FontAtlasTextureRegistry::_AtlasKey key{ font, lookupFontSize, extendedGlyphs };
    auto fontFound = m_prv->m_atlases.find(key);
    if (fontFound != m_prv->m_atlases.end())
    {
        result = fontFound->second.lock();
        if (!result)
        {
            result = this->_createAtlas(font, roundFontSize, mipMaps, extendedGlyphs);
            fontFound->second = result;
        }
    }
    else
    {
        result = this->_createAtlas(font, roundFontSize, mipMaps, extendedGlyphs);
        auto fontEmplaced = m_prv->m_atlases.emplace(
            std::piecewise_construct, std::forward_as_tuple(std::move(key)), std::forward_as_tuple(result));
    }

    return result;
}

std::shared_ptr<FontAtlasTexture> FontAtlasTextureRegistry::_createAtlas(const char* font, float roundFontSize, bool mipMaps, bool extendedGlyphs)
{
    std::shared_ptr<FontAtlasTexture> result;

    auto* fileIO = PlatformRegistry::instance().fileIO();
    std::string fontPath = fileIO ? fileIO->resolvePath(font) : std::string(font);
    if (fileIO && fileIO->fileExists(fontPath.c_str()))
    {
        result =
            std::shared_ptr<FontAtlasTexture>{ new FontAtlasTexture{ fontPath.c_str(), font, roundFontSize, mipMaps, extendedGlyphs } };
    }
    else
    {
        OMNIUI_LOG_WARN_ONCE("Invalid font path: %s", fontPath.c_str());
    }

    return result;
}

std::vector<std::pair<std::string, uint32_t>> FontAtlasTextureRegistry::_getStoredFonts() const
{
    std::vector<std::pair<std::string, uint32_t>> result;

    for (auto&& atlas : m_prv->m_atlases)
    {
        if (atlas.second.lock())
        {
            result.push_back({ atlas.first.font, atlas.first.size });
        }
    }

    return result;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
