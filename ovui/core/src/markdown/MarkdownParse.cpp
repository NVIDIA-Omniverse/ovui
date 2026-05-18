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

// md4c callbacks -> MarkdownDocument token stream.  Parsing is kept in a
// separate TU so compile times scale linearly with renderer changes.
//
#include "MarkdownParse.h"
#include "MarkdownRenderer.h"


extern "C" {
#include <entity.h>
}

#include <cctype>
#include <cstring>
#include <string>
#include <string_view>
#include <unordered_map>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

struct ParseCtx
{
    MarkdownDocument* doc;
};

uint32_t _appendText(MarkdownDocument* doc, const MD_CHAR* text, MD_SIZE size)
{
    uint32_t offset = static_cast<uint32_t>(doc->textBuffer.size());
    doc->textBuffer.append(text, size);
    return offset;
}

uint32_t _appendString(MarkdownDocument* doc, const std::string& text)
{
    uint32_t offset = static_cast<uint32_t>(doc->textBuffer.size());
    doc->textBuffer.append(text);
    return offset;
}

int _hexValue(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return 10 + c - 'a';
    if (c >= 'A' && c <= 'F')
        return 10 + c - 'A';
    return -1;
}

std::string _decodeEntityText(const char* begin, const char* end)
{
    std::string out;
    if (!begin || begin >= end)
        return out;

    size_t len = static_cast<size_t>(end - begin);
    if (len > 3 && begin[0] == '&' && begin[1] == '#' && end[-1] == ';')
    {
        unsigned codepoint = 0;
        size_t i = 2;
        bool hex = false;
        if (i < len && (begin[i] == 'x' || begin[i] == 'X'))
        {
            hex = true;
            ++i;
        }

        bool valid = i < len - 1;
        for (; i < len - 1 && valid; ++i)
        {
            int digit = hex ? _hexValue(begin[i])
                            : (std::isdigit(static_cast<unsigned char>(begin[i])) ? begin[i] - '0' : -1);
            if (digit < 0)
            {
                valid = false;
                break;
            }
            codepoint = codepoint * (hex ? 16u : 10u) + static_cast<unsigned>(digit);
            if (codepoint > 0x110000u)
                break;
        }

        if (valid)
        {
            _appendUtf8Codepoint(out, codepoint);
            return out;
        }
    }

    const ENTITY* ent = entity_lookup(begin, len);
    if (ent)
    {
        _appendUtf8Codepoint(out, ent->codepoints[0]);
        if (ent->codepoints[1])
            _appendUtf8Codepoint(out, ent->codepoints[1]);
        return out;
    }

    out.assign(begin, end);
    return out;
}

bool _appendAttribute(MarkdownDocument* doc, const MD_ATTRIBUTE& attr, uint32_t* offset, uint32_t* len)
{
    if (!attr.text || attr.size == 0)
        return false;

    std::string text;
    if (attr.substr_offsets && attr.substr_types)
    {
        for (int i = 0; attr.substr_offsets[i] < attr.size; ++i)
        {
            MD_OFFSET off = attr.substr_offsets[i];
            MD_SIZE size = attr.substr_offsets[i + 1] - off;
            const char* begin = attr.text + off;
            TextForTypeResult r = _textForType(attr.substr_types[i], begin, begin + size);
            std::string_view sv = r.as_view();
            text.append(sv.data(), sv.size());
        }
    }
    else
    {
        text.assign(attr.text, attr.size);
    }

    *offset = _appendString(doc, text);
    *len = static_cast<uint32_t>(text.size());
    return true;
}

