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

// Text-run layout: emoji/ZWJ scanning, UTF-8 decode, fallback-font
// rerouting, inline decoration, and paragraph/heading spacing.
//
#include "MarkdownText.h"
#include "MarkdownPaint.h"
#include "TwemojiAtlas.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>

#include <md4c.h>

#include <algorithm>
#include <cstring>

OMNIUI_NAMESPACE_OPEN_SCOPE

// =====================================================================
// UTF-8 decode
// =====================================================================

int _decodeUtf8(const char* p, const char* end, uint32_t* outCp)
{
    uint8_t c = static_cast<uint8_t>(*p);
    if (c < 0x80)
    {
        *outCp = c;
        return 1;
    }
    if ((c & 0xE0) == 0xC0 && p + 1 < end)
    {
        *outCp = (c & 0x1F) << 6 | (static_cast<uint8_t>(p[1]) & 0x3F);
        return 2;
    }
    if ((c & 0xF0) == 0xE0 && p + 2 < end)
    {
        *outCp = (c & 0x0F) << 12 | (static_cast<uint8_t>(p[1]) & 0x3F) << 6 | (static_cast<uint8_t>(p[2]) & 0x3F);
        return 3;
    }
    if ((c & 0xF8) == 0xF0 && p + 3 < end)
    {
        *outCp = (c & 0x07) << 18 | (static_cast<uint8_t>(p[1]) & 0x3F) << 12 |
                 (static_cast<uint8_t>(p[2]) & 0x3F) << 6 | (static_cast<uint8_t>(p[3]) & 0x3F);
        return 4;
    }
    *outCp = 0xFFFD;
    return 1;
}

// =====================================================================
// Emoji classification + scanning
// =====================================================================

bool _isEmojiCodepoint(uint32_t cp)
{
    if (cp >= 0x1F600 && cp <= 0x1F64F) return true; // emoticons
    if (cp >= 0x1F300 && cp <= 0x1F5FF) return true; // misc symbols & pictographs
    if (cp >= 0x1F680 && cp <= 0x1F6FF) return true; // transport & map
    if (cp >= 0x1F700 && cp <= 0x1F77F) return true; // alchemical
    if (cp >= 0x1F780 && cp <= 0x1F7FF) return true; // geometric shapes ext
    if (cp >= 0x1F800 && cp <= 0x1F8FF) return true; // supplemental arrows-C
    if (cp >= 0x1F900 && cp <= 0x1F9FF) return true; // supplemental symbols
    if (cp >= 0x1FA00 && cp <= 0x1FA6F) return true; // chess symbols
    if (cp >= 0x1FA70 && cp <= 0x1FAFF) return true; // symbols & pictographs ext-A
    if (cp >= 0x2600 && cp <= 0x27BF) return true;   // misc symbols + dingbats
    if (cp >= 0x2300 && cp <= 0x23FF) return true;   // misc technical
    if (cp >= 0x2700 && cp <= 0x27BF) return true;   // dingbats
    if (cp >= 0x1F1E0 && cp <= 0x1F1FF) return true; // regional indicators (flags)
    if (cp == 0x200D) return true;                    // ZWJ
    if (cp >= 0xFE00 && cp <= 0xFE0F) return true;   // variation selectors
    if (cp >= 0x1F3FB && cp <= 0x1F3FF) return true;  // skin tone modifiers
    if (cp == 0x2764 || cp == 0x2763) return true;    // hearts
    if (cp == 0x2B50 || cp == 0x2B55) return true;    // star, circle
    if (cp == 0x231A || cp == 0x231B) return true;    // watch, hourglass
    if (cp >= 0x25AA && cp <= 0x25FE) return true;    // geometric shapes
    if (cp == 0x00A9 || cp == 0x00AE) return true;    // (c), (r)
    if (cp == 0x2122 || cp == 0x2139) return true;    // TM, info
    if (cp >= 0x2194 && cp <= 0x21AA) return true;    // arrows
    if (cp >= 0x23E9 && cp <= 0x23F3) return true;    // play buttons
    if (cp >= 0x23F8 && cp <= 0x23FA) return true;    // media control
    if (cp == 0x2934 || cp == 0x2935) return true;    // curved arrows
    if (cp >= 0x25FB && cp <= 0x25FE) return true;    // squares
    if (cp >= 0x2614 && cp <= 0x2615) return true;    // umbrella, hot beverage
    if (cp == 0x2648 || (cp >= 0x2648 && cp <= 0x2653)) return true; // zodiac
    if (cp >= 0x2660 && cp <= 0x2668) return true;    // card suits, hot springs
    if (cp == 0x267F || cp == 0x2692 || cp == 0x2693 || cp == 0x2694 || cp == 0x2695 ||
        cp == 0x2696 || cp == 0x2697 || cp == 0x2699 || cp == 0x269B || cp == 0x269C) return true;
    if (cp == 0x26A0 || cp == 0x26A1 || cp == 0x26AA || cp == 0x26AB) return true;
    if (cp >= 0x26BD && cp <= 0x26C8) return true;    // sports
    if (cp >= 0x26CE && cp <= 0x26CF) return true;
    if (cp == 0x26D1 || cp == 0x26D3 || cp == 0x26D4) return true;
    if (cp >= 0x26E9 && cp <= 0x26EA) return true;
    if (cp >= 0x26F0 && cp <= 0x26FA) return true;    // outdoor
    if (cp == 0x26FD) return true;                     // fuel pump
    if (cp == 0x2702 || cp == 0x2705 || cp == 0x2708 || cp == 0x2709) return true;
    if (cp >= 0x270A && cp <= 0x270D) return true;     // hand signs
    if (cp == 0x270F || cp == 0x2712) return true;     // pencil, pen
    if (cp == 0x2714 || cp == 0x2716) return true;     // check, cross
    if (cp >= 0x271D && cp <= 0x2721) return true;
    if (cp == 0x2728) return true;                     // sparkles
    if (cp >= 0x2733 && cp <= 0x2734) return true;
    if (cp == 0x2744 || cp == 0x2747) return true;     // snowflake, sparkle
    if (cp >= 0x274C && cp <= 0x274E) return true;
    if (cp >= 0x2753 && cp <= 0x2755) return true;     // question/exclaim
    if (cp == 0x2757) return true;
    if (cp >= 0x2795 && cp <= 0x2797) return true;     // math
    if (cp == 0x27A1) return true;                     // right arrow
    if (cp == 0x27B0) return true;                     // curly loop
    return false;
}

