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

// Draw-only helpers: block backgrounds, code blocks, tables, images,
// alert glyphs, list markers, thematic breaks.
//
#include "MarkdownPaint.h"
#include "MarkdownText.h"
#include "ImageResolver.h"
#include "MarkdownSyntaxHighlighter.h"
#include "MarkdownTableLayout.h"
#include "TwemojiAtlas.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>

#include <md4c.h>

#include <algorithm>
#include <cctype>
#include <cstring>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

// Case-insensitive ends-with check on two string_views (zero-copy suffix test).
bool endsWithICase(std::string_view s, std::string_view suffix)
{
    if (s.size() < suffix.size())
        return false;
    for (size_t i = 0; i < suffix.size(); ++i)
    {
        char a = s[s.size() - suffix.size() + i];
        char b = suffix[i];
        if (std::tolower(static_cast<unsigned char>(a)) != std::tolower(static_cast<unsigned char>(b)))
            return false;
    }
    return true;
}

bool _isProviderCodeLanguage(const std::string& language, MarkdownAssetKind& kind)
{
    std::string lower(language);
    std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    if (lower == "mermaid")
    {
        kind = MarkdownAssetKind::eDiagramBlock;
        return true;
    }
    if (lower == "math" || lower == "latex" || lower == "tex")
    {
        kind = MarkdownAssetKind::eMathBlock;
        return true;
    }
    return false;
}

const char* _alertLabel(uint8_t alertKind)
{
    switch (alertKind)
    {
    case 1: return "Note";
    case 2: return "Tip";
    case 3: return "Important";
    case 4: return "Warning";
    case 5: return "Caution";
    default: return "";
    }
}

ImU32 _syntaxColorForKind(const RenderConfig& cfg, MarkdownSyntaxKind kind)
{
    switch (kind)
    {
    case MarkdownSyntaxKind::Keyword: return cfg.codeKeywordColor;
    case MarkdownSyntaxKind::String: return cfg.codeStringColor;
    case MarkdownSyntaxKind::Comment: return cfg.codeCommentColor;
    case MarkdownSyntaxKind::Number: return cfg.codeNumberColor;
    case MarkdownSyntaxKind::Punctuation: return cfg.codePunctuationColor;
    default: return cfg.codeTextColor;
    }
}

void _drawCodeSegment(WalkState& state, ImFont* font, float fontSize, ImVec2& pos,
                      ImU32 color, const char* begin, const char* end)
{
    if (!begin || begin >= end)
        return;
    _addTextWithFontTexture(state.drawList, font, fontSize, pos, color, begin, end);
    ImVec2 sz = font->CalcTextSizeA(fontSize, FLT_MAX, 0.0f, begin, end);
    pos.x += sz.x;
}

void _renderHighlightedCodeLine(WalkState& state, ImFont* font, float fontSize,
                                ImVec2 pos, const char* begin, const char* end)
{
    const RenderConfig& cfg = *state.config;
    std::vector<MarkdownSyntaxToken> tokens;
    bool highlighted = false;
    std::string_view language(state.codeBlockLang.data(), state.codeBlockLang.size());
    std::string_view line(begin, static_cast<size_t>(end - begin));

    if (cfg.syntaxHighlighter)
        highlighted = cfg.syntaxHighlighter(language, line, tokens);
    if (!highlighted)
        highlighted = highlightMarkdownCode(language, line, tokens);

    if (!highlighted || tokens.empty())
    {
        _drawCodeSegment(state, font, fontSize, pos, cfg.codeTextColor, begin, end);
        return;
    }

    std::sort(tokens.begin(), tokens.end(), [](const MarkdownSyntaxToken& a, const MarkdownSyntaxToken& b) {
        return a.offset < b.offset;
    });

    size_t cursor = 0;
    size_t len = static_cast<size_t>(end - begin);
    for (const MarkdownSyntaxToken& token : tokens)
    {
        if (token.offset >= len)
            continue;
        size_t tokenBegin = std::max(cursor, token.offset);
        size_t tokenEnd = std::min(len, token.offset + token.length);
        if (tokenEnd <= tokenBegin)
            continue;
        if (cursor < tokenBegin)
            _drawCodeSegment(state, font, fontSize, pos, cfg.codeTextColor, begin + cursor, begin + tokenBegin);
        _drawCodeSegment(state, font, fontSize, pos, _syntaxColorForKind(cfg, token.kind),
                         begin + tokenBegin, begin + tokenEnd);
        cursor = tokenEnd;
    }

    if (cursor < len)
        _drawCodeSegment(state, font, fontSize, pos, cfg.codeTextColor, begin + cursor, end);
}

void _drawCopyIcon(ImDrawList* drawList, const ImVec2& a, const ImVec2& b, ImU32 color)
{
    if (!drawList)
        return;

    const float w = b.x - a.x;
    const float h = b.y - a.y;
    const float size = std::min(w, h);
    const float inset = std::max(4.0f, size * 0.24f);
    const float offset = std::max(3.0f, size * 0.16f);
    const float paperW = size - inset * 2.0f - offset;
    const float paperH = size - inset * 2.0f - offset;
    const ImVec2 frontMin(a.x + inset + offset, a.y + inset);
    const ImVec2 frontMax(frontMin.x + paperW, frontMin.y + paperH);
    const ImVec2 backMin(a.x + inset, a.y + inset + offset);
    const ImVec2 backMax(backMin.x + paperW, backMin.y + paperH);

    drawList->AddRect(backMin, backMax, color, 1.5f, 0, 1.25f);
    drawList->AddRectFilled(frontMin, frontMax, (color & 0x00ffffffu) | 0x18000000u, 1.5f);
    drawList->AddRect(frontMin, frontMax, color, 1.5f, 0, 1.25f);
}

