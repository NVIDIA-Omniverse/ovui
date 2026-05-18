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

// Style-cascade -> RenderConfig resolver.  Factored out of
// MarkdownWidget::_drawContent so results can be cached across frames.
//
#include "MarkdownStyleResolver.h"

#include <omni/ui/FontAtlasTexture.h>
#include <omni/ui/platform/IUiFileIO.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <imgui/imgui.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

std::string makeFingerprint(const std::vector<std::string>& candidates, float size)
{
    std::string fp;
    for (const std::string& c : candidates)
    {
        fp.append(c);
        fp.push_back('\x1F');
    }
    fp.append(std::to_string(static_cast<int>(size * 1000.0f)));
    return fp;
}

std::string probeFirstExistingPath(const std::vector<std::string>& candidates)
{
    auto* fileIO = PlatformRegistry::instance().fileIO();
    for (const std::string& candidate : candidates)
    {
        if (candidate.empty())
            continue;
        if (fileIO)
        {
            std::string resolved = fileIO->resolvePath(candidate.c_str());
            if (fileIO->fileExists(resolved.c_str()))
                return resolved;
        }
        else if (std::filesystem::exists(candidate))
        {
            return candidate;
        }
    }
    return {};
}

void scaleRenderConfig(RenderConfig& config, float scale)
{
    if (scale <= 0.0f || std::abs(scale - 1.0f) < 0.001f)
        return;

    config.bodyFontSize *= scale;
    config.codeFontSize *= scale;
    for (float& headingSize : config.headingSizes)
        headingSize *= scale;

    config.paragraphSpacing *= scale;
    config.headingSpacingBefore *= scale;
    config.headingSpacingAfter *= scale;
    config.listIndent *= scale;
    config.bulletGap *= scale;
    config.quoteBarWidth *= scale;
    config.quoteBarPadding *= scale;
    config.quoteIndent *= scale;
    config.codeBlockPadding *= scale;
    config.codeBlockBorderRadius *= scale;
    config.codeBorderRadius *= scale;
    config.hrThickness *= scale;
    config.hrSpacing *= scale;
    config.tablePadding *= scale;
    config.tableRowSpacing *= scale;
    config.tableMinColumnWidth *= scale;
    config.tableMaxColumnWidth *= scale;
    config.tableFixedColumnWidth *= scale;
    config.imageDefaultWidth *= scale;
    config.imageDefaultHeight *= scale;
}

} // namespace

