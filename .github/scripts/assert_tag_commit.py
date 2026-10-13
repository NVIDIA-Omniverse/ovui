#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Check the release tag exists and still names the verified commit.

Everything upstream of the upload works from a commit that was resolved ONCE,
early in the run: the release event's SHA, or the ref the dispatch named. A tag
is mutable. If it is repointed between that moment and the upload, every earlier
gate still passes — they were asked about the old commit — and the wheels land
on a release whose tag now names something else.

So the tag is resolved again here, at the last moment before `gh release upload`.

TWO THINGS ARE CHECKED, NOT ONE
-------------------------------
`repos/<repo>/commits/<ref>` resolves ANY committish: a tag, a branch, or a raw
SHA. An earlier version of this script used it, so a ref that was not a tag at
all still satisfied "the tag names the right commit" — a branch of the same name
was enough, and a publication did not require the release tag to exist.

A publication therefore resolves through the TAG NAMESPACE only:
`repos/<repo>/git/ref/tags/<tag>`, which 404s for anything that is not a tag.
An annotated tag points at a tag object, so the result is PEELED through
`repos/<repo>/git/tags/<sha>` until a commit is reached.

Manual verification may name a branch before a tag exists. Without
`--require-tag`, that fallback is allowed and reported as a rehearsal. The
publishing workflow always passes `--require-tag`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

MAX_PEEL = 10


def _api(path: str, jq: str | None = None) -> tuple[int, str]:
    cmd = ["gh", "api", path]
    if jq:
        cmd += ["--jq", jq]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return out.returncode, out.stdout.strip()


def resolve_tag(repo: str, tag: str) -> str | None:
    """Return the commit a TAG names, peeling annotated tags. None if no tag."""
    code, raw = _api(f"repos/{repo}/git/ref/tags/{tag}")
    if code != 0 or not raw:
        return None
    obj = json.loads(raw)["object"]
    sha, kind = obj["sha"], obj["type"]
    for _ in range(MAX_PEEL):
        if kind == "commit":
            return sha
        if kind != "tag":
            return None
        code, raw = _api(f"repos/{repo}/git/tags/{sha}")
        if code != 0 or not raw:
            return None
        obj = json.loads(raw)["object"]
        sha, kind = obj["sha"], obj["type"]
    return None


def resolve_committish(repo: str, ref: str) -> str | None:
    """Return the commit ANY ref names. Rehearsal only — never for a release."""
    code, sha = _api(f"repos/{repo}/commits/{ref}", ".sha")
    return sha if code == 0 and sha else None


def compare(tag: str, actual: str, expected: str) -> int:
    if not actual:
        print(
            f"::error title=Release tag did not resolve::'{tag}' names no commit.",
            file=sys.stderr,
        )
        return 1
    if actual != expected:
        print(
            f"::error title=Release tag moved::'{tag}' now names commit {actual}, but the "
            f"wheels about to be uploaded were built and verified from {expected}. "
            f"Nothing is uploaded. Re-run the release for the commit the tag names.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: '{tag}' still names {actual}, the commit the wheels were built from")
    return 0


def run(repo: str, tag: str, expected: str, require_tag: bool) -> int:
    actual = resolve_tag(repo, tag) if repo else None
    if actual is not None:
        print(f"tag '{tag}' resolves to {actual}")
        return compare(tag, actual, expected)

    if require_tag:
        print(
            f"::error title=Release tag does not exist::'refs/tags/{tag}' was not found. A "
            f"release must be published on a real tag: a branch or a commit of the same name "
            f"is not one, and nothing is uploaded without it.",
            file=sys.stderr,
        )
        return 1

    # Rehearsal: no such tag, so fall back to any committish and say so.
    actual = resolve_committish(repo, tag)
    print(
        f"::warning title=Rehearsal against a non-tag ref::'refs/tags/{tag}' does not exist. "
        f"Resolving '{tag}' as an ordinary ref. A publication would stop here."
    )
    return compare(tag, actual or "", expected)


def selftest() -> int:
    """Prove the comparison rejects a moved tag and an unresolvable one."""
    good = "a" * 40
    moved = "b" * 40
    cases = [
        ("the tag still names the verified commit", good, 0),
        ("the tag was repointed to another commit", moved, 1),
        ("the tag resolves to nothing", "", 1),
    ]
    failures = 0
    for label, actual, want in cases:
        print(f"selftest: {label}")
        got = 1 if compare("v0.0.0-selftest", actual, good) != 0 else 0
        if got != want:
            verb = "rejected" if want else "accepted"
            print(f"SELFTEST FAILED: {label} should have been {verb}", file=sys.stderr)
            failures += 1
    if failures:
        return 1
    print("SELFTEST OK: the check accepts a tag that still names the verified commit "
          "and rejects a moved or unresolvable one")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="owner/name, for resolving the tag")
    parser.add_argument("--tag", help="the release tag to resolve")
    parser.add_argument("--expected", help="the commit the wheels were verified against")
    parser.add_argument(
        "--require-tag",
        action="store_true",
        help="refuse anything that is not a real tag. The publishing path passes this.",
    )
    parser.add_argument(
        "--actual",
        help="skip resolution and compare this commit instead (for a mocked tag move)",
    )
    parser.add_argument("--selftest", action="store_true", help="prove the check can fail")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.tag or not args.expected:
        parser.error("--tag and --expected are required unless --selftest is given")
    if args.actual is not None:
        return compare(args.tag, args.actual, args.expected)
    if not args.repo:
        parser.error("--repo is required when --actual is not given")
    return run(args.repo, args.tag, args.expected, args.require_tag)


if __name__ == "__main__":
    raise SystemExit(main())