void _drawImagePlaceholder(WalkState& state, ImFont* font, float baseSize)
{
    const RenderConfig& cfg = *state.config;
    const std::string& alt = state.imageAlt.empty() ? state.imageSrc : state.imageAlt;
    const char* lb = alt.data();
    const char* le = lb + alt.size();

    char prefix[8] = "img: ";
    ImVec2 prefSz = font->CalcTextSizeA(baseSize, FLT_MAX, 0.0f, prefix, prefix + 5);
    ImVec2 altSz = font->CalcTextSizeA(baseSize, FLT_MAX, 0.0f, lb, le);
    float w = prefSz.x + altSz.x + 12.0f;
    float h = baseSize + 4.0f;

    float remaining = state.lineXStart + state.availableWidth - state.cursor.x;
    if (w > remaining && state.cursor.x > state.lineXStart + 0.5f)
    {
        state.newLine(state.lineHeight > 0.0f ? state.lineHeight : baseSize);
        state.lineHeight = 0.0f;
    }

    if (state.drawList)
    {
        ImVec2 a(state.cursor.x, state.cursor.y);
        ImVec2 b(a.x + w, a.y + h);
        state.drawList->AddRectFilled(a, b, cfg.imagePlaceholderBgColor, 3.0f);
        state.drawList->AddRect(a, b, cfg.imagePlaceholderBorderColor, 3.0f, 0, 1.0f);
        _addTextWithFontTexture(state.drawList, font, baseSize, ImVec2(a.x + 6.0f, a.y + 2.0f),
                                cfg.imageAltColor, prefix, prefix + 5);
        _addTextWithFontTexture(state.drawList, font, baseSize, ImVec2(a.x + 6.0f + prefSz.x, a.y + 2.0f),
                                cfg.imageAltColor, lb, le);

        // Keyboard-focusable item so the title tooltip is announceable via
        // Tab navigation.  Pure focus + announce -- no click action.
        uint32_t imgSeed = state.imageIdSeed++;
        ImVec2 savedCursor = ImGui::GetCursorScreenPos();
        ImGui::PushID(static_cast<int>(imgSeed));
        ImGui::SetCursorScreenPos(a);
        ImGui::InvisibleButton("##mdimg", ImVec2(w, h), ImGuiButtonFlags_AllowOverlap);
        bool hovered = ImGui::IsItemHovered();
        bool focused = ImGui::IsItemFocused();
        ImGui::PopID();
        ImGui::SetCursorScreenPos(savedCursor);

        const std::string& announce = !state.imageTitle.empty()
                                          ? state.imageTitle
                                          : (!state.imageAlt.empty() ? state.imageAlt : state.imageSrc);
        if ((hovered || focused) && !announce.empty())
            ImGui::SetTooltip("%s", announce.c_str());
        if (focused && !hovered)
        {
            ImU32 ring = ImGui::GetColorU32(ImGuiCol_NavCursor);
            if ((ring & 0xFF000000u) == 0)
                ring = cfg.imagePlaceholderBorderColor;
            _drawFocusRing(state.drawList, a, b, ring);
        }
    }

    state.cursor.x += w;
    state.lineHeight = ImMax(state.lineHeight, h);
}

void _drawResolvedInlineImage(WalkState& state, ImFont* font, float baseSize, const ResolvedImage& img)
{
    float imgW = img.size.x;
    float imgH = img.size.y;

    constexpr float kMinDisplaySize = 16.0f;
    if (imgW > 0 && imgH > 0 && imgW < kMinDisplaySize && imgH < kMinDisplaySize)
    {
        float upscale = kMinDisplaySize / std::max(imgW, imgH);
        imgW *= upscale;
        imgH *= upscale;
    }

    float avail = state.availableWidth;
    float scale = std::min(1.0f, avail / imgW);
    float w = imgW * scale;
    float h = imgH * scale;

    float remaining = state.lineXStart + avail - state.cursor.x;
    if (w > remaining && state.cursor.x > state.lineXStart + 0.5f)
    {
        state.newLine(state.lineHeight > 0.0f ? state.lineHeight : baseSize);
        state.lineHeight = 0.0f;
    }

    if (state.drawList)
    {
        ImVec2 a(state.cursor.x, state.cursor.y);
        ImVec2 b(a.x + w, a.y + h);
        state.drawList->AddImage(img.textureId, a, b, img.uv0, img.uv1);

        // Focusable item: Tab-reachable, emits the tooltip on focus as well
        // as hover.  Intentionally no click action.
        uint32_t imgSeed = state.imageIdSeed++;
        ImVec2 savedCursor = ImGui::GetCursorScreenPos();
        ImGui::PushID(static_cast<int>(imgSeed));
        ImGui::SetCursorScreenPos(a);
        ImGui::InvisibleButton("##mdimg", ImVec2(w, h), ImGuiButtonFlags_AllowOverlap);
        bool hovered = ImGui::IsItemHovered();
        bool focused = ImGui::IsItemFocused();
        ImGui::PopID();
        ImGui::SetCursorScreenPos(savedCursor);

        const std::string& announce = !state.imageTitle.empty()
                                          ? state.imageTitle
                                          : (!state.imageAlt.empty() ? state.imageAlt : state.imageSrc);
        if ((hovered || focused) && !announce.empty())
            ImGui::SetTooltip("%s", announce.c_str());
        if (focused && !hovered)
        {
            ImU32 ring = ImGui::GetColorU32(ImGuiCol_NavCursor);
            if ((ring & 0xFF000000u) == 0)
                ring = state.config->linkHoverColor;
            _drawFocusRing(state.drawList, a, b, ring);
        }
    }

    state.cursor.x += w;
    state.lineHeight = ImMax(state.lineHeight, h);
}

