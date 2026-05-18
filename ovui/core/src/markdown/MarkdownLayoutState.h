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

// Internal header: layout/walker state types shared between MarkdownRenderer.cpp
// (walker loop) and the extracted MarkdownParse / MarkdownText / MarkdownPaint
// translation units.  Not part of the public include tree.
//
#pragma once

#include "MarkdownRenderer.h"
#include "RenderConfig.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>

#include <md4c.h>

#include <cstdint>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class ImageResolver;
class TwemojiAtlas;

// =====================================================================
// Walker state types
// =====================================================================

struct InlineStyle
{
    int strong = 0;
    int em = 0;
    int code = 0;
    int del = 0;
};

struct ListContext
{
    uint8_t blockType = 0; // MD_BLOCK_UL or MD_BLOCK_OL
    uint32_t counter = 1;  // next index for OL items
    int depth = 0;         // 0-based nesting depth (0 = top list)
    uint8_t isTight = 1;   // loose lists get paragraph-level item spacing
};

struct QuoteFrame
{
    float xStart = 0.0f;          // left x at the moment the quote opened
    float yStart = 0.0f;          // y at the moment the quote opened
    float savedLineXStart = 0.0f; // restore on leave
    uint8_t alertKind = 0;
};

struct InlineRun
{
    enum class Kind
    {
        Text,
        Image
    };

    Kind kind = Kind::Text;
    std::string text;
    std::string src;
    std::string alt;
    std::string linkUrl;
    std::string linkTitle;
    std::string title;
    InlineStyle style;
};

struct TableCell
{
    std::string text;
    std::vector<InlineRun> runs;
    uint8_t align = 0; // 0 default, 1 left, 2 center, 3 right
    bool isHeader = false;
    bool hasRichContent = false;
};

struct WalkState
{
    const MarkdownDocument* doc = nullptr;
    const RenderConfig* config = nullptr;
    float availableWidth = 0.0f;
    ImDrawList* drawList = nullptr;                 // null = measurement pass
    ImDrawListSplitter* drawSplitter = nullptr;     // draw-channel ordering for late block backgrounds
    ImVec2 origin = ImVec2(0.0f, 0.0f);             // top-left of widget content
    ImVec2 cursor = ImVec2(0.0f, 0.0f);             // current draw position (screen coords)
    float lineHeight = 0.0f;
    float lineXStart = 0.0f; // x at start of the current visual line

    // Active block state (paragraph-like blocks).
    uint8_t curBlock = 0;
    uint8_t curHeadingLevel = 0;
    std::string curHeadingSlug;
    bool inAnyText = false;        // true while inside a P or H
    bool paragraphHasText = false; // true once real text is rendered in current P/H

    // Active inline style stack.
    InlineStyle style;

    // Active list context stack.
    std::vector<ListContext> lists;
    // Saved lineXStart values on EnterBlock LI, popped on LeaveBlock LI.
    std::vector<float> indentStack;
    // True after EnterBlock LI until the first inner block starts -- used
    // to suppress the paragraph top-spacing of the first block in an item.
    bool freshListItem = false;
    // True when an LI began collecting inline text without an explicit
    // EnterBlock P -- md4c omits P for tight lists.  We own the closing
    // newline at LeaveBlock LI.
    bool implicitItemLine = false;

    // Block-quote state.
    std::vector<QuoteFrame> quotes;

    // Code-block accumulation.
    bool inCodeBlock = false;
    bool inHtmlBlock = false;
    std::string codeBlockBuffer;
    std::string codeBlockLang;

    // Image accumulation -- alt text comes via subsequent text events.
    bool inImage = false;
    std::string imageAlt;
    std::string imageSrc;
    std::string imageTitle;

    // Table accumulation -- cells are collected during walk, rendered at
    // LeaveBlock MD_BLOCK_TABLE.
    bool inTable = false;
    bool inTableHeader = false;
    int tableColCount = 0;
    int tableCurCol = 0;
    std::vector<std::vector<TableCell>> tableRows; // rows[r][c]
    std::vector<uint8_t> tableColAlign;            // per-column alignment

    // Link state (set by SPAN_A enter/leave).
    int activeLinkIdx = -1;
    std::string activeLinkUrl;
    std::string activeLinkTitle;
    bool activeHeadingAnchor = false;
    InteractionState* interaction = nullptr;

    // ImGui item ID seeds.  These counters advance during the walk and give
    // every interactive region (link segment, copy button, image) a stable
    // identity on ImGui's focus graph.  Reset to 0 at the start of _layout.
    //
    // linkSegmentIdx: reset to 0 at EnterSpan SPAN_A, incremented per visual
    //                 segment of that link so wrapped links don't collapse
    //                 into a single InvisibleButton rect.
    // codeBlockIdSeed: incremented per EnterBlock MD_BLOCK_CODE; used as the
    //                  ImGui PushID seed for the copy button.
    // imageIdSeed: incremented per drawn image (placeholder + resolved paths).
    int linkSegmentIdx = 0;
    uint32_t codeBlockIdSeed = 0;
    uint32_t imageIdSeed = 0;

