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

#include "RenderConfig.h"

#include <omni/ui/Api.h>

#include <imgui/imgui.h>

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class ImageResolver;
class TwemojiAtlas;

/**
 * @brief A flat token in the parsed markdown stream.
 *
 * The renderer walks tokens left-to-right and emits ImGui draw commands.
 * Text payloads point into MarkdownDocument::textBuffer via offset+len.
 */
struct MdToken
{
    enum Kind : uint8_t
    {
        EnterBlock = 0,
        LeaveBlock,
        EnterSpan,
        LeaveSpan,
        Text,
        SoftBreak,
        HardBreak,
    };

    Kind kind = EnterBlock;
    uint8_t blockType = 0;   // MD_BLOCKTYPE for EnterBlock/LeaveBlock
    uint8_t spanType = 0;    // MD_SPANTYPE  for EnterSpan/LeaveSpan
    uint8_t textType = 0;    // MD_TEXTTYPE  for Text
    uint8_t level = 0;       // heading level 1..6 (only for blockType == H)
    uint32_t textOffset = 0; // index into MarkdownDocument::textBuffer
    uint32_t textLen = 0;
    uint32_t titleOffset = 0; // link/image title, when present
    uint32_t titleLen = 0;

    // Block-specific detail packed into existing token.
    // MD_BLOCK_OL EnterBlock: olStart = MD_BLOCK_OL_DETAIL::start
    // MD_BLOCK_LI EnterBlock: isTask = MD_BLOCK_LI_DETAIL::is_task
    //                          taskMark = MD_BLOCK_LI_DETAIL::task_mark
    // MD_BLOCK_TABLE EnterBlock: tableCols = col_count
    // MD_BLOCK_TH/TD EnterBlock: cellAlign (0 default, 1 left, 2 center, 3 right)
    // MD_BLOCK_CODE EnterBlock: codeLangOffset/codeLangLen point at info string
    uint32_t olStart = 1;
    uint8_t isTask = 0;
    uint8_t taskMark = 0;
    uint8_t tableCols = 0;
    uint8_t cellAlign = 0;
    uint8_t isAutolink = 0;
    uint8_t alertKind = 0; // MD_BLOCK_QUOTE EnterBlock: 1 note, 2 tip, 3 important, 4 warning, 5 caution
    uint8_t hidden = 0;    // post-parse normalization hides marker-only tokens
    uint8_t isTight = 1;   // MD_BLOCK_UL/OL: 1 if md4c marked list tight, 0 if loose
    uint32_t codeLangOffset = 0;
    uint32_t codeLangLen = 0;
    uint32_t slugOffset = 0; // MD_BLOCK_H EnterBlock: generated heading anchor slug
    uint32_t slugLen = 0;
};

struct MdHeading
{
    uint8_t level = 0;
    uint32_t textOffset = 0;
    uint32_t textLen = 0;
    uint32_t slugOffset = 0;
    uint32_t slugLen = 0;
};

/**
 * @brief Cached parse output -- token stream + concatenated text storage.
 */
struct MarkdownDocument
{
    std::string source;       // original markdown source
    std::string textBuffer;   // backing storage for token text payloads
    std::vector<MdToken> tokens;
    std::vector<MdHeading> headings;
    bool parsed = false;
};

/**
 * @brief Parse markdown text via md4c into a MarkdownDocument.
 *
 * Always succeeds (md4c is total).  On parser error, the token stream
 * may be incomplete but parsed is still set true.
 */
OMNIUI_API void parseMarkdown(const std::string& text, MarkdownDocument& outDoc);

/**
 * @brief Per-widget interaction state carried across frames.
 *
 * The renderer fills `linksThisFrame` and `hoveredLinkIdx` while drawing.
 * The widget owner reads the previous frame's hover index back via
 * `prevHoveredLinkIdx` so wrapped links highlight every visual segment.
 */
struct InteractionState
{
    // Set by widget before render; renderer compares per-link index.
    int prevHoveredLinkIdx = -1;
    // Set by widget before render; mirrors prevHoveredLinkIdx for keyboard
    // focus so wrapped links show the hover color on every visual segment
    // while focused via Tab navigation.
    int prevFocusedLinkIdx = -1;
    // Set by renderer; -1 if nothing was hovered this frame.
    int hoveredLinkIdx = -1;
    // Set by renderer; -1 if no link segment owns keyboard focus this frame.
    int focusedLinkIdx = -1;
    // Filled by renderer in source order.
    std::vector<std::string> linksThisFrame;
    // Filled in parallel with linksThisFrame. Empty when the link has no title.
    std::vector<std::string> linkTitlesThisFrame;
    // Invoked synchronously when a link is released-clicked.
    std::function<void(const std::string&)> onLinkClicked;
    // Invoked synchronously when an in-document anchor link (href "#slug") is
    // activated.  The widget uses this to drive scrollToAnchor.  Empty /
    // unset means fall back to onLinkClicked.
    std::function<void(const std::string&)> onAnchorNavigate;
    // Filled by renderer during each walk.  Maps heading slug -> y offset
    // (relative to origin) at the bottom of the heading block.  Used by
    // MarkdownWidget::scrollToAnchor to drive ImGui::SetScrollY next frame.
    std::vector<std::pair<std::string, float>> anchorOffsetsThisFrame;
};

/**
 * @brief Render a parsed document at the current ImGui cursor.
 *        Advances the cursor by the laid-out height.
 *
 * @param interaction Optional per-widget hover/click state.  May be null
 *                    for read-only / measurement contexts.
 *
 * @return The total laid-out height in pixels.
 */
OMNIUI_API float renderMarkdown(const MarkdownDocument& doc,
                                const RenderConfig& config,
                                float availableWidth,
                                InteractionState* interaction = nullptr,
                                ImageResolver* imageResolver = nullptr,
                                TwemojiAtlas* emojiAtlas = nullptr);

/**
 * @brief Measure the laid-out height for a given available width without
 *        emitting any draw commands.
 */
OMNIUI_API float measureMarkdown(const MarkdownDocument& doc, const RenderConfig& config, float availableWidth);

OMNIUI_NAMESPACE_CLOSE_SCOPE
