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

// Entry-point TU for the markdown renderer.  Owns the walker loop
// (`_walk`), the layout driver (`_layout`), and the public
// `renderMarkdown` / `measureMarkdown` wrappers.  Parsing, paint, and
// text-run layout live in their own TUs (MarkdownParse.cpp,
// MarkdownPaint.cpp, MarkdownText.cpp).
//
#include "MarkdownRenderer.h"
#include "MarkdownLayoutState.h"
#include "MarkdownPaint.h"
#include "MarkdownParse.h"
#include "MarkdownText.h"
#include "ImageResolver.h"
#include "TwemojiAtlas.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>

#include <md4c.h>

#include <algorithm>
#include <string>
#include <string_view>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

// Walk the token stream, dispatching each token to its paint helper.
// All heavy lifting lives in the helpers; this function is a dispatcher.
void _walk(WalkState& state)
{
    const auto& tokens = state.doc->tokens;
    const char* textBase = state.doc->textBuffer.data();

    ImFont* baseFont = state.config->bodyFont ? state.config->bodyFont : ImGui::GetFont();
    float baseSize = state.config->bodyFontSize;

    for (const MdToken& tok : tokens)
    {
        if (tok.hidden)
            continue;

        switch (tok.kind)
        {
        case MdToken::EnterBlock:
        {
            state.curBlock = tok.blockType;
            state.curHeadingLevel = tok.level;
            if (tok.blockType == MD_BLOCK_H && tok.slugLen > 0)
                state.curHeadingSlug.assign(textBase + tok.slugOffset, tok.slugLen);
            // Heading margin-collapse flag: only a paragraph (MD_BLOCK_P)
            // should absorb the collapse.  Other block types (quote, code,
            // table, HR, list) reset the flag so paragraphs further down do
            // not mistakenly drop their own top margin.
            if (tok.blockType != MD_BLOCK_P && tok.blockType != MD_BLOCK_H)
                state.lastBlockWasHeading = false;
            if (tok.blockType == MD_BLOCK_H || tok.blockType == MD_BLOCK_P)
            {
                if (state.freshListItem)
                {
                    // First block inside a list item shares the line with
                    // the marker -- suppress paragraph top-spacing.
                    state.freshListItem = false;
                }
                else
                {
                    _emitBlockTopSpacing(state, tok.blockType);
                }
                // A real P owns the closing newline; cancel any implicit
                // line that EnterBlock LI may have opened.
                state.implicitItemLine = false;
                state.cursor.x = state.lineXStart;
                state.lineHeight = 0.0f;
                state.inAnyText = true;
                state.paragraphHasText = false;
            }
            else if (tok.blockType == MD_BLOCK_UL || tok.blockType == MD_BLOCK_OL)
            {
                // A nested list aborts any in-progress implicit item line
                // (tight-list LI that had just emitted text).
                if (state.implicitItemLine)
                {
                    float lh = state.lineHeight > 0.0f ? state.lineHeight : baseSize;
                    state.newLine(lh);
                    state.implicitItemLine = false;
                    state.inAnyText = false;
                    state.freshListItem = false;
                }

                ListContext ctx;
                ctx.blockType = tok.blockType;
                ctx.counter = tok.blockType == MD_BLOCK_OL ? tok.olStart : 1;
                ctx.depth = static_cast<int>(state.lists.size());
                ctx.isTight = tok.isTight;
                state.lists.push_back(ctx);

                // Breathe above the first item so the list doesn't hug
                // whatever paragraph preceded it. Nested lists already
                // carry the parent item's spacing so only top-level lists
                // add the gap here.
                if (ctx.depth == 0)
                    state.cursor.y += 6.0f;

                state.freshListItem = false;
            }
            else if (tok.blockType == MD_BLOCK_LI)
            {
                state.cursor.x = state.lineXStart;

                // Oracle renders list bullets/numbers in the muted-foreground
                // colour (same token used for code-block lang labels), never
                // at the full body weight — matches Tailwind Typography's
                // `--tw-prose-bullets` default.
                ImU32 mColor = state.config->codeLangChipColor;
                ImFont* mFont = baseFont;
                float mSize = baseSize;

                float markerAdvance = _drawListMarker(state, tok, mFont, mSize, mColor);
                (void)markerAdvance;

                state.indentStack.push_back(state.lineXStart);
                state.lineXStart += state.config->listIndent;
                state.cursor.x = state.lineXStart;

                state.lineHeight = 0.0f;
                state.inAnyText = true;
                state.paragraphHasText = false;
                state.implicitItemLine = true;
                state.freshListItem = true;
            }
            else if (tok.blockType == MD_BLOCK_QUOTE)
            {
                if (state.cursor.y > state.origin.y + 0.1f)
                    state.cursor.y += state.config->paragraphSpacing;
                QuoteFrame qf;
                qf.xStart = state.lineXStart;
                qf.yStart = state.cursor.y;
                qf.savedLineXStart = state.lineXStart;
                qf.alertKind = tok.alertKind;
                state.quotes.push_back(qf);
                state.lineXStart += state.config->quoteBarWidth + state.config->quoteBarPadding;
                state.cursor.x = state.lineXStart;
                if (tok.alertKind != 0)
                    _renderAlertTitle(state, baseFont, baseSize, tok.alertKind);
            }
            else if (tok.blockType == MD_BLOCK_HR)
            {
                _renderThematicBreak(state);
            }
            else if (tok.blockType == MD_BLOCK_CODE)
            {
                state.inCodeBlock = true;
                state.codeBlockBuffer.clear();
                state.codeBlockLang.clear();
                // Advance the ImGui-ID seed for the copy button.  Every
                // encountered fenced/indented code block gets a unique
                // identity even when the text is identical.
                state.codeBlockIdSeed++;
                if (tok.codeLangLen > 0)
                    state.codeBlockLang.assign(textBase + tok.codeLangOffset, tok.codeLangLen);
            }
            else if (tok.blockType == MD_BLOCK_HTML)
            {
                state.inHtmlBlock = true;
                state.codeBlockBuffer.clear();
                state.codeBlockLang = "html";
            }
            else if (tok.blockType == MD_BLOCK_TABLE)
            {
                state.inTable = true;
                state.tableColCount = tok.tableCols;
                state.tableCurCol = 0;
                state.tableRows.clear();
                state.tableColAlign.assign(tok.tableCols, 0);
            }
            else if (tok.blockType == MD_BLOCK_THEAD)
            {
                state.inTableHeader = true;
            }
            else if (tok.blockType == MD_BLOCK_TR)
            {
                state.tableCurCol = 0;
                state.tableRows.emplace_back();
                if (state.tableColCount > 0)
                    state.tableRows.back().resize(state.tableColCount);
            }
            else if (tok.blockType == MD_BLOCK_TH || tok.blockType == MD_BLOCK_TD)
            {
                if (state.inTable && !state.tableRows.empty())
                {
                    int c = state.tableCurCol;
                    if (c < (int)state.tableRows.back().size())
                    {
                        state.tableRows.back()[c].isHeader = state.inTableHeader;
                        state.tableRows.back()[c].align = tok.cellAlign;
                        if (state.inTableHeader && c < (int)state.tableColAlign.size()
                            && state.tableColAlign[c] == 0)
                        {
                            state.tableColAlign[c] = tok.cellAlign;
                        }
                    }
                }
                state.inAnyText = true;
            }
            break;
        }
        case MdToken::LeaveBlock:
        {
            if (tok.blockType == MD_BLOCK_H || tok.blockType == MD_BLOCK_P)
            {
                if (tok.blockType == MD_BLOCK_H)
                    _renderHeadingAnchor(state, baseFont, baseSize);
                float lh = state.lineHeight > 0.0f ? state.lineHeight : baseSize;
                state.newLine(lh);
                _emitBlockBottomSpacing(state, tok.blockType);
                state.inAnyText = false;
                if (tok.blockType == MD_BLOCK_H)
                {
                    // Record the y offset of the heading (relative to
                    // the widget's origin) so scrollToAnchor can drive
                    // ImGui::SetScrollY to jump the viewport here.  We
                    // stash qf.yStart-style metadata via the cursor at
                    // LeaveBlock time because the actual heading height
                    // is only known now.
                    if (state.interaction && !state.curHeadingSlug.empty())
                    {
                        float y = 0.0f;  // Heading top relative to origin.
                        // We approximate "top of heading" via cursor.y minus
                        // what we just advanced (lh + bottom spacing).  This
                        // is fine for scroll-targeting: even if the cursor
                        // has moved past the heading, the user will still
                        // see the heading near the top of the scroll region.
                        y = state.cursor.y - state.origin.y;
                        // Subtract the heading's own line height + bottom
                        // spacing so the saved offset points at the top of
                        // the heading rather than the start of the next
                        // block.
                        float hSize = _headingSizeForLevel(*state.config, state.curHeadingLevel);
                        y -= hSize + state.config->headingSpacingAfter;
                        if (y < 0.0f) y = 0.0f;
                        state.interaction->anchorOffsetsThisFrame.emplace_back(
                            state.curHeadingSlug, y);
                    }
                    state.curHeadingSlug.clear();
                }
            }
            else if (tok.blockType == MD_BLOCK_UL || tok.blockType == MD_BLOCK_OL)
            {
                if (!state.lists.empty())
                    state.lists.pop_back();
                if (state.lists.empty())
                {
                    state.cursor.y += state.config->paragraphSpacing;
                }
            }
            else if (tok.blockType == MD_BLOCK_LI)
            {
                if (state.implicitItemLine)
                {
                    float lh = state.lineHeight > 0.0f ? state.lineHeight : baseSize;
                    state.newLine(lh);
                    state.implicitItemLine = false;
                    state.inAnyText = false;
                }
                state.freshListItem = false;

                // Item spacing. Oracle (Tailwind prose) renders tight
                // lists with ~18-22 px between items and loose lists with
                // ~30 px. Nested lists get less breathing room than
                // top-level ones.
                if (!state.lists.empty())
                {
                    float gap = state.lists.back().depth == 0 ? 18.0f : 8.0f;
                    state.cursor.y += gap;
                    if (!state.lists.back().isTight)
                        state.cursor.y += state.config->paragraphSpacing;
                }

                if (!state.indentStack.empty())
                {
                    state.lineXStart = state.indentStack.back();
                    state.indentStack.pop_back();
                    state.cursor.x = state.lineXStart;
                }
                if (!state.lists.empty() && state.lists.back().blockType == MD_BLOCK_OL)
                {
                    state.lists.back().counter++;
                }
            }
            else if (tok.blockType == MD_BLOCK_QUOTE)
            {
                if (!state.quotes.empty())
                {
                    QuoteFrame qf = state.quotes.back();
                    state.quotes.pop_back();
                    state.lineXStart = qf.savedLineXStart;
                    float yEnd = state.cursor.y;
                    if (state.drawList)
                    {
                        const RenderConfig& cfg = *state.config;
                        ImU32 quoteBg = _quoteBgColorForFrame(cfg, qf);
                        ImU32 quoteBar = _quoteBarColorForFrame(cfg, qf);
                        if (state.drawSplitter)
                            state.drawSplitter->SetCurrentChannel(state.drawList, 0);
                        if ((quoteBg & 0xFF000000u) != 0)
                        {
                            state.drawList->AddRectFilled(
                                ImVec2(qf.xStart, qf.yStart),
                                ImVec2(qf.xStart + state.availableWidth, yEnd),
                                quoteBg, 2.0f);
                        }
                        state.drawList->AddRectFilled(
                            ImVec2(qf.xStart, qf.yStart),
                            ImVec2(qf.xStart + cfg.quoteBarWidth, yEnd),
                            quoteBar);
                        if (state.drawSplitter)
                            state.drawSplitter->SetCurrentChannel(state.drawList, 1);
                    }
                    state.cursor.x = state.lineXStart;
                    if (state.quotes.empty())
                        state.cursor.y += state.config->paragraphSpacing;
                }
            }
            else if (tok.blockType == MD_BLOCK_CODE)
            {
                state.inCodeBlock = false;
                _renderCodeBlock(state, baseFont, baseSize);
            }
            else if (tok.blockType == MD_BLOCK_HTML)
            {
                state.inHtmlBlock = false;
                _renderCodeBlock(state, baseFont, baseSize);
            }
            else if (tok.blockType == MD_BLOCK_TABLE)
            {
                _renderTable(state, baseFont, baseSize);
                state.inTable = false;
                state.tableRows.clear();
                state.tableColAlign.clear();
                state.tableColCount = 0;
            }
            else if (tok.blockType == MD_BLOCK_THEAD)
            {
                state.inTableHeader = false;
            }
            else if (tok.blockType == MD_BLOCK_TR)
            {
                // Nothing -- row already pushed at TR enter.
            }
            else if (tok.blockType == MD_BLOCK_TH || tok.blockType == MD_BLOCK_TD)
            {
                state.tableCurCol++;
                state.inAnyText = false;
            }
            state.curBlock = 0;
            state.curHeadingLevel = 0;
            break;
        }
        case MdToken::Text:
        {
            const char* begin = textBase + tok.textOffset;
            const char* end = begin + tok.textLen;

            // Zero-copy path for MD_TEXT_NORMAL / MD_TEXT_CODE / MD_TEXT_HTML:
            // those textType values require no decoding, so _textForType
            // returns a string_view into doc.textBuffer directly.
            TextForTypeResult decoded = _textForType(static_cast<MD_TEXTTYPE>(tok.textType), begin, end);
            std::string_view text = decoded.as_view();

            // Verbatim block accumulation takes priority over rendering.
            if (state.inCodeBlock || state.inHtmlBlock)
            {
                state.codeBlockBuffer.append(text.data(), text.size());
                break;
            }
            // Image alt accumulation.
            if (state.inImage)
            {
                state.imageAlt.append(text.data(), text.size());
                break;
            }
            // Table cell accumulation: store both text fallback and rich inline runs.
            if (state.inTable && !state.tableRows.empty())
            {
                _appendTableCellText(state, std::string(text));
                break;
            }
            if (!state.inAnyText)
                break;
            state.paragraphHasText = true;

            float fontSize = baseSize;
            ImU32 color = _textColorForState(state);
            if (state.curBlock == MD_BLOCK_H)
            {
                fontSize = _headingSizeForLevel(*state.config, state.curHeadingLevel);
            }
            _renderTextRun(state, baseFont, fontSize, color, text.data(), text.data() + text.size());
            break;
        }
        case MdToken::SoftBreak:
        {
            if (state.inCodeBlock || state.inHtmlBlock)
            {
                state.codeBlockBuffer.push_back('\n');
                break;
            }
            if (state.inImage) { state.imageAlt.push_back(' '); break; }
            if (state.inTable && !state.tableRows.empty())
            {
                _appendTableCellText(state, " ");
                break;
            }
            // Treat as a single space (CommonMark default).
            if (state.inAnyText)
            {
                const char space = ' ';
                float fontSize = state.curBlock == MD_BLOCK_H
                                     ? _headingSizeForLevel(*state.config, state.curHeadingLevel)
                                     : baseSize;
                ImU32 color = _textColorForState(state);
                _renderTextRun(state, baseFont, fontSize, color, &space, &space + 1);
            }
            break;
        }
        case MdToken::HardBreak:
        {
            if (state.inCodeBlock || state.inHtmlBlock) { state.codeBlockBuffer.push_back('\n'); break; }
            if (state.inImage)     { state.imageAlt.push_back(' '); break; }
            if (state.inTable)     { break; }
            float fontSize = state.curBlock == MD_BLOCK_H
                                 ? _headingSizeForLevel(*state.config, state.curHeadingLevel)
                                 : baseSize;
            state.newLine(fontSize);
            break;
        }
        case MdToken::EnterSpan:
        {
            switch (tok.spanType)
            {
            case MD_SPAN_STRONG: state.style.strong++; break;
            case MD_SPAN_EM:     state.style.em++;     break;
            case MD_SPAN_CODE:   state.style.code++;   break;
            case MD_SPAN_DEL:    state.style.del++;    break;
            case MD_SPAN_A:
            {
                std::string url;
                if (tok.textLen > 0)
                    url.assign(textBase + tok.textOffset, tok.textLen);
                std::string title;
                if (tok.titleLen > 0)
                    title.assign(textBase + tok.titleOffset, tok.titleLen);
                state.activeLinkUrl = url;
                state.activeLinkTitle = title;
                // Reset the per-link segment counter so wrapped segments of
                // this link get IDs "md.link.N.s0", "md.link.N.s1", ...
                state.linkSegmentIdx = 0;
                if (state.inTable)
                {
                    state.activeLinkIdx = -1;
                }
                else if (state.interaction)
                {
                    state.interaction->linksThisFrame.push_back(url);
                    state.interaction->linkTitlesThisFrame.push_back(title);
                    state.activeLinkIdx = (int)state.interaction->linksThisFrame.size() - 1;
                }
                else
                {
                    // No interaction state -- still set a flag so the
                    // underline draws (just no hit-testing).
                    state.activeLinkIdx = 0;
                }
                break;
            }
            case MD_SPAN_IMG:
            {
                state.inImage = true;
                state.imageAlt.clear();
                state.imageSrc.clear();
                state.imageTitle.clear();
                if (tok.textLen > 0)
                    state.imageSrc.assign(textBase + tok.textOffset, tok.textLen);
                if (tok.titleLen > 0)
                    state.imageTitle.assign(textBase + tok.titleOffset, tok.titleLen);
                break;
            }
            default: break;
            }
            break;
        }
        case MdToken::LeaveSpan:
        {
            switch (tok.spanType)
            {
            case MD_SPAN_STRONG: if (state.style.strong > 0) state.style.strong--; break;
            case MD_SPAN_EM:     if (state.style.em > 0)     state.style.em--;     break;
            case MD_SPAN_CODE:   if (state.style.code > 0)   state.style.code--;   break;
            case MD_SPAN_DEL:    if (state.style.del > 0)    state.style.del--;    break;
            case MD_SPAN_A:      state.activeLinkIdx = -1; state.activeLinkUrl.clear(); state.activeLinkTitle.clear(); state.linkSegmentIdx = 0; break;
            case MD_SPAN_IMG:
            {
                if (state.inTable)
                {
                    _appendTableCellImage(state);
                }
                else
                {
                    _drawInlineImage(state, baseFont, baseSize);
                }
                state.inImage = false;
                state.imageTitle.clear();
                break;
            }
            default: break;
            }
            break;
        }
        }
    }
}

