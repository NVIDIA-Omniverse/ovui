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

// Internal header: text-run layout + emoji/UTF-8 helpers.  Not part of the
// public include tree.  Consumed by MarkdownRenderer.cpp (walker) and
// MarkdownPaint.cpp (table cells, heading anchors, alert titles).
//
#pragma once

#include "MarkdownLayoutState.h"

#include <cstdint>
#include <string_view>

OMNIUI_NAMESPACE_OPEN_SCOPE

// ---- UTF-8 decode ---------------------------------------------------

// Decode one UTF-8 sequence at [p, end).  Returns the number of bytes
// consumed (always >= 1); writes the codepoint to *outCp.  Invalid
// sequences yield 0xFFFD and 1 byte.
int _decodeUtf8(const char* p, const char* end, uint32_t* outCp);

// ---- Emoji classification -------------------------------------------

bool _isEmojiCodepoint(uint32_t cp);
bool _isVariationSelector(uint32_t cp);
bool _isZWJ(uint32_t cp);
bool _isSkinTone(uint32_t cp);
bool _isRegionalIndicator(uint32_t cp);

// Scan a greedy emoji sequence starting at p.  Returns the byte length
// consumed (0 if no emoji glyph is in the atlas).  On success, *outKey
// is filled with the atlas key of the best-matching sequence.
int _scanEmojiSequence(const char* p, const char* end, TwemojiAtlas* atlas,
                       uint32_t* cps, int maxCp, int* cpCount, uint64_t* outKey);

// ---- Font-glyph probes ----------------------------------------------

// Returns true if `font` has a dedicated glyph for `cp` (no fallback).
// Astral-plane codepoints (cp > 0xFFFF) only succeed on ImWchar32 builds;
// on ImWchar16 builds we return false so callers fall through to their
// fallback-font path instead of short-circuiting at this probe.
bool _fontHasGlyph(ImFont* font, float fontSize, uint32_t cp);

// ---- Text emission --------------------------------------------------

// Emit a plain (non-emoji, non-fallback) text run at the current cursor.
void _renderPlainTextRun(WalkState& state, ImFont* font, float fontSize,
                         ImU32 color, const char* begin, const char* end);

// Emit a text run, automatically rerouting emoji glyphs to the twemoji
// atlas and astral/missing glyphs to the fallback font when needed.
void _renderTextRun(WalkState& state, ImFont* font, float fontSize,
                    ImU32 color, const char* begin, const char* end);

// Apply inline-style decorations (inline-code bg, strong double-draw,
// strikethrough, link underline) to a laid-out segment.  Returns true
// if the segment was clicked.  The click hit-test is guarded against
// clicks that bleed through popups / other windows.
bool _decorateSegment(WalkState& state, ImFont* font, float fontSize,
                      ImU32 color, const char* begin, const char* end,
                      ImVec2 pos, float width);

// Block-level paragraph/heading top and bottom spacing.
void _emitBlockTopSpacing(WalkState& state, uint8_t blockType);
void _emitBlockBottomSpacing(WalkState& state, uint8_t blockType);

OMNIUI_NAMESPACE_CLOSE_SCOPE
