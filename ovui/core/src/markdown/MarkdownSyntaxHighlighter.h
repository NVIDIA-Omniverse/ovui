/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Api.h>

#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

enum class MarkdownSyntaxKind : uint8_t
{
    Keyword = 0,
    String,
    Comment,
    Number,
    Punctuation,
};

struct MarkdownSyntaxToken
{
    size_t offset = 0;
    size_t length = 0;
    MarkdownSyntaxKind kind = MarkdownSyntaxKind::Keyword;
};

OMNIUI_API bool highlightMarkdownCode(std::string_view language,
                                      std::string_view code,
                                      std::vector<MarkdownSyntaxToken>& tokens);

OMNIUI_NAMESPACE_CLOSE_SCOPE
