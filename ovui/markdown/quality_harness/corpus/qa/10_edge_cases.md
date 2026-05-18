# Edge Cases

## Empty sections

## (the heading above has no body)

### (empty h3 followed immediately by another heading)

###

(Above: a literally empty h3.)

## Backslash escapes

Escaped asterisks: \*not italic\* and \*\*not bold\*\*.

Escaped backtick: \`not code\`.

Escaped brackets: \[not a link\](still text).

Escaped hash: \# not a heading when at line start.

A paragraph with a literal backslash \\ in it.

## HTML entities

Ampersand: AT&amp;T.

Copyright: &copy; 2026.

Em dash: &mdash; en dash: &ndash; ellipsis: &hellip;.

Arrows: &larr; &uarr; &rarr; &darr;.

Quotes: &quot;double&quot; and &apos;single&apos;.

Less/greater: &lt;tag&gt;.

Non-breaking space: a&nbsp;b&nbsp;c.

## Deeply nested structures

> - quote containing a list
>   - with a nested list
>     - with a deeper nested list
>       > containing a quote
>       >
>       > > containing a deeper quote
>       > >
>       > > with `inline code` at the leaf.

## Unicode

Latin-1: café, naïve, résumé.

CJK: 你好世界 — 日本語 — 한국어.

Arabic: مرحبا بالعالم.

Hebrew: שלום עולם.

Emoji: 🚀 🎉 ✅ ❌ 🌈 🔥.

Math: α β γ δ ≈ ≠ ≤ ≥ ∞ ∫ √ ∑.

## Very long words

A_really_long_identifier_with_underscores_that_does_not_break_naturally_at_whitespace_and_tests_overflow_behaviour_at_the_wrap_boundary.

Shorter-but-still-longish-hyphenated-identifier-for-wrap-testing.

## Tight numbering edges

1. one
1. one (auto-renumber)
1. one (still auto)

## Mixed edge paragraph

A paragraph with **bold `code-in-bold`**, *italic with a
[link](https://example.com) inside*, and a trailing backslash-newline\
hard break followed by ~~strike with **bold** inside~~ and finally
`inline code with ***syntax*** that should not parse inside code`.