int _enterBlock(MD_BLOCKTYPE type, void* detail, void* userdata)
{
    auto* ctx = static_cast<ParseCtx*>(userdata);
    MdToken tok;
    tok.kind = MdToken::EnterBlock;
    tok.blockType = static_cast<uint8_t>(type);
    if (type == MD_BLOCK_H && detail)
    {
        auto* h = static_cast<MD_BLOCK_H_DETAIL*>(detail);
        tok.level = static_cast<uint8_t>(h->level);
    }
    else if (type == MD_BLOCK_OL && detail)
    {
        auto* ol = static_cast<MD_BLOCK_OL_DETAIL*>(detail);
        tok.olStart = ol->start;
        tok.isTight = ol->is_tight ? 1 : 0;
    }
    else if (type == MD_BLOCK_UL && detail)
    {
        auto* ul = static_cast<MD_BLOCK_UL_DETAIL*>(detail);
        tok.isTight = ul->is_tight ? 1 : 0;
    }
    else if (type == MD_BLOCK_LI && detail)
    {
        auto* li = static_cast<MD_BLOCK_LI_DETAIL*>(detail);
        tok.isTask = li->is_task ? 1 : 0;
        tok.taskMark = static_cast<uint8_t>(li->task_mark);
    }
    else if (type == MD_BLOCK_TABLE && detail)
    {
        auto* t = static_cast<MD_BLOCK_TABLE_DETAIL*>(detail);
        // md4c reports col_count up to 64 in practice; clamp into a byte for storage.
        unsigned cc = t->col_count > 255u ? 255u : t->col_count;
        tok.tableCols = static_cast<uint8_t>(cc);
    }
    else if ((type == MD_BLOCK_TH || type == MD_BLOCK_TD) && detail)
    {
        auto* td = static_cast<MD_BLOCK_TD_DETAIL*>(detail);
        tok.cellAlign = static_cast<uint8_t>(td->align);
    }
    else if (type == MD_BLOCK_CODE && detail)
    {
        auto* c = static_cast<MD_BLOCK_CODE_DETAIL*>(detail);
        if (c->lang.text && c->lang.size > 0)
        {
            tok.codeLangOffset = _appendText(ctx->doc, c->lang.text, c->lang.size);
            tok.codeLangLen = c->lang.size;
        }
    }
    ctx->doc->tokens.push_back(tok);
    return 0;
}

int _leaveBlock(MD_BLOCKTYPE type, void* /*detail*/, void* userdata)
{
    auto* ctx = static_cast<ParseCtx*>(userdata);
    MdToken tok;
    tok.kind = MdToken::LeaveBlock;
    tok.blockType = static_cast<uint8_t>(type);
    ctx->doc->tokens.push_back(tok);
    return 0;
}

int _enterSpan(MD_SPANTYPE type, void* detail, void* userdata)
{
    auto* ctx = static_cast<ParseCtx*>(userdata);
    MdToken tok;
    tok.kind = MdToken::EnterSpan;
    tok.spanType = static_cast<uint8_t>(type);
    if (type == MD_SPAN_A && detail)
    {
        auto* a = static_cast<MD_SPAN_A_DETAIL*>(detail);
        _appendAttribute(ctx->doc, a->href, &tok.textOffset, &tok.textLen);
        _appendAttribute(ctx->doc, a->title, &tok.titleOffset, &tok.titleLen);
        tok.isAutolink = a->is_autolink ? 1 : 0;
    }
    else if (type == MD_SPAN_IMG && detail)
    {
        auto* img = static_cast<MD_SPAN_IMG_DETAIL*>(detail);
        _appendAttribute(ctx->doc, img->src, &tok.textOffset, &tok.textLen);
        _appendAttribute(ctx->doc, img->title, &tok.titleOffset, &tok.titleLen);
    }
    ctx->doc->tokens.push_back(tok);
    return 0;
}

int _leaveSpan(MD_SPANTYPE type, void* /*detail*/, void* userdata)
{
    auto* ctx = static_cast<ParseCtx*>(userdata);
    MdToken tok;
    tok.kind = MdToken::LeaveSpan;
    tok.spanType = static_cast<uint8_t>(type);
    ctx->doc->tokens.push_back(tok);
    return 0;
}

