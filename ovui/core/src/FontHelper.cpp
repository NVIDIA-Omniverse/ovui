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

#include "platform/PlatformRegistry.h"
#include "platform/IUiFileIO.h"
#include "platform/CachedSetting.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Font.h>
#include <omni/ui/FontAtlasTexture.h>
#include <omni/ui/FontHelper.h>
#include <omni/ui/IGlyphManager.h>
#include <omni/ui/Profile.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/Widget.h>

constexpr char kFontFileSettingsPath[] = "/app/font/file";
constexpr char kFontOverresolutionSettingsPath[] = "/app/font/overresolutionSize";
constexpr float kOverresolutionDefaultFontSize = 100.f;


OMNIUI_NAMESPACE_OPEN_SCOPE

/// Local string cache that tracks a setting path and resolves path aliases.
class _LocalStringCache
{
public:
    _LocalStringCache() = default;

    ~_LocalStringCache()
    {
        stopTracking();
    }

    void startTracking(const char* settingPath)
    {
        auto* settings = PlatformRegistry::instance().settings();
        if (!settings)
            return;

        m_settingPath = settingPath;

        // Get initial value and resolve path aliases
        std::string raw = settings->getString(settingPath, "");
        auto* fileIO = PlatformRegistry::instance().fileIO();
        m_value = raw.empty() ? std::string() : (fileIO ? fileIO->resolvePath(raw.c_str()) : raw);

        // Subscribe to changes
        m_subId = settings->subscribe(settingPath, [this](const char*) {
            auto* s = PlatformRegistry::instance().settings();
            if (!s)
                return;
            std::string raw = s->getString(m_settingPath.c_str(), "");
            auto* fio = PlatformRegistry::instance().fileIO();
            m_value = raw.empty() ? std::string() : (fio ? fio->resolvePath(raw.c_str()) : raw);
        });
    }

    void stopTracking()
    {
        if (m_subId != 0)
        {
            auto* s = PlatformRegistry::instance().settings();
            if (s)
                s->unsubscribe(m_subId);
            m_subId = 0;
        }
    }

    operator bool() const
    {
        return m_subId != 0;
    }

    const std::string& get()
    {
        return m_value;
    }

private:
    std::string m_value;
    std::string m_settingPath;
    SettingsSubscriptionId m_subId = 0;
};

struct _LocalOverresolutionSizeCache
{
    _LocalOverresolutionSizeCache()
    {
        auto* settings = PlatformRegistry::instance().settings();
        if (settings)
        {
            settings->setDefaultFloat(kFontOverresolutionSettingsPath, kOverresolutionDefaultFontSize);
            overresolution = settings->getFloat(kFontOverresolutionSettingsPath, kOverresolutionDefaultFontSize);
        }
    }

    float overresolution = kOverresolutionDefaultFontSize;
};

struct FontHelperPrivate
{
    // The pointer to the font that is used by this helper
    void* m_font = nullptr;
    // The final size that contains the scale factor and the size from style
    float m_scaledSize = 14.0f;
    // The size if the atlas
    float m_atlasSize = 0.0f;
    // Font size multiplier. We need it to be able to restore the underlying
    // system when we finish drawing.
    float m_fontScale = 1.0f;

    std::shared_ptr<FontAtlasTexture> m_atlas;

    _LocalStringCache m_fontFileCache;
};

FontHelper::FontHelper() : m_prv{ std::make_unique<FontHelperPrivate>() }
{
}

FontHelper::~FontHelper() = default;

void FontHelper::_pushFont(const Widget& widget, bool overresolution)
{
    this->_updateFont(widget, overresolution);

    // Check CurrentWindow because when changing the size outside the drawing
    // loop it could crash.
    if (m_prv->m_font && ImGui::GetCurrentContext()->CurrentWindow)
    {
        auto font = reinterpret_cast<ImFont*>(m_prv->m_font);
        ImGui::PushFont(font, font->LegacySize * m_prv->m_fontScale);
    }
}

void FontHelper::_pushFont(float fontSize)
{
    this->_updateFont(fontSize, 1.0f, true);

    if (m_prv->m_font)
    {
        auto font = reinterpret_cast<ImFont*>(m_prv->m_font);
        ImGui::PushFont(font, font->LegacySize * m_prv->m_fontScale);
    }
}

void FontHelper::_popFont() const
{
    if (m_prv->m_font && ImGui::GetCurrentContext()->CurrentWindow)
    {
        ImGui::PopFont();
    }
}