float _layoutInlineRuns(WalkState& state, const std::vector<InlineRun>& runs,
                        ImFont* font, float baseSize, ImU32 textColor,
                        ImVec2 start, float availableWidth, bool forceStrong,
                        ImDrawList* drawList, InteractionState* interaction)
{
    WalkState cellState;
    cellState.config = state.config;
    cellState.availableWidth = std::max(1.0f, availableWidth);
    cellState.drawList = drawList;
    cellState.origin = start;
    cellState.cursor = start;
    cellState.lineXStart = start.x;
    cellState.lineHeight = 0.0f;
    cellState.interaction = interaction;
    cellState.imageResolver = state.imageResolver;
    cellState.emojiAtlas = state.emojiAtlas;
    // Inherit ImGui-ID seeds from the parent so cell-local items do not
    // collide with top-level items.  We write back the advanced counters
    // below so subsequent cells continue from where this one left off.
    cellState.imageIdSeed = state.imageIdSeed;
    cellState.codeBlockIdSeed = state.codeBlockIdSeed;

    if (forceStrong)
        cellState.style.strong++;

    for (const InlineRun& run : runs)
    {
        InlineStyle savedStyle = cellState.style;
        int savedLinkIdx = cellState.activeLinkIdx;
        std::string savedLinkUrl = cellState.activeLinkUrl;
        std::string savedLinkTitle = cellState.activeLinkTitle;

        cellState.style.strong += run.style.strong;
        cellState.style.em += run.style.em;
        cellState.style.code += run.style.code;
        cellState.style.del += run.style.del;

        if (!run.linkUrl.empty())
        {
            cellState.activeLinkUrl = run.linkUrl;
            cellState.activeLinkTitle = run.linkTitle;
            // Reset per-link segment counter so wrapped link segments in
            // table cells get unique suffixes on ImGui's focus graph.
            cellState.linkSegmentIdx = 0;
            if (interaction)
            {
                interaction->linksThisFrame.push_back(run.linkUrl);
                interaction->linkTitlesThisFrame.push_back(run.linkTitle);
                cellState.activeLinkIdx = (int)interaction->linksThisFrame.size() - 1;
            }
            else
            {
                cellState.activeLinkIdx = 0;
            }
        }

        if (run.kind == InlineRun::Kind::Image)
        {
            cellState.imageSrc = run.src;
            cellState.imageAlt = run.alt;
            cellState.imageTitle = run.title;
            _drawInlineImage(cellState, font, baseSize);
        }
        else if (!run.text.empty())
        {
            _renderTextRun(cellState, font, baseSize, textColor,
                           run.text.data(), run.text.data() + run.text.size());
        }

        cellState.style = savedStyle;
        cellState.activeLinkIdx = savedLinkIdx;
        cellState.activeLinkUrl = savedLinkUrl;
        cellState.activeLinkTitle = savedLinkTitle;
    }

    // Propagate ID-seed progress back so sibling cells do not reuse ids.
    state.imageIdSeed = cellState.imageIdSeed;
    state.codeBlockIdSeed = cellState.codeBlockIdSeed;

    return std::max(baseSize, cellState.cursor.y - start.y + std::max(cellState.lineHeight, baseSize));
}

} // namespace

// =====================================================================
// Public helpers (declared in MarkdownPaint.h)
// =====================================================================

void _addTextWithFontTexture(ImDrawList* drawList, ImFont* font, float fontSize,
                             const ImVec2& pos, ImU32 color,
                             const char* begin, const char* end)
{
    if (!drawList || !font || !begin || begin >= end)
        return;

    bool pushedTexture = false;
    if (font->OwnerAtlas)
    {
        drawList->PushTexture(font->OwnerAtlas->TexRef);
        pushedTexture = true;
    }

    drawList->AddText(font, fontSize, pos, color, begin, end);

    if (pushedTexture)
        drawList->PopTexture();
}

void _drawFocusRing(ImDrawList* drawList, ImVec2 a, ImVec2 b, ImU32 color, float thickness)
{
    if (!drawList)
        return;
    constexpr float kOutset = 2.0f;
    // Force alpha to ~220/255 to keep the ring legible but not solid.
    ImU32 ringColor = (color & 0x00FFFFFFu) | (static_cast<ImU32>(220) << IM_COL32_A_SHIFT);
    drawList->AddRect(ImVec2(a.x - kOutset, a.y - kOutset),
                      ImVec2(b.x + kOutset, b.y + kOutset),
                      ringColor, 2.0f, 0, thickness);
}

void _drawAlertGlyph(ImDrawList* drawList, ImVec2 pos, float size, uint8_t alertKind, ImU32 color)
{
    if (!drawList || size <= 0.0f)
        return;

    float thickness = std::max(1.2f, size * 0.10f);
    ImVec2 center(pos.x + size * 0.5f, pos.y + size * 0.5f);
    float r = size * 0.42f;

    auto drawBang = [&]() {
        drawList->AddLine(ImVec2(center.x, pos.y + size * 0.30f),
                          ImVec2(center.x, pos.y + size * 0.58f), color, thickness);
        drawList->AddCircleFilled(ImVec2(center.x, pos.y + size * 0.72f), std::max(1.0f, size * 0.055f), color, 8);
    };

    switch (alertKind)
    {
    case 1:
        drawList->AddCircle(center, r, color, 16, thickness);
        drawList->AddLine(ImVec2(center.x, pos.y + size * 0.42f),
                          ImVec2(center.x, pos.y + size * 0.70f), color, thickness);
        drawList->AddCircleFilled(ImVec2(center.x, pos.y + size * 0.30f), std::max(1.0f, size * 0.055f), color, 8);
        break;
    case 2:
        drawList->AddLine(ImVec2(pos.x + size * 0.22f, pos.y + size * 0.52f),
                          ImVec2(pos.x + size * 0.42f, pos.y + size * 0.72f), color, thickness);
        drawList->AddLine(ImVec2(pos.x + size * 0.42f, pos.y + size * 0.72f),
                          ImVec2(pos.x + size * 0.80f, pos.y + size * 0.28f), color, thickness);
        break;
    case 3:
        drawList->PathLineTo(ImVec2(center.x, pos.y + size * 0.08f));
        drawList->PathLineTo(ImVec2(pos.x + size * 0.92f, center.y));
        drawList->PathLineTo(ImVec2(center.x, pos.y + size * 0.92f));
        drawList->PathLineTo(ImVec2(pos.x + size * 0.08f, center.y));
        drawList->PathStroke(color, ImDrawFlags_Closed, thickness);
        drawBang();
        break;
    case 4:
    case 5:
        drawList->AddTriangle(ImVec2(center.x, pos.y + size * 0.08f),
                              ImVec2(pos.x + size * 0.90f, pos.y + size * 0.88f),
                              ImVec2(pos.x + size * 0.10f, pos.y + size * 0.88f),
                              color, thickness);
        drawBang();
        break;
    default:
        break;
    }
}

