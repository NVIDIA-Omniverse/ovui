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

#include "MarkdownSyntaxHighlighter.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstring>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace
{

enum class Language
{
    Unknown,
    Python,
    Cpp,
    Json,
    Bash,
};

std::string _lowerFirstWord(std::string_view text)
{
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.front())))
        text.remove_prefix(1);
    size_t end = 0;
    while (end < text.size() && !std::isspace(static_cast<unsigned char>(text[end])))
        ++end;

    std::string out(text.substr(0, end));
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return out;
}

Language _languageFromInfoString(std::string_view language)
{
    std::string lang = _lowerFirstWord(language);
    if (lang == "py" || lang == "python" || lang == "python3")
        return Language::Python;
    if (lang == "c" || lang == "cc" || lang == "cpp" || lang == "c++" || lang == "cxx" || lang == "h"
        || lang == "hpp" || lang == "hxx")
        return Language::Cpp;
    if (lang == "json")
        return Language::Json;
    if (lang == "bash" || lang == "sh" || lang == "shell" || lang == "zsh")
        return Language::Bash;
    return Language::Unknown;
}

bool _isIdentStart(char c)
{
    unsigned char uc = static_cast<unsigned char>(c);
    return std::isalpha(uc) || c == '_';
}

bool _isIdentContinue(char c)
{
    unsigned char uc = static_cast<unsigned char>(c);
    return std::isalnum(uc) || c == '_';
}

bool _isPunctuation(char c)
{
    static constexpr const char* kPunctuation = "{}[]()<>.,:;+-*/%=!&|^~?";
    return std::strchr(kPunctuation, c) != nullptr;
}

bool _isKeyword(Language language, std::string_view word)
{
    static constexpr std::array<std::string_view, 36> kPython = {
        "False", "None", "True", "and", "as", "assert", "async", "await", "break",
        "class", "continue", "def", "del", "elif", "else", "except", "finally",
        "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
        "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
        "match",
    };
    static constexpr std::array<std::string_view, 59> kCpp = {
        "alignas", "alignof", "auto", "bool", "break", "case", "catch", "char",
        "class", "const", "constexpr", "continue", "decltype", "default", "delete",
        "do", "double", "else", "enum", "explicit", "export", "extern", "false",
        "float", "for", "friend", "if", "inline", "int", "long", "mutable",
        "namespace", "new", "noexcept", "nullptr", "operator", "private", "protected",
        "public", "return", "short", "signed", "sizeof", "static", "struct", "switch",
        "template", "this", "throw", "true", "try", "typedef", "typename", "union",
        "unsigned", "using", "virtual", "void", "while",
    };
    static constexpr std::array<std::string_view, 3> kJson = {
        "false", "null", "true",
    };
    static constexpr std::array<std::string_view, 30> kBash = {
        "case", "coproc", "do", "done", "elif", "else", "esac", "export", "fi",
        "for", "function", "if", "in", "local", "readonly", "return", "select",
        "shift", "then", "time", "until", "while", "break", "continue", "declare",
        "echo", "exit", "printf", "source", "test",
    };

    auto contains = [word](const auto& keywords) {
        return std::find(keywords.begin(), keywords.end(), word) != keywords.end();
    };

    switch (language)
    {
    case Language::Python: return contains(kPython);
    case Language::Cpp: return contains(kCpp);
    case Language::Json: return contains(kJson);
    case Language::Bash: return contains(kBash);
    default: return false;
    }
}

void _emit(std::vector<MarkdownSyntaxToken>& tokens, size_t begin, size_t end, MarkdownSyntaxKind kind)
{
    if (end <= begin)
        return;
    tokens.push_back(MarkdownSyntaxToken{ begin, end - begin, kind });
}

size_t _consumeLineComment(std::string_view code, size_t i)
{
    size_t j = i;
    while (j < code.size() && code[j] != '\n' && code[j] != '\r')
        ++j;
    return j;
}

size_t _consumeCString(std::string_view code, size_t i)
{
    char quote = code[i];
    size_t j = i + 1;
    bool escaped = false;
    while (j < code.size())
    {
        char c = code[j++];
        if (escaped)
        {
            escaped = false;
            continue;
        }
        if (c == '\\')
        {
            escaped = true;
            continue;
        }
        if (c == quote)
            break;
        if (c == '\n' || c == '\r')
            break;
    }
    return j;
}

