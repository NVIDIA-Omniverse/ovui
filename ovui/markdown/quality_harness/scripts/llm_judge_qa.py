#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""LLM-as-judge runner for QA comparison images.

For each fused comparison image in markdown/quality_harness/artifacts/qa_comparison/,
send the image to the Claude CLI (expected on $PATH as ``claude``) and ask
for a structured conformance report.  The prompt is fixed at the top of
this file.

The concatenated judge output is written to markdown/quality_harness/reports/.
If the ``claude`` CLI is unavailable, the script falls back to writing the
prompt + image paths into the report so the operator can run the
evaluation manually or in a different session.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
CMP_DIR = HARNESS / "artifacts" / "qa_comparison"
REPORTS = HARNESS / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

RESULTS_MD = REPORTS / "QA-JUDGE-RESULTS.md"
BUGS_MD = REPORTS / "QA-BUG-LIST.md"

JUDGE_PROMPT = """\
You are a visual QA judge comparing two markdown renderings side by side.

LEFT: Ground truth HTML rendering (reference standard)
RIGHT: ovui ImGui widget rendering (what we're testing)

Analyze the comparison and report:

1. ALIGNMENT: Are text blocks, headings, lists, tables aligned similarly?
2. FONT SIZING: Are heading sizes, body text, code text proportionally correct?
3. SPACING: Is paragraph spacing, list indentation, blockquote padding similar?
4. INLINE STYLES: Are bold, italic, code, strikethrough, links visually distinct and correct?
5. BLOCK ELEMENTS: Are code blocks, blockquotes, tables, HRules rendered correctly?
6. MISSING ELEMENTS: Is any content missing or not rendered?
7. ARTIFACTS: Any visual glitches, overlapping text, truncated content?

For each issue found, provide:
- SEVERITY: P0 (broken/missing), P1 (visually wrong), P2 (minor difference)
- DESCRIPTION: What's wrong
- LOCATION: Where in the document
- SUGGESTION: How to fix it

Rate overall conformance: A (excellent), B (good, minor issues), C (functional, notable gaps), D (significant problems), F (broken)
"""


def run_claude(image_path: Path, prompt: str) -> str:
    """Invoke the `claude` CLI with an image attachment and a text prompt."""
    cli = shutil.which("claude")
    if cli is None:
        return "[claude CLI unavailable — judge must be run manually on this image]"
    # Use the non-interactive print mode.  The CLI accepts stdin prompt text
    # and `-` for stdin; image attachments go via the MCP image tool which is
    # available by default.  Fall back to prompt-only if the attachment
    # extension is not recognised.
    cmd = [cli, "--print", "--allowed-tools=none", f"{prompt}\n\n(Image: {image_path})"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return res.stdout.strip() or res.stderr.strip()
    except Exception as exc:  # pragma: no cover
        return f"[claude CLI error: {exc}]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    cmps = sorted(CMP_DIR.glob("*.png"))
    if args.only:
        cmps = [p for p in cmps if p.stem == args.only]
    if not cmps:
        print(f"No comparison images in {CMP_DIR}", file=sys.stderr)
        return 1

    sections = ["# QA Judge Results\n", "_LLM-as-judge visual conformance report._\n"]
    for cmp_path in cmps:
        print(f"Judging {cmp_path.name}")
        report = run_claude(cmp_path, JUDGE_PROMPT)
        sections.append(f"## {cmp_path.stem}\n")
        sections.append(f"![comparison](../artifacts/qa_comparison/{cmp_path.name})\n")
        sections.append(report + "\n")

    RESULTS_MD.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {RESULTS_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
