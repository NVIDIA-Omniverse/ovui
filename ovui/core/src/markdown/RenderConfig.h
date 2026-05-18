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
#include <omni/ui/Types.h>

#include <imgui/imgui.h>

#include <algorithm>
#include <cstdint>
#include <functional>
#include <string_view>
#include <vector>

#include <omni/ui/Types.h>

#include "MarkdownSyntaxHighlighter.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

inline ImU32 brighten(ImU32 col, float factor)
{
    int r = std::min(255, static_cast<int>((col & 0xFF) * factor));
    int g = std::min(255, static_cast<int>(((col >> 8) & 0xFF) * factor));
    int b = std::min(255, static_cast<int>(((col >> 16) & 0xFF) * factor));
    int a = (col >> 24) & 0xFF;
    return IM_COL32(r, g, b, a);
}

inline ImU32 withAlpha(ImU32 col, uint8_t alpha)
{
    return (col & 0x00FFFFFFu) | (static_cast<ImU32>(alpha) << 24);
}

inline ImU32 warmShift(ImU32 col)
{
    int r = std::min(255, static_cast<int>(col & 0xFF) + 20);
    int g = (col >> 8) & 0xFF;
    int b = std::max(0, static_cast<int>((col >> 16) & 0xFF) - 10);
    int a = (col >> 24) & 0xFF;
    return IM_COL32(r, g, b, a);
}

enum class MarkdownTableLayoutPolicy : uint8_t
{
    Equal = 0,
    ContentFit,
    Fixed,
    Clipped,
};

/**
 * @brief Per-frame style snapshot used by the markdown renderer.
 *
 * Populated from the ovui style cascade in MarkdownWidget::_drawContent
 * before delegating to the backend.  All fields have sensible defaults
 * so the widget renders something even before styles are applied.
 */
struct RenderConfig
{
    // Body font (nullptr = use widget font).
    ImFont* bodyFont = nullptr;
    ImFont* boldFont = nullptr;
    ImFont* italicFont = nullptr;
    ImFont* fallbackFont = nullptr;
    ImFont* headingFonts[6] = {};
    float bodyFontSize = 16.0f;

    // Heading font sizes (level 1..6), in pixels.  Ratios chosen to match
    // GitHub / standard HTML rendering (2em / 1.5em / 1.17em / 1em / 0.83em /
    // 0.67em at a 16px base) so the hierarchy reads the way people expect
    // from any CommonMark-on-HTML engine.
    float headingSizes[6] = { 32.0f, 24.0f, 19.0f, 16.0f, 14.0f, 12.0f };
    ImU32 headingColors[6] = {};
    ImU32 headingAnchorColor = IM_COL32(120, 160, 220, 190);
    bool showHeadingAnchor = false;

    // Inline code / fenced code font (nullptr = use bodyFont).
    ImFont* codeFont = nullptr;
    float codeFontSize = 14.0f;