void FontHelper::_updateFont(const Widget& widget, bool overresolution)
{
    float fontStyleSize = 14.0f;
    bool hasFontSizeStyle = widget._resolveStyleProperty(StyleFloatProperty::eFontSize, &fontStyleSize);
    float scale = widget._getScale();

    const char* font = nullptr;
    widget._resolveStyleProperty(StyleStringProperty::eFont, &font);
    if (!font && overresolution)
    {
        if (!m_prv->m_fontFileCache)
        {
            m_prv->m_fontFileCache.startTracking(kFontFileSettingsPath);
        }

        font = m_prv->m_fontFileCache.get().c_str();
    }
    if (font)
    {
        // Because when there is no font, all the fonts are pre-scaled for DPI.
        fontStyleSize *= widget.getDpiScale();
    }

    float fontSize = std::max(1e-3f, fontStyleSize * scale);
    this->_updateFont(font, fontSize, scale, hasFontSizeStyle, overresolution);
}

void FontHelper::_updateFont(float fontSize, float scale, bool hasFontSizeStyle)
{
    this->_updateFont(nullptr, fontSize, scale, hasFontSizeStyle);
}

void FontHelper::_updateFont(const char* font, float fontSize, float scale, bool hasFontSizeStyle, bool overresolution)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    static _LocalOverresolutionSizeCache getOverresolutionSizeOnce;

    if (font)
    {
        // The size to request
        float sizeToRequest = overresolution ? getOverresolutionSizeOnce.overresolution : fontSize;

        // if the current font is not the same as the passed one
        if (!m_prv->m_atlas || !m_prv->m_atlas->isA(font, sizeToRequest))
        {
            // get the atlas from the registry. if it's overresolution, use mipmapping.
            m_prv->m_atlas = FontAtlasTextureRegistry::instance().getAtlas(font, sizeToRequest, overresolution);
        }
    }
    else
    {
        if (m_prv->m_atlas)
        {
            m_prv->m_atlas.reset();
        }
    }

    if (m_prv->m_atlas)
    {
        m_prv->m_font = m_prv->m_atlas->getFont();

        if (overresolution)
        {
            // sets the scaled size and atlas size to getOverresolutionSizeOnce.overresolution
            m_prv->m_scaledSize = fontSize;
            m_prv->m_atlasSize = getOverresolutionSizeOnce.overresolution;
            m_prv->m_fontScale = m_prv->m_scaledSize / m_prv->m_atlasSize;
        }
        else
        {
            // sets the scaled size and atlas size to fontSize
            m_prv->m_scaledSize = fontSize;
            m_prv->m_atlasSize = fontSize;
            m_prv->m_fontScale = 1.0f;
        }

        return;
    }

    if (fontSize == m_prv->m_scaledSize)
    {
        return;
    }
    m_prv->m_scaledSize = fontSize;

    bool is_scaled = scale != 1.0f;

    if (hasFontSizeStyle || is_scaled)
    {
        // Carbonite supports three sizes of the font.
        // TODO: We need own font generator
        // TODO: It's the only style property that should ignore HiDPI, all others should be premultiplied to HiDPI
        // except this one.
        ui::FontStyle font;
        float atlasFontSize;
        if (fontSize <= 7.0f)
        {
            font = ui::FontStyle::eXXXS;
            atlasFontSize = 6.0f;
        }
        else if (fontSize <= 9.0f)
        {
            font = ui::FontStyle::eXXS;
            atlasFontSize = 8.0f;
        }
        else if (fontSize <= 11.0f)
        {
            font = ui::FontStyle::eExtraSmall;
            atlasFontSize = 10.0f;
        }
        else if (fontSize <= 13.0f)
        {
            font = ui::FontStyle::eSmall;
            atlasFontSize = 12.0f;
        }
        else if (fontSize <= 15.0f)
        {
            font = ui::FontStyle::eNormal;
            atlasFontSize = 14.0f;
        }
        else if (fontSize <= 17.0f)
        {
            font = ui::FontStyle::eLarge;
            atlasFontSize = 16.0f;
        }
        else if (fontSize <= 19.0f)
        {
            font = ui::FontStyle::eExtraLarge;
            atlasFontSize = 18.0f;
        }
        else if (fontSize <= 21.0f)
        {
            font = ui::FontStyle::eXXL;
            atlasFontSize = 20.0f;
        }
        else if (fontSize <= 23.0f)
        {
            font = ui::FontStyle::eXXXL;
            atlasFontSize = 22.0f;
        }
        else
        {
            font = ui::FontStyle::eUltra;
            atlasFontSize = getOverresolutionSizeOnce.overresolution;
        }

        if (m_prv->m_atlasSize != atlasFontSize)
        {
            auto* glyphmanager = PlatformRegistry::instance().glyphManager();
            m_prv->m_font = nullptr;
            if (glyphmanager)
            {
                m_prv->m_font = glyphmanager->getFont(font);
            }

            m_prv->m_atlasSize = atlasFontSize;
        }

       m_prv-> m_fontScale = m_prv->m_scaledSize / m_prv->m_atlasSize;
    }
    else
    {
        m_prv->m_font = nullptr;
        m_prv->m_fontScale = 1.0f;
        m_prv->m_atlasSize = 0.0f;
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