void _renderAlertTitle(WalkState& state, ImFont* font, float baseSize, uint8_t alertKind)
{
    int idx = _alertIndex(alertKind);
    const char* label = _alertLabel(alertKind);
    if (idx < 0 || !label || !label[0])
        return;

    InlineStyle savedStyle = state.style;
    state.style.strong++;
    float iconSize = std::max(10.0f, baseSize * 0.86f);
    float iconGap = std::max(4.0f, baseSize * 0.35f);
    if (state.cursor.x + iconSize + iconGap > state.lineXStart + state.availableWidth)
        state.newLine(baseSize);
    if (state.drawList)
    {
        ImVec2 iconPos(state.cursor.x, state.cursor.y + std::max(0.0f, (baseSize - iconSize) * 0.5f));
        _drawAlertGlyph(state.drawList, iconPos, iconSize, alertKind, state.config->alertBarColors[idx]);
    }
    state.cursor.x += iconSize + iconGap;
    state.lineHeight = ImMax(state.lineHeight, iconSize);

    // Render the label uppercase to match the oracle (Shiki's GitHub alert
    // plugin emits NOTE/TIP/IMPORTANT/WARNING/CAUTION). Labels are a tiny
    // fixed set of ASCII letters so uppercase in place is safe.
    char upper[32];
    size_t n = std::min<size_t>(sizeof(upper) - 1, std::strlen(label));
    for (size_t i = 0; i < n; ++i)
        upper[i] = (label[i] >= 'a' && label[i] <= 'z') ? char(label[i] - 32) : label[i];
    upper[n] = '\0';
    _renderTextRun(state, font, baseSize, state.config->alertBarColors[idx],
                   upper, upper + n);
    state.style = savedStyle;

    float lh = state.lineHeight > 0.0f ? state.lineHeight : baseSize;
    state.newLine(lh);
    state.lineHeight = 0.0f;
    state.cursor.x = state.lineXStart;
    // Extra breathing room between the alert label row and its body
    // paragraph — oracle leaves ~24 px here.
    state.cursor.y += state.config->paragraphSpacing * 0.5f;
}

void _renderHeadingAnchor(WalkState& state, ImFont* font, float baseSize)
{
    if (state.curHeadingSlug.empty())
        return;

    const char marker[] = " #";
    int savedLinkIdx = state.activeLinkIdx;
    std::string savedUrl = state.activeLinkUrl;
    std::string savedTitle = state.activeLinkTitle;
    bool savedHeadingAnchor = state.activeHeadingAnchor;

    state.activeLinkUrl = "#" + state.curHeadingSlug;
    state.activeLinkTitle = state.activeLinkUrl;
    state.activeHeadingAnchor = true;
    if (state.interaction)
    {
        state.interaction->linksThisFrame.push_back(state.activeLinkUrl);
        state.interaction->linkTitlesThisFrame.push_back(state.activeLinkTitle);
        state.activeLinkIdx = static_cast<int>(state.interaction->linksThisFrame.size()) - 1;
    }
    else
    {
        state.activeLinkIdx = 0;
    }

    _renderTextRun(state, font, baseSize, state.config->headingAnchorColor,
                   marker, marker + std::strlen(marker));

    state.activeLinkIdx = savedLinkIdx;
    state.activeLinkUrl = savedUrl;
    state.activeLinkTitle = savedTitle;
    state.activeHeadingAnchor = savedHeadingAnchor;
}

void _renderThematicBreak(WalkState& state)
{
    const RenderConfig& cfg = *state.config;
    if (state.cursor.y > state.origin.y + 0.1f)
        state.cursor.y += cfg.hrSpacing;
    float x0 = state.lineXStart;
    float x1 = state.lineXStart + state.availableWidth;
    float y = state.cursor.y + cfg.hrThickness * 0.5f;
    if (state.drawList)
    {
        state.drawList->AddLine(ImVec2(x0, y), ImVec2(x1, y), cfg.hrColor, cfg.hrThickness);
    }
    state.cursor.x = state.lineXStart;
    state.cursor.y += cfg.hrThickness + cfg.hrSpacing;
}

bool _renderProviderCodeBlock(WalkState& state, ImFont* font, float baseSize)
{
    const RenderConfig& cfg = *state.config;
    if (!cfg.assetProvider)
        return false;

    MarkdownAssetKind kind = MarkdownAssetKind::eDiagramBlock;
    if (!_isProviderCodeLanguage(state.codeBlockLang, kind))
        return false;

    MarkdownAssetRequest request;
    request.kind = kind;
    request.language = state.codeBlockLang;
    request.source = state.codeBlockBuffer;
    request.maxDisplayWidth = state.availableWidth;
    request.fontSize = baseSize;
    request.deviceScale = std::max(ImGui::GetIO().DisplayFramebufferScale.x, ImGui::GetIO().DisplayFramebufferScale.y);
    request.inlineAsset = false;
    request.documentGeneration = cfg.documentGeneration;

    MarkdownAssetResult asset = cfg.assetProvider->request(request);
    if (asset.state == MarkdownAssetState::eUnsupported)
        return false;

    if (state.cursor.y > state.origin.y + 0.1f)
        state.cursor.y += cfg.paragraphSpacing;

    float blockWidth = std::max(state.availableWidth, baseSize * 8.0f);
    float displayW = blockWidth;
    float displayH = std::max(baseSize * 3.0f, cfg.imageDefaultHeight);

    bool ready = asset.state == MarkdownAssetState::eReady && asset.imGuiTextureId
                 && asset.width > 0.0f && asset.height > 0.0f;
    if (ready)
    {
        displayW = std::min(blockWidth, asset.width);
        float scale = displayW / asset.width;
        displayH = asset.height * scale;
    }

    ImVec2 a(state.cursor.x, state.cursor.y);
    ImVec2 b(a.x + displayW, a.y + displayH);

    if (state.drawList)
    {
        if (ready)
        {
            state.drawList->AddImage(
                static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(asset.imGuiTextureId)),
                a, b, ImVec2(asset.uv0x, asset.uv0y), ImVec2(asset.uv1x, asset.uv1y));
        }
        else
        {
            state.drawList->AddRectFilled(a, b, cfg.imagePlaceholderBgColor, cfg.codeBlockBorderRadius);
            state.drawList->AddRect(a, b, cfg.imagePlaceholderBorderColor, cfg.codeBlockBorderRadius, 0, 1.0f);
            std::string label;
            if (asset.state == MarkdownAssetState::ePending)
                label = "rendering " + state.codeBlockLang + "...";
            else
                label = asset.error.empty() ? ("failed " + state.codeBlockLang) : asset.error;
            const char* lb = label.data();
            const char* le = lb + label.size();
            _addTextWithFontTexture(state.drawList, font, baseSize,
                                    ImVec2(a.x + cfg.codeBlockPadding, a.y + cfg.codeBlockPadding),
                                    cfg.imageAltColor, lb, le);
        }
    }

    state.cursor.x = state.lineXStart;
    state.cursor.y = b.y + cfg.paragraphSpacing;
    return true;
}