    // Colors (ABGR ImU32).
    ImU32 textColor = IM_COL32(220, 220, 220, 255);
    ImU32 headingColor = IM_COL32(255, 255, 255, 255);
    ImU32 codeBgColor = IM_COL32(40, 40, 40, 200);
    ImU32 codeTextColor = IM_COL32(230, 200, 180, 255);
    ImU32 codeBlockBgColor = IM_COL32(30, 30, 30, 220);
    ImU32 codeBlockBorderColor = IM_COL32(70, 70, 70, 255);
    ImU32 codeLangChipColor = IM_COL32(140, 140, 140, 255);
    ImU32 codeBlockCopyColor = IM_COL32(220, 220, 220, 255);
    ImU32 codeBlockCopyBgColor = IM_COL32(55, 55, 55, 230);
    ImU32 codeBlockCopyBorderColor = IM_COL32(95, 95, 95, 255);
    ImU32 codeKeywordColor = IM_COL32(102, 153, 255, 255);
    ImU32 codeStringColor = IM_COL32(210, 165, 115, 255);
    ImU32 codeCommentColor = IM_COL32(145, 155, 165, 255);
    ImU32 codeNumberColor = IM_COL32(190, 150, 255, 255);
    ImU32 codePunctuationColor = IM_COL32(200, 205, 215, 255);
    ImU32 quoteBarColor = IM_COL32(120, 120, 120, 255);
    ImU32 quoteBgColor = IM_COL32(40, 50, 60, 80);
    ImU32 quoteTextColor = IM_COL32(180, 180, 180, 255);
    ImU32 alertBarColors[5] = {
        IM_COL32(9, 105, 218, 255),   // note
        IM_COL32(26, 127, 55, 255),   // tip
        IM_COL32(130, 80, 223, 255),  // important
        IM_COL32(154, 103, 0, 255),   // warning
        IM_COL32(207, 34, 46, 255),   // caution
    };
    ImU32 alertBgColors[5] = {
        IM_COL32(9, 105, 218, 34),
        IM_COL32(26, 127, 55, 34),
        IM_COL32(130, 80, 223, 34),
        IM_COL32(154, 103, 0, 34),
        IM_COL32(207, 34, 46, 34),
    };
    ImU32 alertTextColors[5] = {
        IM_COL32(180, 205, 245, 255),
        IM_COL32(180, 225, 190, 255),
        IM_COL32(215, 195, 255, 255),
        IM_COL32(245, 220, 170, 255),
        IM_COL32(250, 190, 195, 255),
    };
    ImU32 linkColor = IM_COL32(102, 153, 255, 255);
    ImU32 linkHoverColor = IM_COL32(170, 200, 255, 255);
    // Warm off-white for italic emphasis -- distinct from both body and link.
    ImU32 italicColor = IM_COL32(240, 210, 180, 255);
    ImU32 hrColor = IM_COL32(80, 80, 80, 255);
    ImU32 tableBorderColor = IM_COL32(80, 80, 80, 255);
    ImU32 tableHeaderBg = IM_COL32(50, 50, 50, 255);
    ImU32 tableRowAltBg = IM_COL32(40, 40, 40, 255);
    ImU32 tableTextColor = IM_COL32(220, 220, 220, 255);
    ImU32 tableHeaderTextColor = IM_COL32(235, 235, 235, 255);
    ImU32 imagePlaceholderBgColor = IM_COL32(50, 50, 50, 255);
    ImU32 imagePlaceholderBorderColor = IM_COL32(90, 90, 90, 255);
    ImU32 imageAltColor = IM_COL32(160, 160, 160, 255);

    // Spacing. Defaults tuned against the streamdown reference oracle
    // (markdown/quality_harness/oracle) — measured ~30 px gap before headings and
    // ~24 px after at our 17 px body. Margin factors let H1 breathe more
    // than H6 like a real prose document.
    float paragraphSpacing = 12.0f;
    float headingSpacingBefore = 18.0f;
    float headingSpacingAfter = 10.0f;
    float headingMarginTopFactor = 0.5f;
    float headingMarginBottomFactor = 0.2f;
    float lineHeightMultiplier = 1.4f;
    float headingLineHeightMultiplier = 1.2f;
    // Tailwind Typography `prose` uses padding-left: 1.625em on ul/ol +
    // margin-left: 0.4em on marker, so marker-to-indent ≈ 2em ≈ 34 px at
    // our 17 px body.
    float listIndent = 36.0f;
    float bulletGap = 10.0f;
    float quoteBarWidth = 3.0f;
    float quoteBarPadding = 8.0f;
    float quoteIndent = 12.0f;
    float codeBlockPadding = 6.0f;
    float codeBlockBorderRadius = 4.0f;
    float codeBorderRadius = 3.0f;
    float hrThickness = 1.0f;
    float hrSpacing = 6.0f;
    // Oracle CSS: `tbody td, thead th { padding: 10px 14px }` and row
    // baseline ~24 px; match by bumping cell pad + row spacing.
    float tablePadding = 12.0f;
    float tableRowSpacing = 8.0f;
    MarkdownTableLayoutPolicy tableLayoutPolicy = MarkdownTableLayoutPolicy::Equal;
    float tableMinColumnWidth = 48.0f;
    float tableMaxColumnWidth = 420.0f;
    float tableFixedColumnWidth = 144.0f;
    float imageDefaultWidth = 200.0f;
    float imageDefaultHeight = 120.0f;

    // Native async asset provider (raw borrow; lifetime owned by widget).
    // Refreshed per frame in MarkdownWidget::_drawContent so it stays correct
    // across provider swaps even while the rest of the config is cached.
    IMarkdownAssetProvider* assetProvider = nullptr;
    uint64_t documentGeneration = 0;

    std::function<bool(std::string_view, std::string_view, std::vector<MarkdownSyntaxToken>&)> syntaxHighlighter;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