int _text(MD_TEXTTYPE type, const MD_CHAR* text, MD_SIZE size, void* userdata)
{
    auto* ctx = static_cast<ParseCtx*>(userdata);
    if (type == MD_TEXT_SOFTBR)
    {
        MdToken tok;
        tok.kind = MdToken::SoftBreak;
        ctx->doc->tokens.push_back(tok);
        return 0;
    }
    if (type == MD_TEXT_BR)
    {
        MdToken tok;
        tok.kind = MdToken::HardBreak;
        ctx->doc->tokens.push_back(tok);
        return 0;
    }

    MdToken tok;
    tok.kind = MdToken::Text;
    tok.textType = static_cast<uint8_t>(type);
    tok.textOffset = _appendText(ctx->doc, text, size);
    tok.textLen = size;
    ctx->doc->tokens.push_back(tok);
    return 0;
}

std::string _trimAndCollapseAsciiWhitespace(const std::string& input)
{
    std::string out;
    bool pendingSpace = false;
    bool wrote = false;
    for (char c : input)
    {
        if (_isAsciiSpace(c))
        {
            pendingSpace = wrote;
            continue;
        }
        if (pendingSpace && !out.empty())
            out.push_back(' ');
        out.push_back(c);
        wrote = true;
        pendingSpace = false;
    }
    return out;
}

std::string _baseSlugForHeading(const std::string& headingText)
{
    std::string slug;
    bool pendingDash = false;

    for (unsigned char uc : headingText)
    {
        char c = static_cast<char>(uc);
        if (uc < 0x80)
        {
            if (std::isalnum(uc))
            {
                if (pendingDash && !slug.empty())
                    slug.push_back('-');
                slug.push_back(static_cast<char>(std::tolower(uc)));
                pendingDash = false;
            }
            else if (_isAsciiSpace(c))
            {
                if (!slug.empty())
                    pendingDash = true;
            }
            // GitHub-style anchors remove ASCII punctuation.
            continue;
        }

        if (pendingDash && !slug.empty())
            slug.push_back('-');
        slug.push_back(c);
        pendingDash = false;
    }

    if (slug.empty())
        slug = "section";
    return slug;
}

std::string _uniqueHeadingSlug(const std::string& base,
                               std::unordered_map<std::string, int>& baseCounts,
                               std::unordered_map<std::string, bool>& usedSlugs)
{
    int& nextSuffix = baseCounts[base];
    std::string slug = nextSuffix == 0 ? base : base + "-" + std::to_string(nextSuffix);
    ++nextSuffix;
    while (usedSlugs.find(slug) != usedSlugs.end())
    {
        slug = base + "-" + std::to_string(nextSuffix);
        ++nextSuffix;
    }
    usedSlugs[slug] = true;
    return slug;
}

std::string _tokenText(const MarkdownDocument& doc, const MdToken& tok)
{
    if (tok.kind != MdToken::Text || tok.textLen == 0)
        return {};
    const char* begin = doc.textBuffer.data() + tok.textOffset;
    TextForTypeResult r = _textForType(static_cast<MD_TEXTTYPE>(tok.textType), begin, begin + tok.textLen);
    std::string_view sv = r.as_view();
    return std::string(sv.data(), sv.size());
}

void _normalizeHeadings(MarkdownDocument& doc)
{
    doc.headings.clear();
    std::unordered_map<std::string, int> baseCounts;
    std::unordered_map<std::string, bool> usedSlugs;

    for (size_t i = 0; i < doc.tokens.size(); ++i)
    {
        MdToken& tok = doc.tokens[i];
        if (tok.kind != MdToken::EnterBlock || tok.blockType != MD_BLOCK_H)
            continue;

        std::string plain;
        for (size_t j = i + 1; j < doc.tokens.size(); ++j)
        {
            const MdToken& inner = doc.tokens[j];
            if (inner.kind == MdToken::LeaveBlock && inner.blockType == MD_BLOCK_H)
                break;
            if (inner.kind == MdToken::Text)
                plain.append(_tokenText(doc, inner));
            else if (inner.kind == MdToken::SoftBreak || inner.kind == MdToken::HardBreak)
                plain.push_back(' ');
        }

        plain = _trimAndCollapseAsciiWhitespace(plain);
        std::string slug = _uniqueHeadingSlug(_baseSlugForHeading(plain), baseCounts, usedSlugs);

        tok.slugOffset = _appendString(&doc, slug);
        tok.slugLen = static_cast<uint32_t>(slug.size());

        MdHeading h;
        h.level = tok.level;
        h.textOffset = _appendString(&doc, plain);
        h.textLen = static_cast<uint32_t>(plain.size());
        h.slugOffset = tok.slugOffset;
        h.slugLen = tok.slugLen;
        doc.headings.push_back(h);
    }
}