bool _isVariationSelector(uint32_t cp) { return cp >= 0xFE00 && cp <= 0xFE0F; }
bool _isZWJ(uint32_t cp)               { return cp == 0x200D; }
bool _isSkinTone(uint32_t cp)          { return cp >= 0x1F3FB && cp <= 0x1F3FF; }
bool _isRegionalIndicator(uint32_t cp) { return cp >= 0x1F1E6 && cp <= 0x1F1FF; }

int _scanEmojiSequence(const char* p, const char* end, TwemojiAtlas* atlas,
                       uint32_t* cps, int maxCp, int* cpCount, uint64_t* outKey)
{
    const char* start = p;
    *cpCount = 0;

    uint32_t firstCp;
    int firstLen = _decodeUtf8(p, end, &firstCp);

    if (!_isEmojiCodepoint(firstCp))
        return 0;

    cps[(*cpCount)++] = firstCp;
    p += firstLen;

    // Regional indicator pairs (flags)
    if (_isRegionalIndicator(firstCp) && p < end)
    {
        uint32_t secondCp;
        int secondLen = _decodeUtf8(p, end, &secondCp);
        if (_isRegionalIndicator(secondCp))
        {
            cps[(*cpCount)++] = secondCp;
            p += secondLen;
        }
    }

    // Greedily consume ZWJ sequences, skin tones, and variation selectors
    while (p < end && *cpCount < maxCp)
    {
        uint32_t cp;
        int len = _decodeUtf8(p, end, &cp);

        if (_isVariationSelector(cp))
        {
            cps[(*cpCount)++] = cp;
            p += len;
            continue;
        }
        if (_isSkinTone(cp))
        {
            cps[(*cpCount)++] = cp;
            p += len;
            continue;
        }
        if (_isZWJ(cp))
        {
            const char* afterZwj = p + len;
            if (afterZwj < end)
            {
                uint32_t nextCp;
                int nextLen = _decodeUtf8(afterZwj, end, &nextCp);
                if (_isEmojiCodepoint(nextCp))
                {
                    cps[(*cpCount)++] = cp;
                    cps[(*cpCount)++] = nextCp;
                    p = afterZwj + nextLen;
                    continue;
                }
            }
        }
        break;
    }

    // Build key and check atlas
    uint64_t key = TwemojiAtlas::hashSequence(cps, *cpCount);
    if (atlas->hasGlyph(key))
    {
        *outKey = key;
        return static_cast<int>(p - start);
    }

    // Strip FE0F variation selectors and retry
    uint32_t stripped[16];
    int strippedCount = 0;
    for (int i = 0; i < *cpCount && strippedCount < 16; ++i)
    {
        if (!_isVariationSelector(cps[i]))
            stripped[strippedCount++] = cps[i];
    }
    if (strippedCount > 0 && strippedCount != *cpCount)
    {
        key = TwemojiAtlas::hashSequence(stripped, strippedCount);
        if (atlas->hasGlyph(key))
        {
            *outKey = key;
            return static_cast<int>(p - start);
        }
    }

    // Single codepoint fallback
    if (*cpCount > 1)
    {
        key = TwemojiAtlas::hashSequence(cps, 1);
        if (atlas->hasGlyph(key))
        {
            *outKey = key;
            return firstLen;
        }
    }

    return 0;
}

