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

// Fuzz-style robustness runner: feeds every markdown file in the adjacent
// corpus directory through parseMarkdown() and asserts that each completes
// without crashing and emits a self-consistent token stream.
//
// Invariants checked per file:
//   * doc.parsed == true
//   * For every token, textOffset + textLen <= textBuffer.size()
//   * For every EnterBlock there is a matching LeaveBlock (by running count)
//   * Same for EnterSpan / LeaveSpan
//   * Heading tokens carry level in 1..6
//   * Slug offsets/lengths stay inside textBuffer
//
#include "markdown/MarkdownRenderer.h"

#include <md4c.h>

#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace omni::ui;

namespace
{

void require(bool condition, const std::string& message)
{
    if (!condition)
    {
        std::cerr << "FAIL: " << message << std::endl;
        std::exit(1);
    }
}

std::string readFile(const std::filesystem::path& path)
{
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs)
    {
        std::cerr << "FAIL: unable to open " << path << std::endl;
        std::exit(1);
    }
    std::ostringstream os;
    os << ifs.rdbuf();
    return os.str();
}

void validateInvariants(const MarkdownDocument& doc, const std::string& label)
{
    require(doc.parsed, label + ": doc.parsed == true");

    int blockDepth = 0;
    int spanDepth = 0;
    const size_t bufSize = doc.textBuffer.size();

    for (size_t i = 0; i < doc.tokens.size(); ++i)
    {
        const MdToken& tok = doc.tokens[i];

        // Offsets stay inside the text buffer (note: zero-length tokens are
        // fine even with offset == bufSize).
        require(static_cast<size_t>(tok.textOffset) + tok.textLen <= bufSize,
                label + ": token textOffset+textLen within textBuffer");
        require(static_cast<size_t>(tok.titleOffset) + tok.titleLen <= bufSize,
                label + ": token titleOffset+titleLen within textBuffer");
        require(static_cast<size_t>(tok.codeLangOffset) + tok.codeLangLen <= bufSize,
                label + ": token codeLangOffset+codeLangLen within textBuffer");
        require(static_cast<size_t>(tok.slugOffset) + tok.slugLen <= bufSize,
                label + ": token slugOffset+slugLen within textBuffer");

        switch (tok.kind)
        {
            case MdToken::EnterBlock:
                ++blockDepth;
                if (tok.blockType == MD_BLOCK_H)
                {
                    require(tok.level >= 1 && tok.level <= 6,
                            label + ": heading level within 1..6");
                }
                break;
            case MdToken::LeaveBlock:
                require(blockDepth > 0, label + ": LeaveBlock with no matching EnterBlock");
                --blockDepth;
                break;
            case MdToken::EnterSpan:
                ++spanDepth;
                break;
            case MdToken::LeaveSpan:
                require(spanDepth > 0, label + ": LeaveSpan with no matching EnterSpan");
                --spanDepth;
                break;
            case MdToken::Text:
            case MdToken::SoftBreak:
            case MdToken::HardBreak:
                break;
        }
    }

    require(blockDepth == 0, label + ": balanced EnterBlock/LeaveBlock");
    require(spanDepth == 0, label + ": balanced EnterSpan/LeaveSpan");

    for (const MdHeading& h : doc.headings)
    {
        require(h.level >= 1 && h.level <= 6, label + ": heading level in 1..6");
        require(static_cast<size_t>(h.textOffset) + h.textLen <= bufSize,
                label + ": heading textOffset/len within textBuffer");
        require(static_cast<size_t>(h.slugOffset) + h.slugLen <= bufSize,
                label + ": heading slugOffset/len within textBuffer");
    }
}

std::filesystem::path resolveCorpusDir()
{
    // Prefer env override for out-of-tree builds.
    if (const char* envDir = std::getenv("OMNI_UI_MARKDOWN_FUZZ_CORPUS"))
    {
        std::filesystem::path p(envDir);
        if (std::filesystem::is_directory(p))
            return p;
    }

    // Compile-time default baked in by CMake points at the in-tree corpus so
    // the test binary works right after `cmake --build` without any env vars.
#ifdef OMNI_UI_MARKDOWN_FUZZ_CORPUS_DEFAULT
    {
        std::filesystem::path p(OMNI_UI_MARKDOWN_FUZZ_CORPUS_DEFAULT);
        if (std::filesystem::is_directory(p))
            return p;
    }
#endif

    // Walk upward from cwd as a last-resort fallback (useful when running the
    // binary from arbitrary out-of-tree build directories).
    std::filesystem::path cwd = std::filesystem::current_path();
    for (int depth = 0; depth < 6; ++depth)
    {
        std::filesystem::path candidate = cwd / "tests" / "markdown_fuzz_corpus";
        if (std::filesystem::is_directory(candidate))
            return candidate;
        if (!cwd.has_parent_path())
            break;
        cwd = cwd.parent_path();
    }

    std::cerr << "FAIL: could not locate tests/markdown_fuzz_corpus "
                 "(set OMNI_UI_MARKDOWN_FUZZ_CORPUS to override)"
              << std::endl;
    std::exit(1);
}

} // namespace

int main()
{
    std::filesystem::path corpus = resolveCorpusDir();
    std::vector<std::filesystem::path> files;
    for (const auto& entry : std::filesystem::directory_iterator(corpus))
    {
        if (!entry.is_regular_file())
            continue;
        if (entry.path().extension() != ".md")
            continue;
        files.push_back(entry.path());
    }

    require(!files.empty(), "corpus contains at least one .md file");
    std::sort(files.begin(), files.end());

    for (const auto& path : files)
    {
        std::string text = readFile(path);
        MarkdownDocument doc;
        parseMarkdown(text, doc);
        validateInvariants(doc, path.filename().string());
    }

    std::cout << "markdown_fuzz_tests: ok (" << files.size() << " files)" << std::endl;
    return 0;
}