uint8_t _parseAlertMarker(const std::string& text, size_t* markerEnd)
{
    size_t pos = 0;
    while (pos < text.size() && _isAsciiSpace(text[pos]))
        ++pos;

    struct AlertDef
    {
        const char* marker;
        uint8_t kind;
    };
    static constexpr AlertDef kAlerts[] = {
        { "[!NOTE]", 1 },
        { "[!TIP]", 2 },
        { "[!IMPORTANT]", 3 },
        { "[!WARNING]", 4 },
        { "[!CAUTION]", 5 },
    };

    for (const AlertDef& def : kAlerts)
    {
        size_t len = std::strlen(def.marker);
        if (text.size() - pos < len)
            continue;
        bool match = true;
        for (size_t i = 0; i < len; ++i)
        {
            unsigned char a = static_cast<unsigned char>(text[pos + i]);
            unsigned char b = static_cast<unsigned char>(def.marker[i]);
            if (std::toupper(a) != std::toupper(b))
            {
                match = false;
                break;
            }
        }
        if (match)
        {
            *markerEnd = pos + len;
            return def.kind;
        }
    }
    return 0;
}

void _hideAlertMarkerText(MarkdownDocument& doc, size_t markerIdx, size_t markerEnd, const std::string& decodedText)
{
    MdToken& markerTok = doc.tokens[markerIdx];
    size_t suffixStart = markerEnd;
    while (suffixStart < decodedText.size() && _isAsciiSpace(decodedText[suffixStart]))
        ++suffixStart;

    if (suffixStart < decodedText.size())
    {
        std::string suffix = decodedText.substr(suffixStart);
        markerTok.textOffset = _appendString(&doc, suffix);
        markerTok.textLen = static_cast<uint32_t>(suffix.size());
        markerTok.textType = static_cast<uint8_t>(MD_TEXT_NORMAL);
        return;
    }

    markerTok.hidden = 1;
    if (markerIdx + 1 < doc.tokens.size()
        && (doc.tokens[markerIdx + 1].kind == MdToken::SoftBreak
            || doc.tokens[markerIdx + 1].kind == MdToken::HardBreak))
    {
        doc.tokens[markerIdx + 1].hidden = 1;
    }
}

void _normalizeAlerts(MarkdownDocument& doc)
{
    for (size_t i = 0; i < doc.tokens.size(); ++i)
    {
        MdToken& quoteTok = doc.tokens[i];
        if (quoteTok.kind != MdToken::EnterBlock || quoteTok.blockType != MD_BLOCK_QUOTE)
            continue;

        int quoteDepth = 1;
        for (size_t j = i + 1; j < doc.tokens.size(); ++j)
        {
            const MdToken& inner = doc.tokens[j];
            if (inner.kind == MdToken::EnterBlock && inner.blockType == MD_BLOCK_QUOTE)
            {
                ++quoteDepth;
                continue;
            }
            if (inner.kind == MdToken::LeaveBlock && inner.blockType == MD_BLOCK_QUOTE)
            {
                --quoteDepth;
                if (quoteDepth == 0)
                    break;
                continue;
            }
            if (quoteDepth != 1)
                continue;

            if (inner.kind == MdToken::EnterBlock || inner.kind == MdToken::EnterSpan || inner.kind == MdToken::LeaveSpan)
                continue;
            if (inner.kind == MdToken::SoftBreak || inner.kind == MdToken::HardBreak)
                continue;
            if (inner.kind != MdToken::Text)
                break;

            std::string decoded = _tokenText(doc, inner);
            size_t markerEnd = 0;
            uint8_t kind = _parseAlertMarker(decoded, &markerEnd);
            if (kind != 0)
            {
                quoteTok.alertKind = kind;
                _hideAlertMarkerText(doc, j, markerEnd, decoded);
            }
            break;
        }
    }
}