void buildRenderConfig(const StyleAccessors& accessors, MarkdownStyleCache& cache, RenderConfig& config)
{
    config = RenderConfig{};

    uint32_t color, secondaryColor, secondarySelectedColor, secondaryBgColor, borderColor;
    float fontSize = config.bodyFontSize;

    if (accessors.resolveFloat(StyleFloatProperty::eFontSize, &fontSize))
    {
        float scale = fontSize / config.bodyFontSize;
        config.bodyFontSize = fontSize;
        config.codeFontSize = std::max(1.0f, fontSize - 1.0f);
        for (float& headingSize : config.headingSizes)
            headingSize *= scale;
    }

    if (accessors.resolveColor(StyleColorProperty::eColor, &color))
        config.textColor = color;

    if (accessors.resolveColor(StyleColorProperty::eSecondaryColor, &secondaryColor))
        config.headingColor = secondaryColor;
    else
        config.headingColor = brighten(config.textColor, 1.2f);

    if (accessors.resolveColor(StyleColorProperty::eSecondarySelectedColor, &secondarySelectedColor))
        config.linkColor = secondarySelectedColor;

    if (accessors.resolveColor(StyleColorProperty::eSecondaryBackgroundColor, &secondaryBgColor))
    {
        config.codeBgColor = secondaryBgColor;
        config.codeBlockBgColor = brighten(secondaryBgColor, 0.8f);
        config.quoteBgColor = withAlpha(secondaryBgColor, 80);
        config.tableHeaderBg = secondaryBgColor;
        config.tableRowAltBg = withAlpha(secondaryBgColor, 128);
        config.imagePlaceholderBgColor = secondaryBgColor;
    }

    if (accessors.resolveColor(StyleColorProperty::eBorderColor, &borderColor))
    {
        config.codeBlockBorderColor = borderColor;
        config.hrColor = borderColor;
        config.tableBorderColor = borderColor;
    }

    config.linkHoverColor = brighten(config.linkColor, 1.3f);
    config.headingAnchorColor = withAlpha(config.linkColor, 190);
    config.italicColor = warmShift(config.textColor);
    config.codeTextColor = warmShift(config.textColor);
    config.quoteBarColor = config.headingColor;
    config.quoteTextColor = withAlpha(config.textColor, 200);
    config.codeLangChipColor = withAlpha(config.textColor, 160);
    config.tableTextColor = config.textColor;
    config.tableHeaderTextColor = config.headingColor;
    config.codeBlockCopyColor = config.textColor;
    config.codeBlockCopyBgColor = brighten(config.codeBlockBgColor, 1.4f);
    config.codeBlockCopyBorderColor = config.codeBlockBorderColor;
    config.codeKeywordColor = config.linkColor;
    config.codeStringColor = warmShift(config.textColor);
    config.codeCommentColor = withAlpha(config.textColor, 150);
    config.codeNumberColor = brighten(config.linkColor, 1.15f);
    config.codePunctuationColor = withAlpha(config.textColor, 220);
    for (ImU32& alertTextColor : config.alertTextColors)
        alertTextColor = config.textColor;

    auto resolveGroupColor = [&](const char* group, StyleColorProperty prop, ImU32& target) {
        uint32_t v = target;
        if (accessors.resolveGroupColor(group, prop, &v))
            target = v;
    };
    auto resolveGroupFloat = [&](const char* group, StyleFloatProperty prop, float& target) {
        float v = target;
        if (accessors.resolveGroupFloat(group, prop, &v))
            target = v;
    };

    resolveGroupColor("MarkdownWidget.Link", StyleColorProperty::eColor, config.linkColor);
    resolveGroupColor("MarkdownWidget.Link", StyleColorProperty::eSelectedColor, config.linkHoverColor);
    resolveGroupColor("MarkdownWidget.Link", StyleColorProperty::eSecondarySelectedColor, config.linkHoverColor);
    resolveGroupColor("MarkdownWidget.HeadingAnchor", StyleColorProperty::eColor, config.headingAnchorColor);
    resolveGroupColor("MarkdownWidget.Emphasis", StyleColorProperty::eColor, config.italicColor);
    resolveGroupColor("MarkdownWidget.Code", StyleColorProperty::eColor, config.codeTextColor);
    resolveGroupColor("MarkdownWidget.Code", StyleColorProperty::eBackgroundColor, config.codeBgColor);
    resolveGroupFloat("MarkdownWidget.Code", StyleFloatProperty::eBorderRadius, config.codeBorderRadius);
    resolveGroupColor("MarkdownWidget.CodeBlock", StyleColorProperty::eColor, config.codeTextColor);
    resolveGroupColor("MarkdownWidget.CodeBlock", StyleColorProperty::eBackgroundColor, config.codeBlockBgColor);
    resolveGroupColor("MarkdownWidget.CodeBlock", StyleColorProperty::eBorderColor, config.codeBlockBorderColor);
    resolveGroupColor("MarkdownWidget.CodeBlock", StyleColorProperty::eSecondaryColor, config.codeLangChipColor);
    resolveGroupFloat("MarkdownWidget.CodeBlock", StyleFloatProperty::ePadding, config.codeBlockPadding);
    resolveGroupFloat("MarkdownWidget.CodeBlock", StyleFloatProperty::eBorderRadius, config.codeBlockBorderRadius);
    resolveGroupColor("MarkdownWidget.CodeBlock.Keyword", StyleColorProperty::eColor, config.codeKeywordColor);
    resolveGroupColor("MarkdownWidget.CodeBlock.String", StyleColorProperty::eColor, config.codeStringColor);
    resolveGroupColor("MarkdownWidget.CodeBlock.Comment", StyleColorProperty::eColor, config.codeCommentColor);
    resolveGroupColor("MarkdownWidget.CodeBlock.Number", StyleColorProperty::eColor, config.codeNumberColor);
    resolveGroupColor("MarkdownWidget.CodeBlock.Punctuation", StyleColorProperty::eColor, config.codePunctuationColor);
    resolveGroupColor("MarkdownWidget.CodeBlock.CopyButton", StyleColorProperty::eColor, config.codeBlockCopyColor);
    resolveGroupColor("MarkdownWidget.CodeBlock.CopyButton", StyleColorProperty::eBackgroundColor, config.codeBlockCopyBgColor);
    resolveGroupColor("MarkdownWidget.CodeBlock.CopyButton", StyleColorProperty::eBorderColor, config.codeBlockCopyBorderColor);
    resolveGroupColor("MarkdownWidget.Quote", StyleColorProperty::eColor, config.quoteTextColor);
    resolveGroupColor("MarkdownWidget.Quote", StyleColorProperty::eBackgroundColor, config.quoteBgColor);
    resolveGroupColor("MarkdownWidget.Quote", StyleColorProperty::eSecondaryColor, config.quoteBarColor);
    resolveGroupFloat("MarkdownWidget.Quote", StyleFloatProperty::eBorderWidth, config.quoteBarWidth);
    resolveGroupFloat("MarkdownWidget.Quote", StyleFloatProperty::ePadding, config.quoteBarPadding);
    for (int i = 0; i < 5; ++i)
    {
        resolveGroupColor("MarkdownWidget.Alert", StyleColorProperty::eColor, config.alertTextColors[i]);
        resolveGroupColor("MarkdownWidget.Alert", StyleColorProperty::eBackgroundColor, config.alertBgColors[i]);
        resolveGroupColor("MarkdownWidget.Alert", StyleColorProperty::eSecondaryColor, config.alertBarColors[i]);
    }
    static const char* kAlertStyleGroups[5] = {
        "MarkdownWidget.Alert.Note",
        "MarkdownWidget.Alert.Tip",
        "MarkdownWidget.Alert.Important",
        "MarkdownWidget.Alert.Warning",
        "MarkdownWidget.Alert.Caution",
    };
    for (int i = 0; i < 5; ++i)
    {
        resolveGroupColor(kAlertStyleGroups[i], StyleColorProperty::eColor, config.alertTextColors[i]);
        resolveGroupColor(kAlertStyleGroups[i], StyleColorProperty::eBackgroundColor, config.alertBgColors[i]);
        resolveGroupColor(kAlertStyleGroups[i], StyleColorProperty::eSecondaryColor, config.alertBarColors[i]);
    }
    resolveGroupColor("MarkdownWidget.Table", StyleColorProperty::eColor, config.tableTextColor);
    resolveGroupColor("MarkdownWidget.Table", StyleColorProperty::eSecondaryColor, config.tableHeaderTextColor);
    resolveGroupColor("MarkdownWidget.Table", StyleColorProperty::eBackgroundColor, config.tableHeaderBg);
    resolveGroupColor("MarkdownWidget.Table", StyleColorProperty::eSecondaryBackgroundColor, config.tableRowAltBg);
    resolveGroupColor("MarkdownWidget.Table", StyleColorProperty::eBorderColor, config.tableBorderColor);
    resolveGroupFloat("MarkdownWidget.Table", StyleFloatProperty::ePadding, config.tablePadding);
    resolveGroupColor("MarkdownWidget.Image", StyleColorProperty::eColor, config.imageAltColor);
    resolveGroupColor("MarkdownWidget.Image", StyleColorProperty::eBackgroundColor, config.imagePlaceholderBgColor);
    resolveGroupColor("MarkdownWidget.Image", StyleColorProperty::eBorderColor, config.imagePlaceholderBorderColor);
    resolveGroupColor("MarkdownWidget.HRule", StyleColorProperty::eColor, config.hrColor);
    resolveGroupFloat("MarkdownWidget.HRule", StyleFloatProperty::eBorderWidth, config.hrThickness);

    for (int i = 0; i < 6; ++i)
    {
        std::string group = "MarkdownWidget.H" + std::to_string(i + 1);
        resolveGroupColor(group.c_str(), StyleColorProperty::eColor, config.headingColors[i]);
        resolveGroupFloat(group.c_str(), StyleFloatProperty::eFontSize, config.headingSizes[i]);
    }

    // Font push (owned by caller via matching _popFont).
    accessors.pushFont();
    config.bodyFont = ImGui::GetFont();
    float actualBodyFontSize = ImGui::GetFontSize();
    if (config.bodyFontSize > 0.0f && actualBodyFontSize > 0.0f)
        scaleRenderConfig(config, actualBodyFontSize / config.bodyFontSize);

    auto parseTablePolicy = [](const char* policy) {
        if (!policy)
            return MarkdownTableLayoutPolicy::Equal;
        std::string value(policy);
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        if (value == "content-fit" || value == "content_fit" || value == "fit")
            return MarkdownTableLayoutPolicy::ContentFit;
        if (value == "fixed")
            return MarkdownTableLayoutPolicy::Fixed;
        if (value == "clipped" || value == "clip" || value == "scroll")
            return MarkdownTableLayoutPolicy::Clipped;
        return MarkdownTableLayoutPolicy::Equal;
    };
    const char* tablePolicy = nullptr;
    if (accessors.resolveGroupString("MarkdownWidget.Table", StyleStringProperty::eLayoutPolicy, &tablePolicy))
        config.tableLayoutPolicy = parseTablePolicy(tablePolicy);

    auto loadFontFace = [&](const std::string& key,
                            const std::vector<std::string>& candidates,
                            float size,
                            bool extendedGlyphs = true) -> ImFont* {
        auto& entry = cache.fontFaces[key];
        std::string fp = makeFingerprint(candidates, size);
        if (!entry.probed || entry.fingerprint != fp)
        {
            entry.fingerprint = fp;
            entry.path = probeFirstExistingPath(candidates);
            entry.probed = true;
            entry.size = size;
            entry.atlas.reset();
        }
        if (entry.path.empty())
            return nullptr;
        if (!entry.atlas || entry.size != size)
        {
            entry.size = size;
            entry.atlas = FontAtlasTextureRegistry::instance().getAtlas(entry.path.c_str(), size, false, extendedGlyphs);
        }
        return entry.atlas ? reinterpret_cast<ImFont*>(entry.atlas->getFont()) : nullptr;
    };

    const char* boldFont = nullptr;
    const char* italicFont = nullptr;
    const char* codeFont = nullptr;
    const char* fallbackFont = nullptr;
    std::array<const char*, 6> headingFonts{};
    accessors.resolveGroupString("MarkdownWidget.Strong", StyleStringProperty::eFont, &boldFont);
    accessors.resolveGroupString("MarkdownWidget.Emphasis", StyleStringProperty::eFont, &italicFont);
    accessors.resolveGroupString("MarkdownWidget.Code", StyleStringProperty::eFont, &codeFont);
    accessors.resolveGroupString("MarkdownWidget.Fallback", StyleStringProperty::eFont, &fallbackFont);
    for (int i = 0; i < 6; ++i)
    {
        std::string group = "MarkdownWidget.H" + std::to_string(i + 1);
        accessors.resolveGroupString(group.c_str(), StyleStringProperty::eFont, &headingFonts[i]);
    }

    config.boldFont = loadFontFace("bold",
        { boldFont ? boldFont : "", "${fonts}/NotoSans-Bold.ttf" },
        config.bodyFontSize);
    for (int i = 0; i < 6; ++i)
    {
        config.headingFonts[i] = loadFontFace("heading" + std::to_string(i + 1),
            { headingFonts[i] ? headingFonts[i] : "",
              boldFont ? boldFont : "",
              "${fonts}/NotoSans-Bold.ttf" },
            config.headingSizes[i]);
    }
    config.italicFont = loadFontFace("italic",
        { italicFont ? italicFont : "", "${fonts}/NotoSans-Italic.ttf", "${fonts}/NotoSans-MediumItalic.ttf" },
        config.bodyFontSize);
    config.codeFont = loadFontFace("code",
        { codeFont ? codeFont : "", "${fonts}/JetBrainsMono-Regular.ttf" },
        config.codeFontSize);
    config.fallbackFont = loadFontFace("fallback",
        { fallbackFont ? fallbackFont : "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" },
        config.bodyFontSize,
        true);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
