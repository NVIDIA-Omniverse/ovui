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

// Internal header: md4c decode helpers shared between MarkdownParse.cpp
// (parser) and the walker in MarkdownRenderer.cpp (which needs to resolve
// Text-token payloads at walk time).  Not part of the public include tree.
//
#pragma once

#include <omni/ui/Api.h>

#include <md4c.h>

#include <cstdint>
#include <string>
#include <string_view>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Result of decoding one Text-token payload.
 *
 * Zero-copy for MD_TEXT_NORMAL / MD_TEXT_CODE / MD_TEXT_HTML: `view` points
 * into the caller-owned source bytes and `owned` is empty.  For entity-
 * decoded and NUL-replaced text, `owned` holds the decoded bytes.
 *
 * Callers should use `as_view()` to get a `string_view` that is valid for
 * the lifetime of whichever buffer supplied the bytes (source buffer for
 * view path, this result's `owned` for decode path).
 */
struct TextForTypeResult
{
    std::string owned;       // non-empty on the decode path
    std::string_view view;   // non-empty on the zero-copy path
    bool zeroCopy = false;   // true => bytes are `view` (pointing into source)

    std::string_view as_view() const
    {
        return zeroCopy ? view : std::string_view(owned);
    }
};

// Encode `codepoint` as UTF-8, appending to `out`.  Invalid codepoints
// emit U+FFFD.
void _appendUtf8Codepoint(std::string& out, unsigned codepoint);

// True for the ASCII whitespace set (space / tab / newline / CR / FF / VT).
bool _isAsciiSpace(char c);

// Decode one text-type payload.  See TextForTypeResult docs for ownership.
// `begin`..`end` must remain live as long as any `as_view()` on the result
// is accessed in zero-copy mode.
TextForTypeResult _textForType(MD_TEXTTYPE type, const char* begin, const char* end);

OMNIUI_NAMESPACE_CLOSE_SCOPE