// =====================================================================
// Font-glyph probe -- astral-plane correctness fix
// =====================================================================

bool _fontHasGlyph(ImFont* font, float fontSize, uint32_t cp)
{
    if (!font)
        return false;
    // Astral-plane handling:
    //  - ImWchar32 builds (IMGUI_USE_WCHAR32): glyph table is keyed by full
    //    codepoint, so we can legitimately probe every codepoint here.
    //    The prior `cp > 0xFFFF => return false` early-return broke the
    //    fallback-font route for every emoji / CJK-Ext / math astral glyph
    //    because the caller only routes when the active font reports
    //    missing AND the fallback reports present.
    //  - ImWchar16 builds: the glyph table literally cannot index past
    //    the BMP.  We preserve the old `cp > 0xFFFF => false` behavior
    //    since neither `IsGlyphLoaded` nor `FindGlyphNoFallback` would
    //    succeed for such codepoints on this build.
    if constexpr (sizeof(ImWchar) >= 4)
    {
        ImFontBaked* baked = font->GetFontBaked(fontSize);
        if (!baked || !baked->IsGlyphLoaded(static_cast<ImWchar>(cp)))
            return false;
        return baked->FindGlyphNoFallback(static_cast<ImWchar>(cp)) != nullptr;
    }
    else
    {
        if (cp > 0xFFFF)
            return false; // BMP-only build: caller must try fallback font.
        ImFontBaked* baked = font->GetFontBaked(fontSize);
        if (!baked || !baked->IsGlyphLoaded(static_cast<ImWchar>(cp)))
            return false;
        return baked->FindGlyphNoFallback(static_cast<ImWchar>(cp)) != nullptr;
    }
}

// =====================================================================
// Segment decoration (inline code bg, bold-fallback, strikethrough, link)
// =====================================================================

