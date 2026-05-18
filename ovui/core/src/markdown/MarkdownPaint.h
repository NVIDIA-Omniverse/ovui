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

// Internal header: draw-only helpers (block backgrounds, glyphs, icons,
// tables, images, code blocks).  Not part of the public include tree.
//
#pragma once

#include "MarkdownLayoutState.h"

#include <cstdint>

OMNIUI_NAMESPACE_OPEN_SCOPE

// Draw one UTF-8 text segment with the font's own atlas texture pushed.
void _addTextWithFontTexture(ImDrawList* drawList, ImFont* font, float fontSize,
                             const ImVec2& pos, ImU32 color,
                             const char* begin, const char* end);

// Draw a 1-px focus ring around the rectangle [a,b] outset by 2 px so the
// ring doesn't touch glyph baselines.  Alpha is forced down to ~220 so the
// ring reads as an affordance rather than a solid border.
void _drawFocusRing(ImDrawList* drawList, ImVec2 a, ImVec2 b, ImU32 color,
                    float thickness = 1.5f);

// Render an alert icon glyph inside an axis-aligned box at `pos` with
// side length `size`.  `alertKind` is 1..5 (note / tip / important /
// warning / caution).
void _drawAlertGlyph(ImDrawList* drawList, ImVec2 pos, float size,
                     uint8_t alertKind, ImU32 color);

// Render the "Note" / "Tip" / ... alert title line.  Must be called
// immediately after the QUOTE frame is pushed.
void _renderAlertTitle(WalkState& state, ImFont* font, float baseSize,
                       uint8_t alertKind);

// Render the trailing "#" anchor link at the end of a heading.
void _renderHeadingAnchor(WalkState& state, ImFont* font, float baseSize);

// Thematic break (horizontal rule).
void _renderThematicBreak(WalkState& state);

// Fenced / indented code block (background + syntax-highlighted text +
// language chip + copy-to-clipboard button).
void _renderCodeBlock(WalkState& state, ImFont* font, float baseSize);

// Draw a list-item marker (bullet / ordered number / task checkbox).
// Returns marker-plus-gap width.
float _drawListMarker(WalkState& state, const MdToken& liTok, ImFont* font,
                      float fontSize, ImU32 color);

// Render an accumulated table at the current cursor.  Column sizing is
// delegated to MarkdownTableLayout.
void _renderTable(WalkState& state, ImFont* font, float baseSize);

// Emoji atlas glyph (called from _renderTextRun).
void _renderEmojiGlyph(WalkState& state, float fontSize, uint64_t key);

// Inline image (resolved via ImageResolver, or a placeholder box).
void _drawInlineImage(WalkState& state, ImFont* font, float baseSize);

// Table cell accumulation (called from the walker when inside a cell).
void _appendTableCellText(WalkState& state, const std::string& text);
void _appendTableCellImage(WalkState& state);

OMNIUI_NAMESPACE_CLOSE_SCOPE
