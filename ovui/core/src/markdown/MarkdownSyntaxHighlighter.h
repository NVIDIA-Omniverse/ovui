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