bool _decorateSegment(WalkState& state, ImFont* font, float fontSize, ImU32 color,
                      const char* begin, const char* end, ImVec2 pos, float width)
{
    bool clicked = false;
    const InlineStyle& s = state.style;
    const bool isLink = state.activeLinkIdx >= 0;
    bool isHovered = false;
    bool isFocused = false;

    // Hit test + focus via a real ImGui InvisibleButton so every link
    // segment sits on the focus graph.  Wrapped links are distinguished
    // by seg-relative suffix (linkSegmentIdx) so ImGui does not collapse
    // co-line segments into one rect.  ImGui's built-in gating already
    // handles popup-blocked input, so we no longer need a manual
    // IsWindowHovered guard.
    if (isLink && state.drawList)
    {
        char idBuf[48];
        std::snprintf(idBuf, sizeof(idBuf), "md.link.%d.s%d",
                      state.activeLinkIdx, state.linkSegmentIdx);
        state.linkSegmentIdx++;

        // Save the cursor -- text layout lives outside ImGui's per-item
        // layout, so we must not let InvisibleButton advance it.
        ImVec2 savedCursor = ImGui::GetCursorScreenPos();
        ImGui::PushID(idBuf);
        ImGui::SetCursorScreenPos(pos);
        bool pressed = ImGui::InvisibleButton(
            "##link", ImVec2(width, fontSize),
            ImGuiButtonFlags_AllowOverlap);
        isHovered = ImGui::IsItemHovered();
        isFocused = ImGui::IsItemFocused();
        bool activated = pressed
            || (isFocused && (ImGui::IsKeyPressed(ImGuiKey_Enter, false)
                              || ImGui::IsKeyPressed(ImGuiKey_Space, false)));
        ImGui::PopID();
        ImGui::SetCursorScreenPos(savedCursor);

        if (state.interaction)
        {
            if (isHovered)
                state.interaction->hoveredLinkIdx = state.activeLinkIdx;
            if (isFocused)
                state.interaction->focusedLinkIdx = state.activeLinkIdx;
        }

        if (isHovered)
            ImGui::SetMouseCursor(ImGuiMouseCursor_Hand);

        if ((isHovered || isFocused) && state.interaction
            && state.activeLinkIdx < (int)state.interaction->linksThisFrame.size())
        {
            const std::string& url = state.interaction->linksThisFrame[state.activeLinkIdx];
            const bool hasTitle = state.activeLinkIdx < (int)state.interaction->linkTitlesThisFrame.size()
                                  && !state.interaction->linkTitlesThisFrame[state.activeLinkIdx].empty();
            const std::string& tooltip = hasTitle
                                             ? state.interaction->linkTitlesThisFrame[state.activeLinkIdx]
                                             : url;
            if (!tooltip.empty())
                ImGui::SetTooltip("%s", tooltip.c_str());
        }

        if (activated)
            clicked = true;
    }

    if (!state.drawList)
        return clicked;

    // Inline code: draw a rounded background rect underneath. Oracle CSS
    // uses padding `2px 6px` + `border-radius: 6px` so the chip reads as a
    // clearly-bounded object, not a barely-visible wash.
    if (s.code > 0)
    {
        const float padX = 5.0f;
        const float padY = 2.0f;
        ImVec2 a(pos.x - padX, pos.y - padY);
        ImVec2 b(pos.x + width + padX, pos.y + fontSize + padY);
        state.drawList->AddRectFilled(a, b, state.config->codeBgColor, 5.0f);
    }

    // Main text.
    _addTextWithFontTexture(state.drawList, font, fontSize, pos, color, begin, end);

    // Strong fallback: when a real bold/heading face is unavailable, re-draw
    // the segment shifted by 1 px. Headings always render bold.
    if ((s.strong > 0 || state.curBlock == MD_BLOCK_H) && !_hasRealStrongFontForState(state))
    {
        ImVec2 shifted(pos.x + 1.0f, pos.y);
        _addTextWithFontTexture(state.drawList, font, fontSize, shifted, color, begin, end);
    }

    // Strikethrough: horizontal line through the segment midline.
    if (s.del > 0)
    {
        float y = pos.y + fontSize * 0.55f;
        state.drawList->AddLine(ImVec2(pos.x, y), ImVec2(pos.x + width, y), color, 1.0f);
    }

    // Link underline: thin line at the segment baseline.  Wrapped links get
    // one underline per visual segment automatically.
    if (isLink)
    {
        bool wasHovered = state.interaction
                          && state.interaction->prevHoveredLinkIdx == state.activeLinkIdx;
        bool wasFocused = state.interaction
                          && state.interaction->prevFocusedLinkIdx == state.activeLinkIdx;
        bool highlight = isHovered || wasHovered || isFocused || wasFocused;
        ImU32 lineColor = state.activeHeadingAnchor
                              ? state.config->headingAnchorColor
                              : (highlight
                                     ? state.config->linkHoverColor
                                     : state.config->linkColor);
        float y = pos.y + fontSize - 1.0f;
        state.drawList->AddLine(ImVec2(pos.x, y), ImVec2(pos.x + width, y), lineColor, 1.0f);

        // Focus ring: only when focused AND not hovered (hover already
        // recolors the segment; drawing both stacks visually).  Uses the
        // ImGui NavCursor color so it matches platform chrome; falls back
        // to linkHoverColor when the theme hasn't set one.
        if (isFocused && !isHovered)
        {
            ImU32 ring = ImGui::GetColorU32(ImGuiCol_NavCursor);
            if ((ring & 0xFF000000u) == 0)
                ring = state.config->linkHoverColor;
            _drawFocusRing(state.drawList,
                           ImVec2(pos.x, pos.y), ImVec2(pos.x + width, pos.y + fontSize),
                           ring);
        }
    }

    return clicked;
}

// =====================================================================
// Plain / full text run
// =====================================================================