float _layout(const MarkdownDocument& doc, const RenderConfig& config, float availableWidth,
              ImDrawList* drawList, ImVec2 startPos, InteractionState* interaction,
              ImageResolver* imageResolver, TwemojiAtlas* emojiAtlas)
{
    if (!doc.parsed || doc.tokens.empty())
    {
        return 0.0f;
    }

    WalkState state;
    state.doc = &doc;
    state.config = &config;
    state.availableWidth = availableWidth > 0.0f ? availableWidth : 1.0f;
    state.drawList = drawList;
    state.origin = startPos;
    state.cursor = startPos;
    state.lineXStart = startPos.x;
    state.lineHeight = 0.0f;
    state.interaction = interaction;
    state.imageResolver = imageResolver;
    state.emojiAtlas = emojiAtlas;
    state.linkSegmentIdx = 0;
    state.codeBlockIdSeed = 0;
    state.imageIdSeed = 0;
    if (interaction)
    {
        interaction->linksThisFrame.clear();
        interaction->linkTitlesThisFrame.clear();
        interaction->hoveredLinkIdx = -1;
        interaction->focusedLinkIdx = -1;
        interaction->anchorOffsetsThisFrame.clear();
    }

    ImDrawListSplitter splitter;
    bool splitDrawList = drawList != nullptr;
    if (splitDrawList)
    {
        splitter.Split(drawList, 2);
        splitter.SetCurrentChannel(drawList, 1);
        state.drawSplitter = &splitter;
    }

    _walk(state);

    if (splitDrawList)
    {
        splitter.SetCurrentChannel(drawList, 1);
        splitter.Merge(drawList);
        state.drawSplitter = nullptr;
    }
    return state.cursor.y - startPos.y;
}

} // namespace

float renderMarkdown(const MarkdownDocument& doc, const RenderConfig& config, float availableWidth,
                     InteractionState* interaction, ImageResolver* imageResolver, TwemojiAtlas* emojiAtlas)
{
    ImDrawList* drawList = ImGui::GetWindowDrawList();
    ImVec2 startPos = ImGui::GetCursorScreenPos();
    float h = _layout(doc, config, availableWidth, drawList, startPos, interaction, imageResolver, emojiAtlas);
    ImGui::Dummy(ImVec2(availableWidth, h));
    return h;
}

float measureMarkdown(const MarkdownDocument& doc, const RenderConfig& config, float availableWidth)
{
    return _layout(doc, config, availableWidth, nullptr, ImVec2(0.0f, 0.0f), nullptr, nullptr, nullptr);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
