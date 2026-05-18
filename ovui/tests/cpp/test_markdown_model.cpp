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

#include "markdown/MarkdownRenderer.h"
#include "markdown/MarkdownSyntaxHighlighter.h"
#include "markdown/MarkdownTableLayout.h"

#include <md4c.h>

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

using namespace omni::ui;

namespace
{

void require(bool condition, const char* message)
{
    if (!condition)
    {
        std::cerr << "FAIL: " << message << std::endl;
        std::exit(1);
    }
}

std::string tokenText(const MarkdownDocument& doc, const MdToken& token)
{
    return doc.textBuffer.substr(token.textOffset, token.textLen);
}

std::vector<MdToken> quoteEnterTokens(const MarkdownDocument& doc)
{
    std::vector<MdToken> out;
    for (const MdToken& token : doc.tokens)
    {
        if (token.kind == MdToken::EnterBlock && token.blockType == MD_BLOCK_QUOTE)
            out.push_back(token);
    }
    return out;
}

bool visibleTextContains(const MarkdownDocument& doc, const std::string& needle)
{
    for (const MdToken& token : doc.tokens)
    {
        if (token.kind == MdToken::Text && !token.hidden && tokenText(doc, token).find(needle) != std::string::npos)
            return true;
    }
    return false;
}

bool hiddenTextContains(const MarkdownDocument& doc, const std::string& needle)
{
    for (const MdToken& token : doc.tokens)
    {
        if (token.kind == MdToken::Text && token.hidden && tokenText(doc, token).find(needle) != std::string::npos)
            return true;
    }
    return false;
}

bool hasToken(const std::vector<MarkdownSyntaxToken>& tokens,
              MarkdownSyntaxKind kind,
              size_t offset,
              size_t length)
{
    for (const MarkdownSyntaxToken& token : tokens)
    {
        if (token.kind == kind && token.offset == offset && token.length == length)
            return true;
    }
    return false;
}

void testAlertMarkers()
{
    MarkdownDocument doc;
    parseMarkdown("> [!NOTE]\n> Body", doc);
    std::vector<MdToken> quotes = quoteEnterTokens(doc);
    require(quotes.size() == 1, "single note quote parsed");
    require(quotes[0].alertKind == 1, "note alert kind set");
    require(hiddenTextContains(doc, "[!NOTE]"), "marker-only alert token hidden");
    require(!visibleTextContains(doc, "[!NOTE]"), "marker-only alert token not visible");
    require(visibleTextContains(doc, "Body"), "alert body remains visible");

    parseMarkdown("> [!WARNING] Keep this suffix\n> Body", doc);
    quotes = quoteEnterTokens(doc);
    require(quotes.size() == 1, "single warning quote parsed");
    require(quotes[0].alertKind == 4, "warning alert kind set");
    require(!visibleTextContains(doc, "[!WARNING]"), "inline alert marker stripped");
    require(visibleTextContains(doc, "Keep this suffix"), "inline alert marker suffix preserved");

    parseMarkdown("> Outer quote\n> > [!TIP]\n> > Nested body", doc);
    quotes = quoteEnterTokens(doc);
    require(quotes.size() == 2, "nested blockquotes parsed");
    require(quotes[0].alertKind == 0, "outer non-alert quote remains non-alert");
    require(quotes[1].alertKind == 2, "nested alert quote detected");
    require(!visibleTextContains(doc, "[!TIP]"), "nested alert marker hidden");

    parseMarkdown("> [!NOPE]\n> Body", doc);
    quotes = quoteEnterTokens(doc);
    require(quotes.size() == 1, "non-alert quote parsed");
    require(quotes[0].alertKind == 0, "unknown marker is not an alert");
    require(visibleTextContains(doc, "[!NOPE]"), "unknown marker remains visible");
}

void testSyntaxTokens()
{
    std::vector<MarkdownSyntaxToken> tokens;

    std::string python = "def f(x):\n    return \"ok\" # yes";
    require(highlightMarkdownCode("python", python, tokens), "python highlighter enabled");
    require(hasToken(tokens, MarkdownSyntaxKind::Keyword, 0, 3), "python def keyword");
    require(hasToken(tokens, MarkdownSyntaxKind::Keyword, python.find("return"), 6), "python return keyword");
    require(hasToken(tokens, MarkdownSyntaxKind::String, python.find("\"ok\""), 4), "python string");
    require(hasToken(tokens, MarkdownSyntaxKind::Comment, python.find("# yes"), 5), "python comment");

    std::string cpp = "int main(){ return 42; // done\n}";
    require(highlightMarkdownCode("cpp", cpp, tokens), "cpp highlighter enabled");
    require(hasToken(tokens, MarkdownSyntaxKind::Keyword, 0, 3), "cpp int keyword");
    require(hasToken(tokens, MarkdownSyntaxKind::Keyword, cpp.find("return"), 6), "cpp return keyword");
    require(hasToken(tokens, MarkdownSyntaxKind::Number, cpp.find("42"), 2), "cpp number");
    require(hasToken(tokens, MarkdownSyntaxKind::Comment, cpp.find("// done"), 7), "cpp comment");

    std::string json = "{\"ok\": true, \"n\": 2}";
    require(highlightMarkdownCode("json", json, tokens), "json highlighter enabled");
    require(hasToken(tokens, MarkdownSyntaxKind::String, json.find("\"ok\""), 4), "json key string");
    require(hasToken(tokens, MarkdownSyntaxKind::Keyword, json.find("true"), 4), "json true keyword");
    require(hasToken(tokens, MarkdownSyntaxKind::Number, json.find("2"), 1), "json number");

    std::string bash = "echo \"hi\" # comment\nif true; then echo ok; fi";
    require(highlightMarkdownCode("bash", bash, tokens), "bash highlighter enabled");
    require(hasToken(tokens, MarkdownSyntaxKind::Keyword, 0, 4), "bash echo keyword");
    require(hasToken(tokens, MarkdownSyntaxKind::String, bash.find("\"hi\""), 4), "bash string");
    require(hasToken(tokens, MarkdownSyntaxKind::Comment, bash.find("# comment"), 9), "bash comment");
    require(hasToken(tokens, MarkdownSyntaxKind::Keyword, bash.find("if"), 2), "bash if keyword");

    require(!highlightMarkdownCode("mermaid", "graph TD; A-->B", tokens), "unknown language falls back");
    require(tokens.empty(), "unknown language produces no tokens");
}

void testTableLayout()
{
    std::vector<MarkdownTableColumnMeasure> measures = {
        { 40.0f, 50.0f },
        { 60.0f, 180.0f },
        { 30.0f, 80.0f },
    };

    auto equal = computeMarkdownTableColumnLayout(
        MarkdownTableLayoutPolicy::Equal, measures, 300.0f, 32.0f, 400.0f, 90.0f);
    require(equal.columnWidths.size() == 3, "equal layout column count");
    require(std::fabs(equal.columnWidths[0] - 100.0f) < 0.01f, "equal layout width");
    require(!equal.clipped, "equal layout not clipped");

    auto fit = computeMarkdownTableColumnLayout(
        MarkdownTableLayoutPolicy::ContentFit, measures, 300.0f, 32.0f, 400.0f, 90.0f);
    require(fit.columnWidths.size() == 3, "content-fit layout column count");
    require(fit.columnWidths[1] > fit.columnWidths[0], "content-fit favors wider content");
    require(std::fabs(fit.tableWidth - 300.0f) < 0.01f, "content-fit fills available width");
    require(!fit.clipped, "content-fit not clipped");

    auto fixed = computeMarkdownTableColumnLayout(
        MarkdownTableLayoutPolicy::Fixed, measures, 300.0f, 32.0f, 400.0f, 90.0f);
    require(fixed.columnWidths.size() == 3, "fixed layout column count");
    require(std::fabs(fixed.tableWidth - 270.0f) < 0.01f, "fixed layout table width");
    require(!fixed.clipped, "fixed layout not clipped when it fits");

    auto clipped = computeMarkdownTableColumnLayout(
        MarkdownTableLayoutPolicy::Clipped,
        { { 80.0f, 500.0f }, { 80.0f, 500.0f } },
        300.0f, 48.0f, 600.0f, 90.0f);
    require(clipped.columnWidths.size() == 2, "clipped layout column count");
    require(clipped.tableWidth > 300.0f, "clipped layout may exceed available width");
    require(clipped.clipped, "clipped layout reports clipping");
}

// ---------------------------------------------------------------------------
// Additional coverage: slug, alerts, OL, task lists, tables, autolinks, code.
// ---------------------------------------------------------------------------

std::string slugFor(const MarkdownDocument& doc, const MdToken& tok)
{
    if (tok.slugLen == 0)
        return {};
    return doc.textBuffer.substr(tok.slugOffset, tok.slugLen);
}

std::vector<MdToken> headingEnterTokens(const MarkdownDocument& doc)
{
    std::vector<MdToken> out;
    for (const MdToken& token : doc.tokens)
    {
        if (token.kind == MdToken::EnterBlock && token.blockType == MD_BLOCK_H)
            out.push_back(token);
    }
    return out;
}

void test_heading_slug_generation()
{
    MarkdownDocument doc;
    // Heading 2 uses U+2014 em-dash (0xE2 0x80 0x94).
    // Heading 3 uses Japanese "日本語" (0xE6 0x97 0xA5 0xE6 0x9C 0xAC 0xE8 0xAA 0x9E).
    parseMarkdown(
        "# Hello World\n\n"
        "## Foo\xe2\x80\x94" "Bar!\n\n"
        "### \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\n\n"
        "#### Hello   World\n",
        doc);

    std::vector<MdToken> headings = headingEnterTokens(doc);
    require(headings.size() == 4, "four headings parsed");

    // GitHub-style slug: lowercase, ASCII punctuation stripped, whitespace
    // collapsed to a single dash.
    require(slugFor(doc, headings[0]) == "hello-world", "hello world slug");

    // The slugifier retains non-ASCII UTF-8 bytes verbatim. Em-dash between
    // two ASCII runs is preserved as-is (no dash substitution).
    require(slugFor(doc, headings[1]) == "foo\xe2\x80\x94""bar",
            "em-dash preserved verbatim in slug");

    // Pure CJK heading: all bytes are non-ASCII, passed through verbatim.
    require(slugFor(doc, headings[2]) == "\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e",
            "CJK slug preserves UTF-8 bytes");

    // md4c + MD_FLAG_COLLAPSEWHITESPACE folds internal whitespace runs, and
    // the second "Hello World" dedupes against the first via numeric suffix.
    require(slugFor(doc, headings[3]) == "hello-world-1", "duplicate slug uses numeric suffix");

    // All slugs should live inside the document text buffer.
    for (const MdToken& h : headings)
    {
        require(h.slugOffset + h.slugLen <= doc.textBuffer.size(),
                "heading slug inside textBuffer");
    }
}

void test_alert_normalization()
{
    // Each of the five recognised alert kinds should set alertKind and hide
    // the marker text.
    struct AlertCase
    {
        const char* marker;
        uint8_t expectedKind;
    };
    static const AlertCase cases[] = {
        { "NOTE", 1 },
        { "TIP", 2 },
        { "IMPORTANT", 3 },
        { "WARNING", 4 },
        { "CAUTION", 5 },
    };

    for (const AlertCase& c : cases)
    {
        MarkdownDocument doc;
        std::string input = std::string("> [!") + c.marker + "]\n> Body line 1.\n> Body line 2.";
        parseMarkdown(input, doc);

        std::vector<MdToken> quotes = quoteEnterTokens(doc);
        require(quotes.size() == 1, "single alert quote parsed");
        require(quotes[0].alertKind == c.expectedKind, "alert kind matches marker");

        std::string marker = std::string("[!") + c.marker + "]";
        require(hiddenTextContains(doc, marker), "alert marker token is hidden");
        require(!visibleTextContains(doc, marker), "alert marker not visible");
        require(visibleTextContains(doc, "Body line 1."), "alert body visible");
    }

    // Negative case: unknown marker keeps alertKind == 0 and text visible.
    MarkdownDocument doc;
    parseMarkdown("> [!FOO]\n> Body", doc);
    std::vector<MdToken> quotes = quoteEnterTokens(doc);
    require(quotes.size() == 1, "single quote for unknown marker");
    require(quotes[0].alertKind == 0, "unknown marker does not set alertKind");
    require(!hiddenTextContains(doc, "[!FOO]"), "unknown marker text not hidden");
    require(visibleTextContains(doc, "[!FOO]"), "unknown marker text remains visible");
}

void test_nested_quote_no_alert_confusion()
{
    MarkdownDocument doc;
    parseMarkdown(
        "> [!NOTE]\n"
        "> outer\n"
        "> > inner\n"
        "> > also inner\n",
        doc);

    std::vector<MdToken> quotes = quoteEnterTokens(doc);
    require(quotes.size() == 2, "outer + nested quote parsed");
    require(quotes[0].alertKind == 1, "outer quote detected as NOTE alert");
    require(quotes[1].alertKind == 0, "inner nested quote has no alertKind");
}

void test_ol_start_preserved()
{
    MarkdownDocument doc;
    parseMarkdown("3. first\n4. second\n", doc);

    bool foundOl = false;
    for (const MdToken& tok : doc.tokens)
    {
        if (tok.kind == MdToken::EnterBlock && tok.blockType == MD_BLOCK_OL)
        {
            require(tok.olStart == 3, "ordered list starts at 3");
            foundOl = true;
            break;
        }
    }
    require(foundOl, "ordered list EnterBlock token present");
}

void test_task_list_items()
{
    MarkdownDocument doc;
    parseMarkdown("- [ ] todo\n- [x] done\n", doc);

    std::vector<MdToken> taskItems;
    for (const MdToken& tok : doc.tokens)
    {
        if (tok.kind == MdToken::EnterBlock && tok.blockType == MD_BLOCK_LI && tok.isTask)
            taskItems.push_back(tok);
    }
    require(taskItems.size() == 2, "two task list items");
    require(taskItems[0].taskMark == ' ', "first task is unchecked");
    require(taskItems[1].taskMark == 'x', "second task is checked");
}

void test_table_column_count_and_alignment()
{
    MarkdownDocument doc;
    parseMarkdown(
        "| A | B | C |\n"
        "|:--|:-:|--:|\n"
        "| 1 | 2 | 3 |\n",
        doc);

    const MdToken* tableTok = nullptr;
    std::vector<const MdToken*> ths;
    for (const MdToken& tok : doc.tokens)
    {
        if (tok.kind == MdToken::EnterBlock && tok.blockType == MD_BLOCK_TABLE)
            tableTok = &tok;
        if (tok.kind == MdToken::EnterBlock && tok.blockType == MD_BLOCK_TH)
            ths.push_back(&tok);
    }
    require(tableTok != nullptr, "table EnterBlock present");
    require(tableTok->tableCols == 3, "table reports 3 columns");
    require(ths.size() == 3, "three TH cells");
    require(ths[0]->cellAlign == 1, "first column left-aligned");
    require(ths[1]->cellAlign == 2, "second column center-aligned");
    require(ths[2]->cellAlign == 3, "third column right-aligned");
}

void test_autolink_detected()
{
    MarkdownDocument doc;
    parseMarkdown("<https://example.com>\n", doc);

    bool foundAutolink = false;
    for (const MdToken& tok : doc.tokens)
    {
        if (tok.kind == MdToken::EnterSpan && tok.spanType == MD_SPAN_A)
        {
            require(tok.isAutolink == 1, "autolink span marked");
            foundAutolink = true;
            break;
        }
    }
    require(foundAutolink, "autolink span produced");
}

void test_fenced_code_language()
{
    MarkdownDocument doc;
    parseMarkdown("```python\nprint(1)\n```\n", doc);

    bool foundCode = false;
    for (const MdToken& tok : doc.tokens)
    {
        if (tok.kind == MdToken::EnterBlock && tok.blockType == MD_BLOCK_CODE)
        {
            require(tok.codeLangLen == 6, "python info string length");
            require(tok.codeLangOffset + tok.codeLangLen <= doc.textBuffer.size(),
                    "code lang offset inside textBuffer");
            std::string lang = doc.textBuffer.substr(tok.codeLangOffset, tok.codeLangLen);
            require(lang == "python", "fenced code language recorded");
            foundCode = true;
            break;
        }
    }
    require(foundCode, "fenced code block present");
}

} // namespace

int main()
{
    testAlertMarkers();
    testSyntaxTokens();
    testTableLayout();
    test_heading_slug_generation();
    test_alert_normalization();
    test_nested_quote_no_alert_confusion();
    test_ol_start_preserved();
    test_task_list_items();
    test_table_column_count_and_alignment();
    test_autolink_detected();
    test_fenced_code_language();
    std::cout << "markdown_model_tests: ok" << std::endl;
    return 0;
}
