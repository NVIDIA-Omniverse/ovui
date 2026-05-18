# UTF-8 edge cases

ASCII followed by emoji: hello world 🎉🚀✨.

Multi-byte CJK: 日本語テスト、中文示例、한국어.

RTL Hebrew then Arabic: שלום עולם والسلام عليكم.

Combining marks: a\u0301e\u0300 café naïve.

Zero-width joiner emoji family: 👨‍👩‍👧‍👦 and flag 🇯🇵.

A lone byte that looks like a surrogate high: invalid bytes skipped by parser.

Mixed line: English + 中文 + 🔥 + עברית + العربية end.