void _renderCodeBlock(WalkState& state, ImFont* font, float baseSize)
{
    const RenderConfig& cfg = *state.config;
    if (_renderProviderCodeBlock(state, font, baseSize))
        return;

    const float monoSize = cfg.codeFontSize > 0.0f ? cfg.codeFontSize : baseSize;
    ImFont* codeFont = cfg.codeFont ? cfg.codeFont : font;

    // Top spacing: a small gap so the code block doesn't hug the prior block.
    if (state.cursor.y > state.origin.y + 0.1f)
        state.cursor.y += cfg.paragraphSpacing;

    const std::string& buf = state.codeBlockBuffer;
    size_t end = buf.size();
    while (end > 0 && (buf[end - 1] == '\n' || buf[end - 1] == '\r'))
        --end;
    int lineCount = 1;
    for (size_t i = 0; i < end; ++i)
        if (buf[i] == '\n') ++lineCount;
    if (end == 0) lineCount = 1;

    float blockWidth = state.lineXStart + state.availableWidth - state.cursor.x;
    if (blockWidth < monoSize * 4.0f) blockWidth = monoSize * 4.0f;

    // Dedicated header row above the code body: full-width strip that
    // carries the language label (left) and the copy icon (right), like
    // the streamdown / GitHub code-block chrome. Visually this is the
    // dominant "this is code" affordance and makes the widget read the
    // same as prose-rendered markdown.
    const float headerPadX = std::max(10.0f, cfg.codeBlockPadding + 2.0f);
    const float headerH = std::max(28.0f, monoSize * 1.75f);
    const float bodyPadY = cfg.codeBlockPadding + 2.0f;
    // Empirically matched against the oracle stride: CSS line-height 1.5 on
    // 14 px renders at ~25 px/line in Chromium. With ImGui at monoSize≈16 px
    // a 1.35 multiplier puts the stride within 1 px.
    const float lineStep = monoSize * 1.35f;

    // Line-number gutter: right-aligned digits in the body text colour.
    ImFont* gutterFont = codeFont;
    const float gutterDigitSz = codeFont->CalcTextSizeA(monoSize, FLT_MAX, 0.0f, "9").x;
    int digitCount = 1;
    for (int n = lineCount; n >= 10; n /= 10) ++digitCount;
    if (digitCount < 2) digitCount = 2;
    const float gutterPadLeft = 14.0f;
    const float gutterPadRight = 16.0f;
    const float gutterWidth = digitCount * gutterDigitSz + gutterPadLeft + gutterPadRight;

    float blockH = headerH + lineCount * lineStep + 2.0f * bodyPadY;

    ImVec2 a(state.cursor.x, state.cursor.y);
    ImVec2 b(state.cursor.x + blockWidth, state.cursor.y + blockH);

    if (state.drawList)
    {
        // Outer fill covers the whole block. We deliberately don't re-fill
        // the header strip on top of the outer border (would cover the
        // top/side border pixels) — oracle's [code-block-header] uses the
        // same background as the body, so one fill is enough; the visual
        // distinction comes from the separator line drawn below.
        state.drawList->AddRectFilled(a, b, cfg.codeBlockBgColor, cfg.codeBlockBorderRadius);
        state.drawList->AddLine(ImVec2(a.x, a.y + headerH), ImVec2(b.x, a.y + headerH),
                                cfg.codeBlockBorderColor, 1.0f);
        state.drawList->AddRect(a, b, cfg.codeBlockBorderColor, cfg.codeBlockBorderRadius, 0, 1.0f);

        // Language label (left-aligned, vertically centred in the header).
        if (!state.codeBlockLang.empty())
        {
            const char* lp = state.codeBlockLang.data();
            const char* le = lp + state.codeBlockLang.size();
            ImVec2 labelSz = codeFont->CalcTextSizeA(monoSize, FLT_MAX, 0.0f, lp, le);
            ImVec2 labelPos(a.x + headerPadX, a.y + (headerH - labelSz.y) * 0.5f);
            _addTextWithFontTexture(state.drawList, codeFont, monoSize, labelPos,
                                    cfg.codeLangChipColor, lp, le);
        }
    }

    // Copy icon (right-aligned, vertically centred). Drop the heavy boxed
    // button — oracle-style chrome uses an icon-only affordance with a
    // hover/focus background ring. Keep ImGui InvisibleButton + focus for
    // accessibility (keyboard navigation, screen-reader-friendly semantics).
    const float iconSize = std::max(18.0f, monoSize);
    ImVec2 iconB(b.x - headerPadX, a.y + (headerH + iconSize) * 0.5f);
    ImVec2 iconA(iconB.x - iconSize, iconB.y - iconSize);

    bool pressed = false;
    bool hovered = false;
    bool focused = false;
    {
        // Stable ImGui ID per code block — see opus a11y comment in
        // _renderProviderCodeBlock for the rationale.
        uint32_t blockSeed = state.codeBlockIdSeed;
        ImVec2 savedCursor = ImGui::GetCursorScreenPos();
        ImGui::PushID(static_cast<int>(blockSeed));
        ImGui::SetCursorScreenPos(iconA);
        pressed = ImGui::InvisibleButton(
            "##copy",
            ImVec2(iconB.x - iconA.x, iconB.y - iconA.y),
            ImGuiButtonFlags_AllowOverlap);
        hovered = ImGui::IsItemHovered();
        focused = ImGui::IsItemFocused();
        ImGui::PopID();
        ImGui::SetCursorScreenPos(savedCursor);
    }

    if (state.drawList)
    {
        if (hovered || focused)
        {
            state.drawList->AddRectFilled(ImVec2(iconA.x - 3, iconA.y - 2),
                                          ImVec2(iconB.x + 3, iconB.y + 2),
                                          cfg.codeBlockCopyBgColor, 3.0f);
        }
        _drawCopyIcon(state.drawList, iconA, iconB, cfg.codeBlockCopyColor);
        if (hovered)
            ImGui::SetMouseCursor(ImGuiMouseCursor_Hand);
        if (hovered || focused)
            ImGui::SetTooltip("Copy code block (Enter)");
        if (focused && !hovered)
        {
            ImU32 ring = ImGui::GetColorU32(ImGuiCol_NavCursor);
            if ((ring & 0xFF000000u) == 0)
                ring = cfg.codeBlockCopyBorderColor;
            _drawFocusRing(state.drawList, iconA, iconB, ring);
        }
    }
    bool activated = pressed
        || (focused && (ImGui::IsKeyPressed(ImGuiKey_Enter, false)
                        || ImGui::IsKeyPressed(ImGuiKey_Space, false)));
    if (activated)
    {
        std::string copyBuffer(buf.data(), end);
        ImGui::SetClipboardText(copyBuffer.c_str());
    }

    // Body text + line-number gutter, below the header strip.
    float gutterX = a.x;
    float textX = gutterX + gutterWidth;
    float textY = a.y + headerH + bodyPadY;
    if (state.drawList)
    {
        const ImU32 gutterColor = cfg.codeTextColor;
        const char* p = buf.data();
        const char* e = p + end;
        int lineNumber = 1;
        char numbuf[16];
        while (p < e)
        {
            const char* nl = (const char*)std::memchr(p, '\n', static_cast<size_t>(e - p));
            const char* lineEnd = nl ? nl : e;

            int n = snprintf(numbuf, sizeof(numbuf), "%d", lineNumber);
            if (n > 0)
            {
                ImVec2 numSz = gutterFont->CalcTextSizeA(monoSize, FLT_MAX, 0.0f, numbuf, numbuf + n);
                ImVec2 numPos(gutterX + gutterWidth - gutterPadRight - numSz.x, textY);
                _addTextWithFontTexture(state.drawList, gutterFont, monoSize, numPos,
                                        gutterColor, numbuf, numbuf + n);
            }

            _renderHighlightedCodeLine(state, codeFont, monoSize, ImVec2(textX, textY), p, lineEnd);
            textY += lineStep;
            p = nl ? nl + 1 : e;
            ++lineNumber;
        }
    }

    state.cursor.x = state.lineXStart;
    state.cursor.y = b.y + cfg.paragraphSpacing;
}