    // Set when a heading just closed; consumed by the next paragraph's
    // top-spacing logic so the heading's own bottom margin is not stacked
    // with paragraphSpacing.  Approximates HTML's margin-collapse rule for
    // adjacent block elements.
    bool lastBlockWasHeading = false;

    // Image resolver (optional — falls back to placeholder if null).
    ImageResolver* imageResolver = nullptr;

    // Twemoji atlas (optional — emoji render as tofu if null).
    TwemojiAtlas* emojiAtlas = nullptr;

    void newLine(float dy)
    {
        cursor.x = lineXStart;
        cursor.y += dy;
    }
};

// =====================================================================
// Small state-query helpers -- inline so the walker in MarkdownRenderer.cpp
// and the paint helpers in MarkdownPaint.cpp both have direct access.
// =====================================================================

inline bool _styleIsPlain(const InlineStyle& style)
{
    return style.strong == 0 && style.em == 0 && style.code == 0 && style.del == 0;
}

inline float _headingSizeForLevel(const RenderConfig& cfg, int level)
{
    if (level < 1) level = 1;
    if (level > 6) level = 6;
    return cfg.headingSizes[level - 1];
}

inline ImU32 _headingColorForLevel(const RenderConfig& cfg, int level)
{
    if (level < 1) level = 1;
    if (level > 6) level = 6;
    ImU32 color = cfg.headingColors[level - 1];
    return color != 0 ? color : cfg.headingColor;
}

inline int _alertIndex(uint8_t alertKind)
{
    if (alertKind < 1 || alertKind > 5)
        return -1;
    return static_cast<int>(alertKind) - 1;
}

inline ImU32 _quoteBarColorForFrame(const RenderConfig& cfg, const QuoteFrame& qf)
{
    int idx = _alertIndex(qf.alertKind);
    return idx >= 0 ? cfg.alertBarColors[idx] : cfg.quoteBarColor;
}

inline ImU32 _quoteBgColorForFrame(const RenderConfig& cfg, const QuoteFrame& qf)
{
    int idx = _alertIndex(qf.alertKind);
    return idx >= 0 ? cfg.alertBgColors[idx] : cfg.quoteBgColor;
}

inline ImU32 _quoteTextColorForState(const WalkState& state)
{
    if (state.quotes.empty())
        return state.config->quoteTextColor;
    int idx = _alertIndex(state.quotes.back().alertKind);
    return idx >= 0 ? state.config->alertTextColors[idx] : state.config->quoteTextColor;
}

inline ImU32 _textColorForState(const WalkState& state)
{
    if (state.curBlock == MD_BLOCK_H)
        return _headingColorForLevel(*state.config, state.curHeadingLevel);
    if (!state.quotes.empty())
        return _quoteTextColorForState(state);
    return state.config->textColor;
}

inline ImU32 _resolveTextColor(const WalkState& state, ImU32 baseColor)
{
    const InlineStyle& s = state.style;
    if (s.code > 0)
        return state.config->codeTextColor;
    if (state.activeLinkIdx >= 0)
    {
        if (state.activeHeadingAnchor)
            return state.config->headingAnchorColor;
        // Cross-frame hover wins over base link color.
        bool wasHovered = state.interaction
                          && state.interaction->prevHoveredLinkIdx == state.activeLinkIdx;
        return wasHovered ? state.config->linkHoverColor : state.config->linkColor;
    }
    if (s.em > 0)
    {
        if (state.config->italicFont)
            return baseColor;
        // Headings stay in the heading color regardless of italic -- a
        // warm-shifted italic inside an H1 reads as an accidental color
        // instead of emphasis, and HTML renderers keep italic headings
        // the same color as the surrounding heading text.
        if (state.curBlock == MD_BLOCK_H)
            return baseColor;
        // Shift the emphasis color toward a distinct warm italic hue -- avoids
        // colliding with linkColor (which also reads as "blue underlined").
        // A future italic font face can replace this; until then the color
        // shift makes italic readable as a separate inline role.
        return state.config->italicColor;
    }
    return baseColor;
}

inline ImFont* _fontForStyle(const WalkState& state, ImFont* baseFont)
{
    const RenderConfig& cfg = *state.config;
    const InlineStyle& style = state.style;
    if (style.code > 0 && cfg.codeFont)
        return cfg.codeFont;
    if (state.curBlock == MD_BLOCK_H)
    {
        int level = state.curHeadingLevel < 1 ? 1 : state.curHeadingLevel;
        if (level > 6)
            level = 6;
        if (cfg.headingFonts[level - 1])
            return cfg.headingFonts[level - 1];
    }
    if (style.strong > 0 && cfg.boldFont)
        return cfg.boldFont;
    if (style.em > 0 && cfg.italicFont)
        return cfg.italicFont;
    return baseFont;
}

inline bool _hasRealStrongFontForState(const WalkState& state)
{
    if (state.curBlock == MD_BLOCK_H)
    {
        int level = state.curHeadingLevel < 1 ? 1 : state.curHeadingLevel;
        if (level > 6)
            level = 6;
        return state.config->headingFonts[level - 1] != nullptr;
    }
    return state.config->boldFont != nullptr;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