void _renderPlainTextRun(WalkState& state, ImFont* font, float fontSize, ImU32 color,
                         const char* begin, const char* end)
{
    if (!begin || begin >= end || !font)
        return;

    // Line-height: body text uses the configured multiplier (HTML-like ~1.5),
    // headings get a tighter multiplier so a single-line heading doesn't waste
    // vertical space.  Fractional advance rounded up to keep glyphs aligned.
    const float multiplier = (state.curBlock == MD_BLOCK_H)
                                 ? state.config->headingLineHeightMultiplier
                                 : state.config->lineHeightMultiplier;
    const float lineH = fontSize * multiplier;
    const ImU32 segColor = _resolveTextColor(state, color);

    // Extra slack (4 px) before the right edge so sub-pixel rounding between
    // fontSize and the font atlas does not push a full word one pixel past
    // the wrap boundary — which, with only 1 px reserved, caused ImGui's
    // CalcWordWrapPosition to fall into its force-mid-word-break branch and
    // produce splits like "giv"+"e".
    const float rightReserve = 4.0f;
    while (begin < end)
    {
        float remaining = state.lineXStart + state.availableWidth - rightReserve - state.cursor.x;
        if (remaining < fontSize * 0.5f)
        {
            state.newLine(lineH);
            remaining = state.availableWidth - rightReserve;
        }

        const char* wrap = font->CalcWordWrapPosition(fontSize, begin, end, remaining);

        if (wrap == begin)
        {
            if (state.cursor.x <= state.lineXStart + 0.5f)
            {
                wrap = begin + 1;
            }
            else
            {
                state.newLine(lineH);
                continue;
            }
        }

        // ImGui's CalcWordWrapPosition force-breaks mid-word when the
        // current word alone exceeds the remaining width. If the wrap
        // result lands between two non-whitespace bytes and we still
        // have room for a newline retry, newline instead.
        if (wrap > begin && wrap < end && state.cursor.x > state.lineXStart + 0.5f)
        {
            char before = *(wrap - 1);
            char at = *wrap;
            auto is_ws = [](char c) { return c == ' ' || c == '\t' || c == '\n'; };
            if (!is_ws(before) && !is_ws(at))
            {
                state.newLine(lineH);
                continue;
            }
        }

        ImVec2 size = font->CalcTextSizeA(fontSize, FLT_MAX, 0.0f, begin, wrap);
        ImVec2 segPos = state.cursor;
        bool clicked = _decorateSegment(state, font, fontSize, segColor, begin, wrap, segPos, size.x);

        if (clicked && state.interaction
            && state.activeLinkIdx >= 0
            && state.activeLinkIdx < (int)state.interaction->linksThisFrame.size())
        {
            const std::string& url = state.interaction->linksThisFrame[state.activeLinkIdx];
            // In-document anchors (`#slug`) route to onAnchorNavigate when
            // set so MarkdownWidget can drive SetScrollY internally.  Fall
            // back to onLinkClicked for external URLs or when no anchor
            // callback is installed.
            bool isAnchor = !url.empty() && url[0] == '#';
            if (isAnchor && state.interaction->onAnchorNavigate)
                state.interaction->onAnchorNavigate(url);
            else if (state.interaction->onLinkClicked)
                state.interaction->onLinkClicked(url);
        }

        state.cursor.x += size.x;
        state.lineHeight = ImMax(state.lineHeight, lineH);

        begin = wrap;
        if (begin < end)
        {
            while (begin < end && (*begin == ' ' || *begin == '\t'))
                ++begin;
            if (begin < end)
            {
                state.newLine(lineH);
            }
        }
    }
}