void _normalizeDocument(MarkdownDocument& doc)
{
    _normalizeHeadings(doc);
    _normalizeAlerts(doc);
}

} // namespace

// ---------------------------------------------------------------------
// Public API exposed via MarkdownParse.h
// ---------------------------------------------------------------------

void _appendUtf8Codepoint(std::string& out, unsigned codepoint)
{
    static const char kReplacement[] = "\xEF\xBF\xBD";
    if (codepoint == 0 || codepoint > 0x10FFFFu || (codepoint >= 0xD800u && codepoint <= 0xDFFFu))
    {
        out.append(kReplacement, sizeof(kReplacement) - 1);
        return;
    }

    if (codepoint <= 0x7Fu)
    {
        out.push_back(static_cast<char>(codepoint));
    }
    else if (codepoint <= 0x7FFu)
    {
        out.push_back(static_cast<char>(0xC0u | ((codepoint >> 6) & 0x1Fu)));
        out.push_back(static_cast<char>(0x80u | (codepoint & 0x3Fu)));
    }
    else if (codepoint <= 0xFFFFu)
    {
        out.push_back(static_cast<char>(0xE0u | ((codepoint >> 12) & 0x0Fu)));
        out.push_back(static_cast<char>(0x80u | ((codepoint >> 6) & 0x3Fu)));
        out.push_back(static_cast<char>(0x80u | (codepoint & 0x3Fu)));
    }
    else
    {
        out.push_back(static_cast<char>(0xF0u | ((codepoint >> 18) & 0x07u)));
        out.push_back(static_cast<char>(0x80u | ((codepoint >> 12) & 0x3Fu)));
        out.push_back(static_cast<char>(0x80u | ((codepoint >> 6) & 0x3Fu)));
        out.push_back(static_cast<char>(0x80u | (codepoint & 0x3Fu)));
    }
}

bool _isAsciiSpace(char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}

// Zero-copy where possible: return a string_view into the source for the
// common MD_TEXT_NORMAL / MD_TEXT_CODE / MD_TEXT_HTML cases.  Only allocate
// when the type actually requires decoding (entities, NUL replacement).
TextForTypeResult _textForType(MD_TEXTTYPE type, const char* begin, const char* end)
{
    if (type == MD_TEXT_ENTITY)
    {
        std::string s = _decodeEntityText(begin, end);
        return TextForTypeResult{ std::move(s), std::string_view(), false };
    }
    if (type == MD_TEXT_NULLCHAR)
    {
        return TextForTypeResult{ std::string("\xEF\xBF\xBD", 3), std::string_view(), false };
    }
    // Zero-copy: the source bytes are already the rendered text.
    return TextForTypeResult{ std::string(), std::string_view(begin, static_cast<size_t>(end - begin)), true };
}

// ---------------------------------------------------------------------

void parseMarkdown(const std::string& text, MarkdownDocument& outDoc)
{
    outDoc.source = text;
    outDoc.textBuffer.clear();
    outDoc.tokens.clear();
    outDoc.headings.clear();
    outDoc.parsed = true;

    if (text.empty())
    {
        return;
    }

    ParseCtx ctx{ &outDoc };

    MD_PARSER parser{};
    parser.abi_version = 0;
    parser.flags = MD_DIALECT_GITHUB | MD_FLAG_COLLAPSEWHITESPACE;
    parser.enter_block = _enterBlock;
    parser.leave_block = _leaveBlock;
    parser.enter_span = _enterSpan;
    parser.leave_span = _leaveSpan;
    parser.text = _text;
    parser.debug_log = nullptr;
    parser.syntax = nullptr;

    md_parse(text.data(), static_cast<MD_SIZE>(text.size()), &parser, &ctx);
    _normalizeDocument(outDoc);

    // Reserve a tiny tail so begin()+textOffset is always dereferenceable
    // even for zero-length runs at the very end.
    outDoc.textBuffer.push_back('\0');
    outDoc.textBuffer.pop_back();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