float _drawListMarker(WalkState& state, const MdToken& liTok, ImFont* font, float fontSize, ImU32 color)
{
    const RenderConfig& cfg = *state.config;
    float markerX = state.cursor.x;
    float baselineY = state.cursor.y;

    // Task checkbox overrides any normal list marker.
    if (liTok.isTask)
    {
        bool checked = (liTok.taskMark == 'x' || liTok.taskMark == 'X');
        float box = fontSize * 0.80f;
        float ty = baselineY + (fontSize - box) * 0.5f;
        ImVec2 a(markerX, ty);
        ImVec2 b(markerX + box, ty + box);
        if (state.drawList)
        {
            state.drawList->AddRect(a, b, color, 2.0f, 0, 1.0f);
            if (checked)
            {
                float pad = box * 0.18f;
                ImVec2 p1(a.x + pad, a.y + box * 0.55f);
                ImVec2 p2(a.x + box * 0.42f, b.y - pad);
                ImVec2 p3(b.x - pad, a.y + pad);
                state.drawList->AddLine(p1, p2, color, 1.5f);
                state.drawList->AddLine(p2, p3, color, 1.5f);
            }
        }
        return box + cfg.bulletGap;
    }

    if (state.lists.empty())
        return 0.0f;
    const ListContext& ctx = state.lists.back();

    if (ctx.blockType == MD_BLOCK_OL)
    {
        char buf[16];
        int n = snprintf(buf, sizeof(buf), "%u.", ctx.counter);
        if (n < 0) n = 0;
        if (state.drawList)
        {
            _addTextWithFontTexture(state.drawList, font, fontSize, ImVec2(markerX, baselineY), color, buf, buf + n);
        }
        ImVec2 sz = font->CalcTextSizeA(fontSize, FLT_MAX, 0.0f, buf, buf + n);
        return sz.x + cfg.bulletGap;
    }

    // Unordered bullet.  '•' for top depth; '-' / '*' for nested depths
    // so nesting is visually distinguishable from indent alone.
    const char* bullet;
    switch (ctx.depth % 3)
    {
    case 0:  bullet = "\xE2\x80\xA2"; break; // •
    case 1:  bullet = "-"; break;
    default: bullet = "*"; break;
    }
    const char* bulletEnd = bullet + std::strlen(bullet);
    if (state.drawList)
    {
        _addTextWithFontTexture(state.drawList, font, fontSize, ImVec2(markerX, baselineY), color, bullet, bulletEnd);
    }
    ImVec2 sz = font->CalcTextSizeA(fontSize, FLT_MAX, 0.0f, bullet, bulletEnd);
    return sz.x + cfg.bulletGap;
}

void _renderEmojiGlyph(WalkState& state, float fontSize, uint64_t key)
{
    ImVec2 uv0, uv1;
    if (!state.emojiAtlas->lookup(key, uv0, uv1))
        return;

    float sz = fontSize;
    float remaining = state.lineXStart + state.availableWidth - state.cursor.x;
    if (remaining < sz)
    {
        state.newLine(fontSize);
    }

    if (state.drawList)
    {
        ImVec2 a(state.cursor.x, state.cursor.y);
        ImVec2 b(a.x + sz, a.y + sz);
        state.drawList->AddImage(state.emojiAtlas->textureId(), a, b, uv0, uv1);
    }
    state.cursor.x += sz;
    state.lineHeight = ImMax(state.lineHeight, sz);
}

void _drawInlineImage(WalkState& state, ImFont* font, float baseSize)
{
    const RenderConfig& cfg = *state.config;

    if (cfg.assetProvider)
    {
        std::string_view srcView(state.imageSrc);
        MarkdownAssetRequest request;
        request.kind = (endsWithICase(srcView, ".svg") || endsWithICase(srcView, ".svgz"))
                           ? MarkdownAssetKind::eSvgImage
                           : MarkdownAssetKind::eRasterImage;
        request.source = state.imageSrc;
        request.altText = state.imageAlt;
        request.title = state.imageTitle;
        request.maxDisplayWidth = state.availableWidth;
        request.fontSize = baseSize;
        request.deviceScale = std::max(ImGui::GetIO().DisplayFramebufferScale.x, ImGui::GetIO().DisplayFramebufferScale.y);
        request.inlineAsset = true;
        request.documentGeneration = cfg.documentGeneration;

        MarkdownAssetResult asset = cfg.assetProvider->request(request);
        if (asset.state == MarkdownAssetState::eReady && asset.imGuiTextureId
            && asset.width > 0.0f && asset.height > 0.0f)
        {
            ResolvedImage img;
            img.textureId = static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(asset.imGuiTextureId));
            img.size = { asset.width, asset.height };
            img.uv0 = { asset.uv0x, asset.uv0y };
            img.uv1 = { asset.uv1x, asset.uv1y };
            img.ready = true;
            _drawResolvedInlineImage(state, font, baseSize, img);
            return;
        }
        if (asset.state == MarkdownAssetState::ePending || asset.state == MarkdownAssetState::eFailed)
        {
            _drawImagePlaceholder(state, font, baseSize);
            return;
        }
        // eUnsupported falls through to the built-in resolver.
    }

    if (!state.imageResolver)
    {
        _drawImagePlaceholder(state, font, baseSize);
        return;
    }

    ResolvedImage img = state.imageResolver->resolve(state.imageSrc);
    if (!img.ready)
    {
        _drawImagePlaceholder(state, font, baseSize);
        return;
    }

    _drawResolvedInlineImage(state, font, baseSize, img);
}