void _renderTextRun(WalkState& state, ImFont* font, float fontSize, ImU32 color,
                    const char* begin, const char* end)
{
    if (!begin || begin >= end || !font)
        return;

    ImFont* activeFont = _fontForStyle(state, font);
    if (!activeFont)
        return;
    float activeFontSize = fontSize;
    float yShift = 0.0f;
    if (state.style.code > 0 && state.config->codeFont && state.config->codeFontSize > 0.0f)
    {
        activeFontSize = state.config->codeFontSize;
        // Baseline alignment: when inline code is smaller than the block
        // it's embedded in (e.g. inside a heading), ImGui draws both
        // glyphs at top-y, so code ends up floating at the top instead
        // of sitting on the baseline. Shift the code glyphs down by the
        // height difference × the cap-height ratio so their baseline
        // aligns with the surrounding text.
        if (fontSize > activeFontSize)
            yShift = (fontSize - activeFontSize) * 0.80f;
    }
    ImFont* fallbackFont = (activeFontSize == state.config->bodyFontSize) ? state.config->fallbackFont : nullptr;
    if ((!state.emojiAtlas || !state.emojiAtlas->isLoaded()) && !fallbackFont)
    {
        if (yShift != 0.0f)
        {
            state.cursor.y += yShift;
            _renderPlainTextRun(state, activeFont, activeFontSize, color, begin, end);
            state.cursor.y -= yShift;
        }
        else
        {
            _renderPlainTextRun(state, activeFont, activeFontSize, color, begin, end);
        }
        return;
    }

    const char* p = begin;
    const char* textStart = begin;

    while (p < end)
    {
        uint32_t cps[16];
        int cpCount = 0;
        uint64_t emojiKey = 0;
        int emojiBytes = state.emojiAtlas && state.emojiAtlas->isLoaded()
                             ? _scanEmojiSequence(p, end, state.emojiAtlas, cps, 16, &cpCount, &emojiKey)
                             : 0;

        if (emojiBytes > 0)
        {
            if (p > textStart)
                _renderPlainTextRun(state, activeFont, activeFontSize, color, textStart, p);

            _renderEmojiGlyph(state, activeFontSize, emojiKey);
            p += emojiBytes;
            textStart = p;
        }
        else
        {
            uint32_t cp;
            int cpLen = _decodeUtf8(p, end, &cp);
            if (fallbackFont
                && !_fontHasGlyph(activeFont, activeFontSize, cp)
                && _fontHasGlyph(fallbackFont, activeFontSize, cp))
            {
                if (p > textStart)
                    _renderPlainTextRun(state, activeFont, activeFontSize, color, textStart, p);

                const char* fallbackEnd = p + cpLen;
                while (fallbackEnd < end)
                {
                    uint32_t nextCp;
                    int nextLen = _decodeUtf8(fallbackEnd, end, &nextCp);
                    if (_fontHasGlyph(activeFont, activeFontSize, nextCp)
                        || !_fontHasGlyph(fallbackFont, activeFontSize, nextCp))
                        break;
                    fallbackEnd += nextLen;
                }
                _renderPlainTextRun(state, fallbackFont, activeFontSize, color, p, fallbackEnd);
                p = fallbackEnd;
                textStart = p;
                continue;
            }
            p += cpLen;
        }
    }

    if (textStart < end)
        _renderPlainTextRun(state, activeFont, activeFontSize, color, textStart, end);
}

// =====================================================================
// Paragraph / heading spacing
// =====================================================================

void _emitBlockTopSpacing(WalkState& state, uint8_t blockType)
{
    const RenderConfig& cfg = *state.config;
    float spacing = 0.0f;
    switch (blockType)
    {
    case MD_BLOCK_H:
        // Scale the heading's top margin with its own size so H1 gets
        // more breathing room than H6, matching how a browser's default
        // stylesheet resolves heading margins (factor ~0.67em).
        spacing = _headingSizeForLevel(cfg, state.curHeadingLevel) * cfg.headingMarginTopFactor;
        break;
    case MD_BLOCK_P:
        // Paragraph top margin.  When the previous block was a heading the
        // heading's own bottom margin has already contributed a gap; adding
        // paragraphSpacing on top of that double-stacks and reads as a
        // wasteful void.  Browsers collapse these margins -- we approximate
        // by suppressing the paragraph-top on the P that directly follows.
        spacing = state.lastBlockWasHeading ? 0.0f : cfg.paragraphSpacing;
        break;
    default:
        break;
    }
    // Don't add spacing at the very top of the document.
    if (state.cursor.y > state.origin.y + 0.1f)
    {
        state.cursor.y += spacing;
    }
    // Once any block has opened we are no longer adjacent to a heading.
    state.lastBlockWasHeading = false;
}

void _emitBlockBottomSpacing(WalkState& state, uint8_t blockType)
{
    const RenderConfig& cfg = *state.config;
    float spacing = 0.0f;
    switch (blockType)
    {
    case MD_BLOCK_H:
        spacing = _headingSizeForLevel(cfg, state.curHeadingLevel) * cfg.headingMarginBottomFactor;
        state.lastBlockWasHeading = true;
        break;
    default:
        break;
    }
    state.cursor.y += spacing;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