size_t _consumePythonString(std::string_view code, size_t i)
{
    char quote = code[i];
    bool triple = i + 2 < code.size() && code[i + 1] == quote && code[i + 2] == quote;
    size_t j = triple ? i + 3 : i + 1;
    bool escaped = false;
    while (j < code.size())
    {
        if (!triple)
        {
            char c = code[j++];
            if (escaped)
            {
                escaped = false;
                continue;
            }
            if (c == '\\')
            {
                escaped = true;
                continue;
            }
            if (c == quote)
                break;
            if (c == '\n' || c == '\r')
                break;
            continue;
        }

        if (j + 2 < code.size() && code[j] == quote && code[j + 1] == quote && code[j + 2] == quote)
            return j + 3;
        ++j;
    }
    return j;
}

size_t _consumeNumber(std::string_view code, size_t i)
{
    size_t j = i;
    if (j < code.size() && (code[j] == '+' || code[j] == '-'))
        ++j;
    bool seenDot = false;
    while (j < code.size())
    {
        char c = code[j];
        if (std::isdigit(static_cast<unsigned char>(c)) || c == '_')
        {
            ++j;
            continue;
        }
        if (c == '.' && !seenDot)
        {
            seenDot = true;
            ++j;
            continue;
        }
        if ((c == 'e' || c == 'E') && j + 1 < code.size())
        {
            size_t k = j + 1;
            if (code[k] == '+' || code[k] == '-')
                ++k;
            if (k < code.size() && std::isdigit(static_cast<unsigned char>(code[k])))
            {
                j = k + 1;
                while (j < code.size() && std::isdigit(static_cast<unsigned char>(code[j])))
                    ++j;
                continue;
            }
        }
        if ((c == 'x' || c == 'X') && j == i + 1)
        {
            ++j;
            while (j < code.size() && std::isxdigit(static_cast<unsigned char>(code[j])))
                ++j;
        }
        break;
    }
    return j;
}

bool _isNumberStart(std::string_view code, size_t i)
{
    if (std::isdigit(static_cast<unsigned char>(code[i])))
        return true;
    if ((code[i] == '-' || code[i] == '+') && i + 1 < code.size()
        && std::isdigit(static_cast<unsigned char>(code[i + 1])))
        return true;
    return false;
}

} // namespace

bool highlightMarkdownCode(std::string_view language,
                           std::string_view code,
                           std::vector<MarkdownSyntaxToken>& tokens)
{
    tokens.clear();
    Language lang = _languageFromInfoString(language);
    if (lang == Language::Unknown)
        return false;

    size_t i = 0;
    while (i < code.size())
    {
        char c = code[i];

        if ((lang == Language::Python || lang == Language::Bash) && c == '#')
        {
            size_t end = _consumeLineComment(code, i);
            _emit(tokens, i, end, MarkdownSyntaxKind::Comment);
            i = end;
            continue;
        }

        if (lang == Language::Cpp && c == '/' && i + 1 < code.size())
        {
            if (code[i + 1] == '/')
            {
                size_t end = _consumeLineComment(code, i);
                _emit(tokens, i, end, MarkdownSyntaxKind::Comment);
                i = end;
                continue;
            }
            if (code[i + 1] == '*')
            {
                size_t end = i + 2;
                while (end + 1 < code.size() && !(code[end] == '*' && code[end + 1] == '/'))
                    ++end;
                end = (end + 1 < code.size()) ? end + 2 : code.size();
                _emit(tokens, i, end, MarkdownSyntaxKind::Comment);
                i = end;
                continue;
            }
        }

        if (lang == Language::Cpp && c == '#')
        {
            size_t end = _consumeLineComment(code, i);
            _emit(tokens, i, end, MarkdownSyntaxKind::Keyword);
            i = end;
            continue;
        }

        if ((lang == Language::Python && (c == '\'' || c == '"'))
            || (lang == Language::Cpp && (c == '\'' || c == '"'))
            || (lang == Language::Json && c == '"')
            || (lang == Language::Bash && (c == '\'' || c == '"' || c == '`')))
        {
            size_t end = lang == Language::Python ? _consumePythonString(code, i) : _consumeCString(code, i);
            _emit(tokens, i, end, MarkdownSyntaxKind::String);
            i = end;
            continue;
        }

        if (_isNumberStart(code, i))
        {
            size_t end = _consumeNumber(code, i);
            _emit(tokens, i, end, MarkdownSyntaxKind::Number);
            i = end;
            continue;
        }

        if (_isIdentStart(c))
        {
            size_t end = i + 1;
            while (end < code.size() && _isIdentContinue(code[end]))
                ++end;
            if (_isKeyword(lang, code.substr(i, end - i)))
                _emit(tokens, i, end, MarkdownSyntaxKind::Keyword);
            i = end;
            continue;
        }

        if (_isPunctuation(c))
            _emit(tokens, i, i + 1, MarkdownSyntaxKind::Punctuation);
        ++i;
    }

    return true;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