void _appendTableCellText(WalkState& state, const std::string& text)
{
    if (!state.inTable || state.tableRows.empty())
        return;
    int c = state.tableCurCol;
    if (c < 0 || c >= (int)state.tableRows.back().size())
        return;

    TableCell& cell = state.tableRows.back()[c];
    cell.text.append(text);
    if (text.empty())
        return;

    if (!cell.runs.empty()
        && cell.runs.back().kind == InlineRun::Kind::Text
        && cell.runs.back().style.strong == state.style.strong
        && cell.runs.back().style.em == state.style.em
        && cell.runs.back().style.code == state.style.code
        && cell.runs.back().style.del == state.style.del
        && cell.runs.back().linkUrl == state.activeLinkUrl
        && cell.runs.back().linkTitle == state.activeLinkTitle)
    {
        cell.runs.back().text.append(text);
    }
    else
    {
        InlineRun run;
        run.kind = InlineRun::Kind::Text;
        run.text = text;
        run.style = state.style;
        run.linkUrl = state.activeLinkUrl;
        run.linkTitle = state.activeLinkTitle;
        cell.runs.push_back(std::move(run));
    }

    if (!_styleIsPlain(state.style) || !state.activeLinkUrl.empty())
        cell.hasRichContent = true;

    // Any non-ASCII byte (emoji, CJK, accented Latin, ...) routes through the
    // rich-runs layout path so the emoji atlas and fallback font can apply.
    // The plain-text cell path draws raw via _addTextWithFontTexture and has
    // no emoji lookup, so without this flip a cell like "Done \u2705" would
    // render the checkmark as tofu.
    if (!cell.hasRichContent)
    {
        for (unsigned char c : text)
        {
            if (c >= 0x80)
            {
                cell.hasRichContent = true;
                break;
            }
        }
    }
}

void _appendTableCellImage(WalkState& state)
{
    if (!state.inTable || state.tableRows.empty())
        return;
    int c = state.tableCurCol;
    if (c < 0 || c >= (int)state.tableRows.back().size())
        return;

    TableCell& cell = state.tableRows.back()[c];
    InlineRun run;
    run.kind = InlineRun::Kind::Image;
    run.src = state.imageSrc;
    run.alt = state.imageAlt;
    run.title = state.imageTitle;
    run.style = state.style;
    cell.runs.push_back(std::move(run));
    cell.text.append(state.imageAlt.empty() ? state.imageSrc : state.imageAlt);
    cell.hasRichContent = true;
}

void _renderTable(WalkState& state, ImFont* font, float baseSize)
{
    const RenderConfig& cfg = *state.config;
    if (state.tableRows.empty() || state.tableColCount <= 0)
        return;

    if (state.cursor.y > state.origin.y + 0.1f)
        state.cursor.y += cfg.paragraphSpacing;

    float totalW = state.availableWidth;
    int cols = state.tableColCount;
    float rowH = baseSize + 2.0f * cfg.tablePadding;

    if ((int)state.tableColAlign.size() < cols)
        state.tableColAlign.resize(cols, 0);

    float x0 = state.lineXStart;
    float y = state.cursor.y;
    float visibleRight = x0 + totalW;

    std::vector<MarkdownTableColumnMeasure> measures(cols);
    for (int c = 0; c < cols; ++c)
    {
        measures[c].minWidth = cfg.tableMinColumnWidth;
        measures[c].preferredWidth = cfg.tableMinColumnWidth;
    }
    for (const auto& row : state.tableRows)
    {
        for (int c = 0; c < cols && c < (int)row.size(); ++c)
        {
            const std::string& text = row[c].text;
            float preferred = cfg.tableMinColumnWidth;
            float longest = cfg.tableMinColumnWidth;
            if (!text.empty())
            {
                const char* begin = text.data();
                const char* end = begin + text.size();
                preferred = font->CalcTextSizeA(baseSize, FLT_MAX, 0.0f, begin, end).x + 2.0f * cfg.tablePadding;
                const char* word = begin;
                while (word < end)
                {
                    while (word < end && std::isspace(static_cast<unsigned char>(*word)))
                        ++word;
                    const char* wordEnd = word;
                    while (wordEnd < end && !std::isspace(static_cast<unsigned char>(*wordEnd)))
                        ++wordEnd;
                    if (wordEnd > word)
                    {
                        float wordW = font->CalcTextSizeA(baseSize, FLT_MAX, 0.0f, word, wordEnd).x
                                      + 2.0f * cfg.tablePadding;
                        longest = std::max(longest, wordW);
                    }
                    word = wordEnd;
                }
            }
            if (row[c].hasRichContent)
                preferred = std::max(preferred, cfg.imageDefaultWidth * 0.6f + 2.0f * cfg.tablePadding);
            measures[c].minWidth = std::max(measures[c].minWidth, longest);
            measures[c].preferredWidth = std::max(measures[c].preferredWidth, preferred);
        }
    }

    MarkdownTableLayoutResult layout = computeMarkdownTableColumnLayout(
        cfg.tableLayoutPolicy, measures, totalW,
        cfg.tableMinColumnWidth, cfg.tableMaxColumnWidth, cfg.tableFixedColumnWidth);
    std::vector<float> colWidths = layout.columnWidths;
    if ((int)colWidths.size() != cols)
        colWidths.assign(cols, totalW / static_cast<float>(cols));

    std::vector<float> colX(cols + 1, x0);
    for (int c = 0; c < cols; ++c)
        colX[c + 1] = colX[c] + colWidths[c];
    float tableW = layout.tableWidth > 0.0f ? layout.tableWidth : (colX.back() - x0);
    float visibleTableW = std::min(tableW, totalW);

    auto wrapCell = [&](const std::string& text, float colW) -> std::vector<std::pair<const char*, const char*>> {
        std::vector<std::pair<const char*, const char*>> lines;
        if (text.empty()) { lines.emplace_back(nullptr, nullptr); return lines; }
        const char* begin = text.data();
        const char* end = begin + text.size();
        float wrapW = colW - 2.0f * cfg.tablePadding;
        if (wrapW < baseSize * 2.0f) wrapW = baseSize * 2.0f;
        while (begin < end)
        {
            const char* w = font->CalcWordWrapPosition(baseSize, begin, end, wrapW);
            if (w == begin) w = begin + 1;
            lines.emplace_back(begin, w);
            begin = w;
            while (begin < end && *begin == ' ') ++begin;
        }
        if (lines.empty()) lines.emplace_back(nullptr, nullptr);
        return lines;
    };

    std::vector<float> rowHeights(state.tableRows.size(), rowH);

    for (size_t r = 0; r < state.tableRows.size(); ++r)
    {
        auto& row = state.tableRows[r];
        std::vector<std::vector<std::pair<const char*, const char*>>> cellLines(cols);
        float thisRowH = rowH;
        bool isHeader = (r == 0) && !row.empty() && row[0].isHeader;
        for (int c = 0; c < cols && c < (int)row.size(); ++c)
        {
            float colW = colWidths[c];
            if (row[c].hasRichContent)
            {
                float innerW = std::max(baseSize * 2.0f, colW - 2.0f * cfg.tablePadding);
                ImU32 measureColor = isHeader ? cfg.tableHeaderTextColor : cfg.tableTextColor;
                float contentH = _layoutInlineRuns(state, row[c].runs, font, baseSize, measureColor, ImVec2(0.0f, 0.0f),
                                                   innerW, isHeader, nullptr, nullptr);
                thisRowH = std::max(thisRowH, contentH + 2.0f * cfg.tablePadding);
            }
            else
            {
                cellLines[c] = wrapCell(row[c].text, colW);
                thisRowH = std::max(thisRowH, (float)cellLines[c].size() * baseSize + 2.0f * cfg.tablePadding);
            }
        }
        rowHeights[r] = thisRowH;

        ImU32 bg = 0;
        if (isHeader)
            bg = cfg.tableHeaderBg;
        else if ((r % 2) == 1)
            bg = cfg.tableRowAltBg;

        if (state.drawList && bg != 0)
        {
            state.drawList->AddRectFilled(ImVec2(x0, y), ImVec2(x0 + visibleTableW, y + thisRowH), bg);
        }

        for (int c = 0; c < cols && c < (int)row.size(); ++c)
        {
            float cx = colX[c];
            float colW = colWidths[c];
            if (cx >= visibleRight)
                continue;
            uint8_t align = state.tableColAlign[c];
            ImU32 cellColor = isHeader ? cfg.tableHeaderTextColor : cfg.tableTextColor;

            if (row[c].hasRichContent)
            {
                if (state.drawList)
                {
                    ImVec2 clipMin(cx + 1.0f, y + 1.0f);
                    ImVec2 clipMax(std::min(cx + colW - 1.0f, visibleRight), y + thisRowH - 1.0f);
                    if (clipMax.x > clipMin.x)
                    {
                        state.drawList->PushClipRect(clipMin, clipMax, true);
                        ImU32 richColor = isHeader ? cfg.tableHeaderTextColor : cfg.tableTextColor;
                        _layoutInlineRuns(state, row[c].runs, font, baseSize, richColor,
                                          ImVec2(cx + cfg.tablePadding, y + cfg.tablePadding),
                                          std::max(baseSize * 2.0f, colW - 2.0f * cfg.tablePadding),
                                          isHeader, state.drawList, state.interaction);
                        state.drawList->PopClipRect();
                    }
                }
                continue;
            }

            for (size_t li = 0; li < cellLines[c].size(); ++li)
            {
                const char* lb = cellLines[c][li].first;
                const char* le = cellLines[c][li].second;
                if (!lb || !le) continue;
                ImVec2 sz = font->CalcTextSizeA(baseSize, FLT_MAX, 0.0f, lb, le);
                float tx = cx + cfg.tablePadding;
                float avail = colW - 2.0f * cfg.tablePadding;
                if (align == 2)      tx = cx + (colW - sz.x) * 0.5f;
                else if (align == 3) tx = cx + colW - cfg.tablePadding - sz.x;
                else                 tx = cx + cfg.tablePadding;
                (void)avail;
                float ty = y + cfg.tablePadding + li * baseSize;
                if (state.drawList)
                {
                    ImVec2 clipMin(cx + 1.0f, y + 1.0f);
                    ImVec2 clipMax(std::min(cx + colW - 1.0f, visibleRight), y + thisRowH - 1.0f);
                    if (clipMax.x > clipMin.x)
                    {
                        state.drawList->PushClipRect(clipMin, clipMax, true);
                        _addTextWithFontTexture(state.drawList, font, baseSize, ImVec2(tx, ty), cellColor, lb, le);
                        if (isHeader)
                        {
                            // Poor-man's bold: shift+1.
                            _addTextWithFontTexture(state.drawList, font, baseSize, ImVec2(tx + 1, ty), cellColor, lb, le);
                        }
                        state.drawList->PopClipRect();
                    }
                }
            }
        }
        y += thisRowH;
    }

    // Borders: outer + inner column lines + inner row lines.
    if (state.drawList)
    {
        ImU32 bc = cfg.tableBorderColor;
        state.drawList->AddRect(ImVec2(x0, state.cursor.y), ImVec2(x0 + visibleTableW, y), bc, 0.0f, 0, 1.0f);
        for (int c = 1; c < cols; ++c)
        {
            float vx = colX[c];
            if (vx >= visibleRight)
                break;
            state.drawList->AddLine(ImVec2(vx, state.cursor.y), ImVec2(vx, y), bc, 1.0f);
        }
        float hy = state.cursor.y;
        for (size_t r = 0; r < state.tableRows.size(); ++r)
        {
            hy += rowHeights[r];
            if (r + 1 < state.tableRows.size())
            {
                state.drawList->AddLine(ImVec2(x0, hy), ImVec2(x0 + visibleTableW, hy), bc, 1.0f);
            }
        }
    }

    state.cursor.x = state.lineXStart;
    state.cursor.y = y + cfg.paragraphSpacing;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
